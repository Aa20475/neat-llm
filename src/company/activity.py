"""Small, readable activity summaries for running chat turns."""

import json


TOOL_LABELS = {
    "python_execute": "Python execution", "project_list": "Listing project files",
    "project_read": "Reading a project file", "project_search": "Searching project files",
    "project_write": "Writing a project file", "project_edit": "Editing a project file",
    "project_delete": "Deleting a project file", "project_diff": "Reviewing worker changes",
    "project_merge": "Merging worker changes", "read_file": "Reading a file",
    "task": "Delegating to a worker", "write_todos": "Updating the task plan",
    "decimal_product": "Calculating a product", "decimal_sum": "Calculating a sum",
}


def summarize_event(row):
    payload = json.loads(row["payload"])
    kind, name = row["kind"], payload.get("name", "")
    summary, detail, tone = kind.replace("_", " ").capitalize(), "", "normal"
    if kind in ("run_started", "runtime_config"):
        summary = "Starting the team"
    elif kind == "model_started":
        summary = "Waiting for model response"
        detail = f"Model call {payload['call_number']}" if payload.get("call_number") else ""
    elif kind == "model_finished":
        calls = payload.get("tool_calls") or []
        summary = "Model requested tools" if calls else "Model response received"
        detail = ", ".join(str(call.get("name", "tool")) for call in calls[:3])
    elif kind == "tool_started":
        summary = "Running Python" if name == "python_execute" else TOOL_LABELS.get(name, "Calling a tool")
        args = payload.get("arguments") or {}
        detail = args.get("path") or args.get("file_path") or args.get("subagent_type") or name
    elif kind == "tool_finished":
        summary = "Tool finished"
        detail = name
        result = payload.get("output")
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (ValueError, TypeError):
                result = None
        if isinstance(result, dict):
            failed = result.get("reported_error") or result.get("status") in ("error", "timed_out", "unavailable")
            if failed:
                summary, tone = "Tool reported an error", "error"
            elif name == "python_execute":
                summary = "Python process exited"
                detail = "Results have not been independently verified"
            if result.get("exit_code") is not None:
                detail += f" · exit {result['exit_code']}"
    elif kind == "worker_started":
        summary = "Worker started"
    elif kind == "worker_finished":
        summary = "Worker finished" if payload.get("status") == "completed" else "Worker stopped"
        detail = payload.get("status", "")
    elif kind in ("model_error", "tool_error", "run_error"):
        summary, tone = {"model_error": "Model request failed", "tool_error": "Tool failed", "run_error": "Run failed"}[kind], "error"
        detail = payload.get("error_type", "")
    elif kind in ("response_incomplete", "run_incomplete", "no_progress", "budget_exceeded"):
        summary, tone = "Task could not finish", "error"
    elif kind == "execution_retry":
        summary = "Retrying to obtain an actual execution result"
    elif kind == "run_interrupted":
        summary = "Stopping the task"
    elif kind == "run_finished":
        summary = "Finalizing the response"
        detail = payload.get("status", "")
    role = row["role"] or "Controller"
    if row["parent_id"]:
        worker = f"Worker {row['worker_id'].rsplit(':', 1)[-1]} · {role}"
    else:
        worker = "Generalist" if role == "generalist" else role
    return {"seq": row["seq"], "timestamp": row["timestamp"], "kind": kind,
            "worker": worker[:120], "summary": summary, "detail": str(detail)[:180], "tone": tone}


def recent_activity(store, run_id):
    # The (run_id, seq) primary key makes this a bounded lookup, not a replay
    # of the full event history or project files on every chat refresh.
    rows = store.db.execute(
        "SELECT e.*,w.role,w.parent_id FROM events e LEFT JOIN workers w ON w.id=e.worker_id "
        "WHERE e.run_id=? ORDER BY e.seq DESC LIMIT 3", (run_id,)
    ).fetchall()
    return [summarize_event(row) for row in rows]
