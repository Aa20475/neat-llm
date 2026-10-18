"""SQLite control state and replay records. No model has a connection to this store."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import sqlite3
import threading
from uuid import uuid4

from company.organization import canonical_json, digest, validate_manifest


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS versions (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, manifest TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS immutable_version_update BEFORE UPDATE ON versions
                BEGIN SELECT RAISE(ABORT, 'Versions are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_version_delete BEFORE DELETE ON versions
                BEGIN SELECT RAISE(ABORT, 'Versions are immutable'); END;
            CREATE TABLE IF NOT EXISTS organization (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                active_version TEXT NOT NULL REFERENCES versions(id), generation INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES versions(id),
                generation INTEGER NOT NULL, task_id TEXT NOT NULL, split TEXT NOT NULL,
                prompt TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT,
                status TEXT NOT NULL, output TEXT, grade TEXT, usage TEXT, error TEXT);
            CREATE TABLE IF NOT EXISTS events (
                run_id TEXT NOT NULL REFERENCES runs(id), seq INTEGER NOT NULL,
                timestamp TEXT NOT NULL, kind TEXT NOT NULL, worker_id TEXT,
                payload TEXT NOT NULL, PRIMARY KEY(run_id,seq));
            CREATE TABLE IF NOT EXISTS workers (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                parent_id TEXT REFERENCES workers(id), role TEXT NOT NULL, temporary INTEGER NOT NULL,
                task TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT);
            CREATE TABLE IF NOT EXISTS reflections (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, base_version TEXT NOT NULL REFERENCES versions(id),
                base_generation INTEGER NOT NULL, status TEXT NOT NULL, evidence_ids TEXT NOT NULL,
                memory_ids TEXT NOT NULL, usage TEXT, response TEXT, error TEXT);
            CREATE TABLE IF NOT EXISTS proposals (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, reflection_id TEXT NOT NULL REFERENCES reflections(id),
                base_version TEXT NOT NULL REFERENCES versions(id), base_generation INTEGER NOT NULL,
                candidate_version TEXT NOT NULL REFERENCES versions(id), document TEXT NOT NULL,
                status TEXT NOT NULL, reason TEXT, evaluation TEXT);
            CREATE TABLE IF NOT EXISTS reflection_memory (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, reflection_id TEXT NOT NULL REFERENCES reflections(id),
                proposal_id TEXT REFERENCES proposals(id), outcome TEXT NOT NULL, lesson TEXT NOT NULL, evidence TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS activations (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, from_version TEXT NOT NULL REFERENCES versions(id),
                to_version TEXT NOT NULL REFERENCES versions(id), generation INTEGER NOT NULL UNIQUE,
                proposal_id TEXT NOT NULL REFERENCES proposals(id), reason TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audits (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, suite_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL, plan TEXT NOT NULL, report TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS immutable_audit_plan BEFORE UPDATE OF plan,suite_id ON audits
                BEGIN SELECT RAISE(ABORT, 'Audit plans are immutable'); END;
            CREATE TABLE IF NOT EXISTS chat_threads (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, title TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS chat_turns (
                id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES chat_threads(id),
                created_at TEXT NOT NULL, prompt TEXT NOT NULL, status TEXT NOT NULL,
                run_id TEXT REFERENCES runs(id), error TEXT);
            CREATE TABLE IF NOT EXISTS learning_exclusions (
                run_id TEXT PRIMARY KEY REFERENCES runs(id), excluded_at TEXT NOT NULL, reason TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS actions (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, kind TEXT NOT NULL,
                status TEXT NOT NULL, result TEXT, error TEXT);
        """)

    def close(self):
        self.db.close()

    def initialize(self, manifest: dict) -> dict:
        """Seed once. Restarting must never reset the active pointer."""
        with self._lock, self.db:
            if not self.db.execute("SELECT 1 FROM organization").fetchone():
                version_id = digest(manifest)
                self.db.execute("INSERT INTO versions VALUES (?,?,?)", (version_id, now(), canonical_json(manifest)))
                self.db.execute("INSERT INTO organization VALUES (1,?,0)", (version_id,))
        return self.active()

    def active(self) -> dict:
        row = self.db.execute("SELECT active_version,generation FROM organization WHERE singleton=1").fetchone()
        if row is None:
            raise ValueError("Organization is not initialized; run `python -m company init`")
        return {"version_id": row["active_version"], "generation": row["generation"], "manifest": self.manifest(row["active_version"])}

    def remove_budgets(self, max_tokens: int = 4096) -> dict:
        """Explicit operator settings change, never a reflection promotion. Caller holds controller lock."""
        with self._lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            for table, status in (("runs", "running"), ("reflections", "running"),
                                  ("actions", "running"), ("proposals", "evaluating")):
                if self.db.execute(f"SELECT 1 FROM {table} WHERE status=?", (status,)).fetchone():
                    raise ValueError("Wait for the current task or reflection to finish before changing settings")
            active = self.active()
            manifest = deepcopy(active["manifest"])
            for key in ("model_calls", "tool_calls", "workers", "wall_seconds"):
                manifest["limits"][key] = None
            manifest["inference"]["max_tokens"] = max_tokens
            if manifest == active["manifest"]:
                return active
            manifest["label"] = active["manifest"]["label"] + "-unlimited"
            validate_manifest(manifest)
            version_id, generation = digest(manifest), active["generation"] + 1
            self.db.execute("INSERT OR IGNORE INTO versions VALUES (?,?,?)", (version_id, now(), canonical_json(manifest)))
            self.db.execute("UPDATE organization SET active_version=?,generation=? WHERE singleton=1", (version_id, generation))
            result = {"from_version": active["version_id"], "to_version": version_id, "generation": generation,
                      "reason": "User removed aggregate execution budgets", "limits": manifest["limits"], "max_tokens": max_tokens}
            self.db.execute("INSERT INTO actions VALUES (?,?,?,?,?,?)", (
                uuid4().hex, now(), "runtime_settings", "completed", canonical_json(result), None))
        return self.active()

    def manifest(self, version_id: str) -> dict:
        row = self.db.execute("SELECT manifest FROM versions WHERE id=?", (version_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown organization version")
        result = json.loads(row["manifest"])
        if digest(result) != version_id:
            raise ValueError("Stored manifest digest does not match")
        return result

    @contextmanager
    def controller(self):
        """One writer process runs agents; readers can inspect the live trace."""
        with self.path.with_suffix(self.path.suffix + ".lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Another controller is running this organization") from None
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def start_run(self, task_id: str, split: str, prompt: str, version_id: str | None = None) -> dict:
        with self._lock, self.db:
            # Pin the pointer and create the run in one transaction.
            self.db.execute("BEGIN IMMEDIATE")
            active = self.active()
            if version_id is not None:
                active = {"version_id": version_id, "generation": active["generation"], "manifest": self.manifest(version_id)}
            run_id = uuid4().hex
            self.db.execute("INSERT INTO runs (id,version_id,generation,task_id,split,prompt,started_at,status) VALUES (?,?,?,?,?,?,?,?)",
                            (run_id, active["version_id"], active["generation"], task_id, split, prompt, now(), "running"))
        self.worker_start(run_id, run_id + ":root", None, "generalist", False, prompt)
        self.event(run_id, "run_started", run_id + ":root", {"version_id": active["version_id"], "generation": active["generation"], "task_id": task_id})
        return {"id": run_id, **active}

    def event(self, run_id: str, kind: str, worker_id: str | None, payload: dict):
        with self._lock, self.db:
            self.db.execute("INSERT INTO events SELECT ?,COALESCE(MAX(seq),0)+1,?,?,?,? FROM events WHERE run_id=?",
                            (run_id, now(), kind, worker_id, canonical_json(payload), run_id))

    def worker_start(self, run_id, worker_id, parent_id, role, temporary, task):
        with self._lock, self.db:
            self.db.execute("INSERT INTO workers VALUES (?,?,?,?,?,?,?,?,NULL)",
                            (worker_id, run_id, parent_id, role, int(temporary), task, "running", now()))

    def worker_finish(self, worker_id, status):
        with self._lock, self.db:
            self.db.execute("UPDATE workers SET status=?,ended_at=? WHERE id=? AND status='running'", (status, now(), worker_id))

    def finish(self, run_id, status, output, grade, usage, error=None):
        with self._lock, self.db:
            self.db.execute("UPDATE runs SET ended_at=?,status=?,output=?,grade=?,usage=?,error=? WHERE id=? AND status='running'",
                            (now(), status, output, canonical_json(grade), canonical_json(usage), error, run_id))
            self.db.execute("UPDATE workers SET ended_at=?,status=? WHERE run_id=? AND status='running'", (now(), status, run_id))
            self.event(run_id, "run_finished", run_id + ":root", {"status": status, "grade": grade, "usage": usage, "error": error})

    def recover_interrupted(self):
        """Call only while holding controller lock; never pretend to resume an LLM turn."""
        for row in self.db.execute("SELECT id FROM runs WHERE status='running'").fetchall():
            self.finish(row["id"], "interrupted", None, None, {"complete": False}, "Previous controller exited before finalizing this run")
        with self._lock, self.db:
            self.db.execute("UPDATE reflections SET status='interrupted',error='Previous controller exited' WHERE status='running'")
            self.db.execute("UPDATE actions SET status='interrupted',error='Previous controller exited' WHERE status='running'")
            for row in self.db.execute("SELECT id,report FROM audits WHERE status='running'").fetchall():
                report = json.loads(row["report"])
                report.update(reason="Previous controller exited; held-out suite remains consumed")
                self.db.execute("UPDATE audits SET status='inconclusive',report=? WHERE id=?", (canonical_json(report), row["id"]))
            for row in self.db.execute("SELECT id,evaluation FROM proposals WHERE status='evaluating'").fetchall():
                report = json.loads(row["evaluation"])
                report.update(decision="inconclusive", reason="Previous controller exited during evaluation")
                self.db.execute("UPDATE proposals SET status='inconclusive',reason=?,evaluation=? WHERE id=?", (report["reason"], canonical_json(report), row["id"]))
            for row in self.db.execute("SELECT chat_turns.id,runs.status FROM chat_turns LEFT JOIN runs ON chat_turns.run_id=runs.id WHERE chat_turns.status='running'").fetchall():
                status = "completed" if row["status"] == "completed" else "interrupted"
                self.db.execute("UPDATE chat_turns SET status=?,error=? WHERE id=?", (
                    status, None if status == "completed" else "Previous controller exited; send a new message to continue", row["id"]))

    def history(self) -> list[dict]:
        rows = self.db.execute("SELECT id,version_id,generation,task_id,split,started_at,status,grade,usage,"
                               "EXISTS(SELECT 1 FROM learning_exclusions e WHERE e.run_id=runs.id) AS reflection_excluded "
                               "FROM runs ORDER BY started_at DESC").fetchall()
        return [self._decode(dict(row), ("grade", "usage")) for row in rows]

    @staticmethod
    def _decode(row, columns):
        for column in columns:
            if row[column] is not None:
                row[column] = json.loads(row[column])
        return row

    def replay(self, run_id: str) -> dict:
        row = self.db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown run ID")
        run = self._decode(dict(row), ("grade", "usage"))
        workers = [dict(row) for row in self.db.execute("SELECT * FROM workers WHERE run_id=? ORDER BY started_at", (run_id,))]
        events = [self._decode(dict(row), ("payload",)) for row in self.db.execute("SELECT * FROM events WHERE run_id=? ORDER BY seq", (run_id,))]
        return {"schema_version": 1, "run": run, "organization": self.manifest(run["version_id"]), "workers": workers, "events": events}

    def save_version(self, manifest: dict) -> str:
        version_id = digest(manifest)
        with self._lock, self.db:
            self.db.execute("INSERT OR IGNORE INTO versions VALUES (?,?,?)", (version_id, now(), canonical_json(manifest)))
        return version_id

    def start_chat_turn(self, prompt: str, thread_id: str | None = None) -> dict:
        turn_id = uuid4().hex
        with self._lock, self.db:
            if thread_id is None:
                thread_id = uuid4().hex
                self.db.execute("INSERT INTO chat_threads VALUES (?,?,?)", (thread_id, now(), prompt[:60]))
            elif not self.db.execute("SELECT 1 FROM chat_threads WHERE id=?", (thread_id,)).fetchone():
                raise ValueError("Unknown conversation")
            self.db.execute("INSERT INTO chat_turns VALUES (?,?,?,?,?,?,?)", (turn_id, thread_id, now(), prompt, "running", None, None))
        return {"id": turn_id, "thread_id": thread_id}

    def start_action(self, kind: str) -> str:
        action_id = uuid4().hex
        with self._lock, self.db:
            self.db.execute("INSERT INTO actions VALUES (?,?,?,?,?,?)", (action_id, now(), kind, "running", None, None))
        return action_id

    def delete_chat_thread(self, thread_id: str) -> dict:
        """Caller holds the controller lock. Preserve evidence referenced by saved experiments."""
        with self._lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if not self.db.execute("SELECT 1 FROM chat_threads WHERE id=?", (thread_id,)).fetchone():
                raise ValueError("Unknown conversation")
            turns = self.db.execute("SELECT run_id,status FROM chat_turns WHERE thread_id=?", (thread_id,)).fetchall()
            run_ids = {row["run_id"] for row in turns if row["run_id"]}
            if any(row["status"] == "running" for row in turns) or any(
                self.db.execute("SELECT 1 FROM runs WHERE id=? AND status='running'", (run_id,)).fetchone()
                for run_id in run_ids
            ):
                raise RuntimeError("Wait for this conversation's task to finish before deleting it")
            referenced = set()
            def collect(value):
                if isinstance(value, str):
                    if value in run_ids:
                        referenced.add(value)
                elif isinstance(value, list):
                    for item in value:
                        collect(item)
                elif isinstance(value, dict):
                    for item in value.values():
                        collect(item)
            for table, fields in (("reflections", ("evidence_ids",)), ("proposals", ("document", "evaluation")),
                                  ("reflection_memory", ("evidence",)), ("audits", ("plan", "report")),
                                  ("actions", ("result",))):
                for row in self.db.execute(f"SELECT {','.join(fields)} FROM {table}"):
                    for value in row:
                        if value:
                            collect(json.loads(value))
            referenced.update(row[0] for row in self.db.execute(
                "SELECT run_id FROM chat_turns WHERE thread_id<>? AND run_id IS NOT NULL", (thread_id,)))
            retained = run_ids & referenced
            self.db.execute("DELETE FROM chat_turns WHERE thread_id=?", (thread_id,))
            self.db.execute("DELETE FROM chat_threads WHERE id=?", (thread_id,))
            for run_id in retained:
                self.db.execute("INSERT OR IGNORE INTO learning_exclusions VALUES (?,?,?)", (
                    run_id, now(), "Conversation deleted; retained only as historical evidence"))
            for run_id in run_ids - retained:
                self.db.execute("DELETE FROM events WHERE run_id=?", (run_id,))
                self.db.execute("DELETE FROM workers WHERE run_id=?", (run_id,))
                self.db.execute("DELETE FROM learning_exclusions WHERE run_id=?", (run_id,))
                self.db.execute("DELETE FROM runs WHERE id=?", (run_id,))
            return {"thread_id": thread_id, "deleted_turns": len(turns), "deleted_runs": len(run_ids - retained),
                    "retained_evidence_runs": len(retained)}

    def finish_action(self, action_id: str, status: str, result=None, error=None):
        with self._lock, self.db:
            self.db.execute("UPDATE actions SET status=?,result=?,error=? WHERE id=?", (status, canonical_json(result), error, action_id))

    def link_chat_run(self, turn_id: str, run_id: str):
        with self._lock, self.db:
            self.db.execute("UPDATE chat_turns SET run_id=? WHERE id=? AND status='running'", (run_id, turn_id))

    def finish_chat_turn(self, turn_id: str, status: str, error=None):
        with self._lock, self.db:
            self.db.execute("UPDATE chat_turns SET status=?,error=? WHERE id=?", (status, error, turn_id))

    def chat_turns(self, thread_id: str | None = None) -> list[dict]:
        return [self._decode(dict(row), ("usage",)) for row in self.db.execute(
            "SELECT c.*,r.version_id,r.output,r.usage FROM chat_turns c LEFT JOIN runs r ON c.run_id=r.id "
            "WHERE (? IS NULL OR c.thread_id=?) ORDER BY c.created_at", (thread_id, thread_id))]

    def start_audit(self, suite_id: str, plan: dict) -> str:
        """Consume a held-out suite once, even if interrupted. Never a promotion gate."""
        audit_id = uuid4().hex
        try:
            with self._lock, self.db:
                self.db.execute("INSERT INTO audits VALUES (?,?,?,?,?,?)", (
                    audit_id, now(), suite_id, "running", canonical_json(plan),
                    canonical_json({"pairs": [], "run_ids": [], "reason": "Frozen comparison in progress"})))
        except sqlite3.IntegrityError:
            raise ValueError("Held-out suite already consumed; inspect its saved audit instead of retesting") from None
        return audit_id

    def audit(self, audit_id: str) -> dict:
        row = self.db.execute("SELECT * FROM audits WHERE id=?", (audit_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown audit")
        return self._decode(dict(row), ("plan", "report"))

    def update_audit(self, audit_id: str, status: str, report: dict):
        with self._lock, self.db:
            cursor = self.db.execute("UPDATE audits SET status=?,report=? WHERE id=? AND status='running'",
                                     (status, canonical_json(report), audit_id))
            if cursor.rowcount != 1:
                raise ValueError("Audit is already finalized")

    def start_reflection(self, evidence_ids: list[str], memory_ids: list[str]) -> dict:
        active = self.active()
        reflection = {"id": uuid4().hex, "base_version": active["version_id"], "base_generation": active["generation"]}
        with self._lock, self.db:
            self.db.execute("INSERT INTO reflections VALUES (?,?,?,?,?,?,?,?,?,?)", (
                reflection["id"], now(), reflection["base_version"], reflection["base_generation"], "running",
                canonical_json(evidence_ids), canonical_json(memory_ids), None, None, None))
        return reflection

    def finish_reflection(self, reflection_id, status, usage, response=None, error=None):
        with self._lock, self.db:
            self.db.execute("UPDATE reflections SET status=?,usage=?,response=?,error=? WHERE id=?",
                            (status, canonical_json(usage), canonical_json(response), error, reflection_id))

    def save_proposal(self, reflection: dict, manifest: dict, document: dict) -> str:
        candidate_id = self.save_version(manifest)
        proposal_id = uuid4().hex
        with self._lock, self.db:
            self.db.execute("INSERT INTO proposals VALUES (?,?,?,?,?,?,?,?,?,?)", (
                proposal_id, now(), reflection["id"], reflection["base_version"], reflection["base_generation"],
                candidate_id, canonical_json(document), "pending", None, None))
        return proposal_id

    def proposal(self, proposal_id: str) -> dict:
        row = self.db.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown proposal")
        return self._decode(dict(row), ("document", "evaluation"))

    def set_evaluation(self, proposal_id: str, status: str, evaluation: dict):
        with self._lock, self.db:
            self.db.execute("UPDATE proposals SET status=?,reason=?,evaluation=? WHERE id=?",
                            (status, evaluation["reason"], canonical_json(evaluation), proposal_id))

    def remember(self, reflection_id, proposal_id, outcome, lesson, evidence):
        with self._lock, self.db:
            self.db.execute("INSERT INTO reflection_memory VALUES (?,?,?,?,?,?,?)",
                            (uuid4().hex, now(), reflection_id, proposal_id, outcome, lesson, canonical_json(evidence)))

    def memories(self, limit: int = 5) -> list[dict]:
        return [self._decode(dict(row), ("evidence",)) for row in self.db.execute(
            "SELECT * FROM reflection_memory ORDER BY created_at DESC LIMIT ?", (limit,))]

    def activate(self, proposal_id: str) -> dict:
        """CAS on both digest and generation; only an evaluated candidate is eligible."""
        with self._lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            proposal = self.proposal(proposal_id)
            evaluation = proposal["evaluation"] or {}
            if proposal["status"] != "qualified" or evaluation.get("decision") != "retain":
                raise ValueError("Candidate has not passed its evaluation gate")
            if evaluation.get("candidate_version") != proposal["candidate_version"] or evaluation.get("base_version") != proposal["base_version"]:
                raise ValueError("Evaluation does not match the candidate digests")
            cursor = self.db.execute("UPDATE organization SET active_version=?,generation=generation+1 WHERE singleton=1 AND active_version=? AND generation=?",
                                     (proposal["candidate_version"], proposal["base_version"], proposal["base_generation"]))
            if cursor.rowcount != 1:
                raise ValueError("Stale proposal: active version or generation changed")
            generation = proposal["base_generation"] + 1
            self.db.execute("INSERT INTO activations VALUES (?,?,?,?,?,?,?)", (
                uuid4().hex, now(), proposal["base_version"], proposal["candidate_version"], generation, proposal_id, evaluation["reason"]))
            self.db.execute("UPDATE proposals SET status='retained' WHERE id=?", (proposal_id,))
        return self.active()

    def revoke_activation(self, proposal_id: str, reason: str) -> dict:
        """Explicit controller correction; preserve the original experiment and activation."""
        with self._lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            proposal = self.proposal(proposal_id)
            active = self.active()
            if proposal["status"] != "retained" or active["version_id"] != proposal["candidate_version"]:
                raise ValueError("Only the currently retained proposal can be revoked")
            generation = active["generation"] + 1
            self.db.execute("UPDATE organization SET active_version=?,generation=? WHERE singleton=1 AND active_version=? AND generation=?",
                            (proposal["base_version"], generation, active["version_id"], active["generation"]))
            self.db.execute("INSERT INTO activations VALUES (?,?,?,?,?,?,?)", (
                uuid4().hex, now(), active["version_id"], proposal["base_version"], generation, proposal_id, reason))
            self.db.execute("UPDATE proposals SET status='revoked',reason=? WHERE id=?", (reason, proposal_id))
        self.remember(proposal["reflection_id"], proposal_id, "revoked", reason,
                      {"base_version": proposal["base_version"], "candidate_version": proposal["candidate_version"], "generation": generation})
        return self.active()
