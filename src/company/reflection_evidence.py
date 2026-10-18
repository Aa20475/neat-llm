"""Full saved event traces and supplementary excerpts from opted-in runs."""

import json
from pathlib import PurePosixPath
import re


def event_evidence(replay):
    """Preserve every saved event and worker; enrich attribution without editing payloads."""
    workers = []
    for worker in replay["workers"]:
        if worker["parent_id"]:
            label = f"Worker {worker['id'].rsplit(':', 1)[-1]} · {worker['role']}"
        else:
            label = "Generalist" if worker["role"] == "generalist" else worker["role"]
        workers.append({**worker, "label": label})
    by_id = {worker["id"]: worker for worker in workers}
    events = []
    for event in replay["events"]:
        worker = by_id.get(event["worker_id"], {})
        fallback = "Controller" if event["worker_id"] is None else f"Unknown worker ({event['worker_id']})"
        events.append({**event, "worker_label": worker.get("label", fallback),
                       "worker_role": worker.get("role"), "parent_worker_id": worker.get("parent_id"),
                       "worker_temporary": worker.get("temporary")})
    return {"workers": workers, "event_trace": events,
            "trace_coverage": {"source": "all persisted events in sequence order",
                               "events_available": len(events), "events_included": len(events), "events_omitted": 0,
                               "workers_included": len(workers), "reflection_payload_truncated": False,
                               "note": "Reflection adds no payload truncation. The runtime may have clipped strings "
                                       "at capture time (12,000 characters) and tools may limit their own output. "
                                       "Previously unrecorded text cannot be recovered."}}


def excerpt(text, limit):
    text = str(text or "")
    if len(text) <= limit:
        return text
    marker = "\n... [excerpt omitted] ...\n"
    half = (limit - len(marker)) // 2
    return text[:half] + marker + text[-(limit - len(marker) - half):]


def tool_result(event):
    result = event["payload"].get("output")
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except ValueError:
            return None
    return result if isinstance(result, dict) else None


def solution_evidence(replay):
    project = replay.get("project") or {}
    files, initial = project.get("final_files", {}), project.get("initial_files", {})
    changed = {path for path in files if files[path] != initial.get(path)}
    def is_test(path):
        name = PurePosixPath(path).name
        return name.startswith("test_") or name.endswith("_test.py") or "tests" in PurePosixPath(path).parts
    sources = [path for path in files if path.endswith(".py") and not is_test(path)
               and not PurePosixPath(path).name.startswith("_") and PurePosixPath(path).name != "demo.py"]
    sources.sort(key=lambda path: (path not in changed, path))
    tests = sorted((path for path in files if path.endswith(".py") and is_test(path)),
                   key=lambda path: (path not in changed, "review" not in path and "adversarial" not in path, path))
    artifacts = []
    for path in sources[:2] + tests[:1]:
        content = files[path]
        limit = 1200 if is_test(path) else 1600
        artifacts.append({"path": path, "kind": "test" if is_test(path) else "implementation",
                          "changed_in_run": path in changed, "characters": len(content),
                          "excerpt": excerpt(content, limit), "excerpt_truncated": len(content) > limit})
    # Names describe intended coverage, not proof that tests ran or are correct.
    coverage = [{"path": path, "test_names": re.findall(r"^\s*(?:async\s+)?def\s+(test_\w+)\s*\(", files[path], re.M)[:20]}
                for path in tests[:4]]
    events = replay["events"]
    starts = {event["payload"].get("call_id"): event for event in events if event["kind"] == "tool_started"}
    failures, edits, reviews = [], [], []
    root = replay["run"]["id"] + ":root"
    for event in events:
        payload = event["payload"]
        if event["kind"] == "tool_finished":
            result = tool_result(event)
            start = starts.get(payload.get("call_id"), {})
            arguments = start.get("payload", {}).get("arguments") or {}
            if result and (result.get("status") in ("error", "timed_out", "unavailable") or result.get("reported_error")):
                detail = result.get("stderr") or result.get("error") or result.get("reported_error") or result.get("stdout")
                failures.append({"event_seq": event["seq"], "worker_id": event["worker_id"], "tool": payload.get("name"),
                                 "path": arguments.get("file_path") or arguments.get("path"),
                                 "status": result.get("status"), "exit_code": result.get("exit_code"), "excerpt": excerpt(detail, 650)})
            if payload.get("name") == "project_edit" and result and result.get("status") == "ok":
                edits.append({"event_seq": event["seq"], "worker_id": event["worker_id"], "path": arguments.get("path"),
                              "before": excerpt(arguments.get("old_text"), 300), "after": excerpt(arguments.get("new_text"), 300)})
        elif event["kind"] == "model_finished" and event["worker_id"] and event["worker_id"] != root and not payload.get("tool_calls") and payload.get("output"):
            reviews.append({"event_seq": event["seq"], "worker_id": event["worker_id"],
                            "source": "worker report; not an independent controller check", "excerpt": excerpt(payload["output"], 1200)})
    # Keep early failures even when final tests pass, plus a later failure.
    selected_failures = failures if len(failures) <= 3 else [*failures[:2], failures[-1]]
    selected_edits = edits if len(edits) <= 3 else [*edits[:2], edits[-1]]
    return {"project_artifacts": artifacts, "test_inventory": coverage,
            "development_failures": selected_failures, "repair_edits": selected_edits, "worker_reports": reviews[-1:],
            "evidence_limits": {"files_available": len(files), "files_excerpted": len(artifacts),
                                "failed_tool_calls": len(failures), "failures_included": len(selected_failures),
                                "successful_edits": len(edits), "edits_included": len(selected_edits),
                                "note": "Excerpts and test names are partial evidence. Edits are chronological observations, not proof of a fix."}}
