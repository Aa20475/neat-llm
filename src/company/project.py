"""Persistent project tools and isolated worker branches; never host filesystem access."""

import asyncio
from copy import deepcopy
import difflib
import hashlib
import json
from uuid import uuid4

from langchain_core.tools import tool

from company.project_runner import project_path, run_project, validate_files


PROJECT_TOOLS = ("project_list", "project_read", "project_search", "project_write", "project_edit",
                 "project_delete", "project_diff", "project_merge")


def file_digest(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def project_prefix(prefix):
    if prefix in ("", ".", "./", "/work", "/work/"):
        return ""
    return project_path(prefix.rstrip("/"))


class Project:
    def __init__(self, files=None, save=None, *, parent=None, branch_id=None):
        self.files = validate_files(files or {})
        self.base = deepcopy(self.files)
        self.save = save or (lambda files, branches: None)
        self.parent, self.branch_id = parent, branch_id
        self.branches = {}
        self.status = "working"
        self.lock = asyncio.Lock()

    def persist(self):
        if self.parent:
            self.parent.persist()
        else:
            self.save(self.files, {key: {"base": child.base, "files": child.files, "status": child.status}
                                   for key, child in self.branches.items()})

    def replace(self, files):
        self.files = validate_files(files)
        self.persist()

    def fork(self):
        key = "worker-" + uuid4().hex[:12]
        child = Project(self.files, parent=self, branch_id=key)
        self.branches[key] = child
        self.persist()
        return child

    def changed(self):
        return sorted(path for path in self.base.keys() | self.files.keys() if self.base.get(path) != self.files.get(path))

    def branch(self, worker_id):
        if self.parent or worker_id not in self.branches:
            raise ValueError("Unknown worker branch; use the workspace ID returned by task")
        branch = self.branches[worker_id]
        if branch.status != "completed":
            raise ValueError("Worker branch has not completed")
        return branch


def project_tools(project: Project):
    async def perform(action):
        async with project.lock:
            try:
                result = action()
                if asyncio.iscoroutine(result):
                    result = await result
                return {"status": "ok", **result, "workspace_digest": file_digest(project.files)}
            except (ValueError, OSError) as error:
                return {"status": "error", "error": str(error), "workspace_digest": file_digest(project.files)}

    @tool
    async def project_list(prefix: str = "") -> dict:
        """List persistent project files under /work, with sizes. Optional relative directory prefix."""
        def action():
            clean = project_prefix(prefix)
            return {"files": [{"path": name, "bytes": len(content.encode())} for name, content in sorted(project.files.items())
                              if not clean or name == clean or name.startswith(clean + "/")],
                    "note": "Use project_write to create files; parent directories are created automatically."}
        return await perform(action)

    @tool
    async def project_read(path: str, start_line: int = 1, max_lines: int = 200) -> dict:
        """Read a saved project file with line numbers. Use project_list to find paths."""
        def action():
            name = project_path(path)
            if name not in project.files:
                if any(key.startswith(name + "/") for key in project.files):
                    raise ValueError("This is a directory; use project_list with this prefix")
                raise ValueError("File not found. Use project_write to create it; parent directories are created automatically.")
            if start_line < 1 or not 1 <= max_lines <= 400:
                raise ValueError("Use a positive start line and 1–400 lines")
            lines = project.files[name].splitlines()
            text = "\n".join(f"{i + 1}: {lines[i]}" for i in range(start_line - 1, min(len(lines), start_line - 1 + max_lines)))
            return {"path": name, "text": text[:24000], "total_lines": len(lines), "truncated": len(text) > 24000}
        return await perform(action)

    @tool
    async def project_search(query: str, prefix: str = "") -> dict:
        """Find literal text in project files; returns up to 50 matching lines."""
        def action():
            if not query or len(query) > 500:
                raise ValueError("Use a nonempty search string of at most 500 characters")
            clean = project_prefix(prefix)
            matches = []
            for name, content in sorted(project.files.items()):
                if clean and name != clean and not name.startswith(clean + "/"):
                    continue
                for i, line in enumerate(content.splitlines(), 1):
                    if query in line:
                        matches.append({"path": name, "line": i, "text": line[:400]})
                        if len(matches) == 50:
                            return {"matches": matches, "truncated": True}
            return {"matches": matches, "truncated": False}
        return await perform(action)

    @tool
    async def project_write(path: str, content: str) -> dict:
        """Create or replace a UTF-8 file, creating parent directories automatically. Files persist across calls and turns."""
        def action():
            name = project_path(path)
            project.replace({**project.files, name: content})
            return {"path": name, "bytes": len(content.encode())}
        return await perform(action)

    @tool
    async def project_edit(path: str, old_text: str, new_text: str) -> dict:
        """Replace exactly one occurrence of old_text in a saved file. Read before editing."""
        def action():
            name = project_path(path)
            if old_text == new_text:
                raise ValueError("The edit changes nothing: old_text and new_text are identical. Inspect the failure and change the relevant code.")
            if name not in project.files or not old_text or project.files[name].count(old_text) != 1:
                raise ValueError("old_text must match exactly once in an existing file; read the current file first")
            project.replace({**project.files, name: project.files[name].replace(old_text, new_text, 1)})
            return {"path": name}
        return await perform(action)

    @tool
    async def project_delete(path: str) -> dict:
        """Delete one file from this task's project workspace."""
        def action():
            name = project_path(path)
            if name not in project.files:
                raise ValueError("File not found")
            project.replace({key: value for key, value in project.files.items() if key != name})
            return {"deleted": name}
        return await perform(action)

    @tool
    async def python_execute(file_path: str | None = None, script_args: list[str] | None = None,
                             code: str | None = None, files: dict[str, str] | None = None) -> dict:
        """Run a saved Python file in /work, with optional script arguments.

        First save reusable code and tests with project_write; then pass file_path,
        e.g. tests/test_scheduler.py. Project files and generated text files persist.
        Each call starts a fresh Python process: import saved modules; variables do
        not carry across calls. For a quick snippet, code is saved to _scratch.py.
        Optional files adds/replaces project files before execution. Stdlib only,
        no network or host files. Returns exit code, bounded stdout/stderr and changed paths.
        Exit code zero is not proof of task success; reported_error flags explicit
        error markers in output (a heuristic). Use assertions and nonzero exits for failures.
        """
        async def action():
            if (file_path is None) == (code is None):
                raise ValueError("Supply either file_path for a saved script or code for a scratch script")
            updated = dict(project.files)
            if files is not None:
                updated.update(validate_files(files))
            path = file_path
            if code is not None:
                if not code.strip() or len(code.encode()) > 32000:
                    raise ValueError("Scratch code must contain 1–32,000 bytes")
                path = "_scratch.py"
                updated[path] = code
            project.replace(updated)
            before = dict(project.files)
            result = await run_project(before, path, script_args)
            after = result.pop("files", None)
            if after is not None:
                project.replace(after)
            result["changed_files"] = sorted(name for name in before.keys() | project.files.keys()
                                             if before.get(name) != project.files.get(name))
            return result
        return await perform(action)

    @tool
    async def project_diff(worker_id: str) -> dict:
        """Review a completed subagent's project changes using its returned workspace ID."""
        def action():
            branch = project.branch(worker_id)
            paths = branch.changed()
            diff = "".join(line for name in paths for line in difflib.unified_diff(
                branch.base.get(name, "").splitlines(keepends=True), branch.files.get(name, "").splitlines(keepends=True),
                fromfile="before/" + name, tofile="after/" + name))
            return {"worker_id": worker_id, "changed_files": paths, "diff": diff[:24000], "truncated": len(diff) > 24000}
        return await perform(action)

    @tool
    async def project_merge(worker_id: str, paths: list[str]) -> dict:
        """Accept selected files from a completed worker after project_diff. Conflicts require manual editing."""
        def action():
            branch = project.branch(worker_id)
            selected = [project_path(path) for path in paths]
            if not selected or len(set(selected)) != len(selected) or set(selected) - set(branch.changed()):
                raise ValueError("Select distinct changed file paths from project_diff")
            conflicts = [name for name in selected if project.files.get(name) not in (branch.base.get(name), branch.files.get(name))]
            if conflicts:
                raise ValueError("Parent changed these files since delegation; merge manually: " + ", ".join(conflicts))
            updated = dict(project.files)
            for name in selected:
                if name in branch.files:
                    updated[name] = branch.files[name]
                else:
                    updated.pop(name, None)
            project.replace(updated)
            return {"merged": selected}
        return await perform(action)

    return {item.name: item for item in (project_list, project_read, project_search, project_write, project_edit,
                                        project_delete, python_execute, project_diff, project_merge)}
