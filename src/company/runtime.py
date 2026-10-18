"""Compile the saved v0 layout into Deep Agents and persist actual execution."""

import asyncio
from dataclasses import replace
import hashlib
import json
import re
import sys
import threading
import time

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain.agents import create_agent
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_core.runnables import RunnableLambda

from company.agent_tools import TOOLS
from company.config import Settings
from company.organization import role_prompt, validate_manifest, worker_files
from company.project import PROJECT_TOOLS, Project, project_tools
from company.responses import IncompleteResponse, require_complete_response
from company.store import Store
from company.workload import grade_output


EXECUTION_PROTOCOL = (
    "When asked to implement and execute code, actually call python_execute and inspect its result before answering. "
    "Use native tool calls; JSON or code blocks in an ordinary answer do not call a tool. "
    "Do not stop at a plan or a promise to begin. Your /work project files persist across calls and follow-up turns. "
    "Inspect with project_list, project_read and project_search. Save reusable code with project_write, "
    "make targeted changes with project_edit, then run saved test files using python_execute(file_path=...). "
    "Python processes and variables are fresh each call: import saved modules instead of assuming prior variables exist. "
    "Prefer implementation and test files over repeatedly rewriting a scratch script. Inspect actual failure output before editing. "
    "Subagents receive copies of your current project. Review their returned workspace ID with project_diff and "
    "accept selected files with project_merge; their changes are not applied automatically. "
    "An exit code of zero only means the process exited normally: inspect output and reported_error before claiming success. "
    "Do not repeat an identical execution or an edit that changes nothing; inspect the relevant code and correct the cause. "
    "Your final answer must distinguish observed execution results from untested claims."
)


def requests_python_execution(prompt: str) -> bool:
    """Narrow check for explicit execution requests, not a general correctness judge."""
    # Shared follow-ups save their context in the prompt for paired replay.
    # Apply the same execution check when replaying as on the original turn.
    if prompt.startswith("Answer the current request in this previously shared conversation."):
        try:
            request = json.loads(prompt.split("\n", 1)[1])["current_request"]
            if isinstance(request, str):
                prompt = request
        except (ValueError, KeyError, IndexError, TypeError):
            pass
    if re.match(r"\s*(explain|describe|how|what)\b", prompt, re.I):
        return False
    return bool(re.search(
        r"\b(?:implement|write|build|create)\s+and\s+(?:execute|run)\b|"
        r"\b(?:execute|run)\s+(?:(?:the|this|some)\s+)?(?:python|code|script|tests)\b", prompt, re.I))


class BudgetExceeded(RuntimeError):
    pass


class NoProgress(RuntimeError):
    pass


class RunTrace(BaseCallbackHandler):
    """One shared budget for the root and every child, including parallel calls."""

    raise_error = True
    run_inline = True

    def __init__(self, store: Store, run: dict, secret: str = "", budget=None, phase="execution"):
        self.store, self.run_id, self.limits = store, run["id"], run["manifest"]["limits"]
        self.root = self.run_id + ":root"
        self.secret = secret
        self.budget, self.phase = budget, phase
        self.saved_roles = {role["id"] for role in run["manifest"]["topology"]["roles"]}
        self.saved_workers = 0
        self.parents: dict[str, str | None] = {}
        self.task_workers: dict[str, str] = {}
        self.depths = {self.root: 0}
        self.tool_names: dict[str, str] = {}
        self.tool_owners: dict[str, str] = {}
        self.tool_arguments = {}
        self.failures = {}
        self.executions = {}
        self.stall_reason = None
        self.response_error = None
        self.incomplete_workers = set()
        self.max_tokens = run["manifest"]["inference"]["max_tokens"]
        self.calls = self.completed = self.tool_calls = self.worker_count = 0
        self.input_tokens = self.output_tokens = self.usage_missing = 0
        self.child_tool_calls = 0
        self.child_tools: set[str] = set()
        self.python_successes = 0
        self.violation: str | None = None
        self._lock = threading.RLock()

    def clean(self, value, limit=12000):
        if isinstance(value, dict):
            return {str(key): self.clean(item, limit) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.clean(item, limit) for item in value]
        if value is None or type(value) in (int, float, bool):
            return value
        text = str(value)
        if self.secret:
            text = text.replace(self.secret, "[REDACTED]")
        return text[:limit] if limit is not None else text

    def link(self, run_id, parent_run_id):
        self.parents[str(run_id)] = str(parent_run_id) if parent_run_id else None

    def owner(self, run_id):
        cursor = str(run_id)
        while cursor:
            if cursor in self.task_workers:
                return self.task_workers[cursor]
            cursor = self.parents.get(cursor)
        return self.root

    def record(self, kind, worker_id, **payload):
        self.store.event(self.run_id, kind, worker_id, self.clean(payload))

    def deny(self, reason):
        self.violation = reason
        self.record("budget_exceeded", self.root, reason=reason)
        raise BudgetExceeded(reason)

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
        with self._lock:
            self.link(run_id, parent_run_id)

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
        with self._lock:
            self.link(run_id, parent_run_id)
            if self.violation:
                raise BudgetExceeded(self.violation)
            if self.stall_reason:
                raise NoProgress(self.stall_reason)
            if self.response_error:
                raise IncompleteResponse(self.response_error)
            if self.limits["model_calls"] is not None and self.calls >= self.limits["model_calls"]:
                self.deny("model_calls")
            if self.budget:
                self.budget.reserve()
            self.calls += 1
            self.record("model_started", self.owner(run_id), call_id=str(run_id), call_number=self.calls)

    def on_llm_end(self, response, *, run_id, **kwargs):
        with self._lock:
            self.completed += 1
            for batch in response.generations:
                for generation in batch:
                    message = getattr(generation, "message", None)
                    usage = getattr(message, "usage_metadata", None)
                    if usage is None:
                        self.usage_missing += 1
                    usage = usage or {}
                    self.input_tokens += usage.get("input_tokens", 0)
                    self.output_tokens += usage.get("output_tokens", 0)
                    finish_reason = (generation.generation_info or {}).get("finish_reason") or getattr(message, "response_metadata", {}).get("finish_reason")
                    text = getattr(message, "text", "")
                    self.record("model_finished", self.owner(run_id), call_id=str(run_id), usage=usage,
                                finish_reason=finish_reason, output=text, output_chars=len(text),
                                trace_output_truncated=len(text) > 12000, tool_calls=getattr(message, "tool_calls", []))
                    if message is not None:
                        try:
                            require_complete_response(message, max_tokens=self.max_tokens, finish_reason=finish_reason)
                        except IncompleteResponse as exc:
                            self.response_error = str(exc)
                            self.incomplete_workers.add(self.owner(run_id))
                            self.record("response_incomplete", self.owner(run_id), reason=str(exc), finish_reason=finish_reason)
                            raise

    def on_llm_error(self, error, *, run_id, **kwargs):
        with self._lock:
            self.record("model_error", self.owner(run_id), call_id=str(run_id), error_type=type(error).__name__)

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, inputs=None, **kwargs):
        with self._lock:
            self.link(run_id, parent_run_id)
            if self.violation:
                raise BudgetExceeded(self.violation)
            if self.stall_reason:
                raise NoProgress(self.stall_reason)
            if self.response_error:
                raise IncompleteResponse(self.response_error)
            if self.limits["tool_calls"] is not None and self.tool_calls >= self.limits["tool_calls"]:
                self.deny("tool_calls")
            name = serialized.get("name", "unknown")
            # Explicit allowlist also applies to framework-injected tools.
            if name not in (*TOOLS, *PROJECT_TOOLS, "task", "write_todos", "read_file"):
                self.deny("unapproved_tool")
            owner = self.owner(parent_run_id)
            self.tool_names[str(run_id)] = name
            self.tool_owners[str(run_id)] = owner
            arguments = inputs if isinstance(inputs, dict) else {"input": input_str}
            self.tool_arguments[str(run_id)] = arguments
            if name == "task":
                if self.limits["workers"] is not None and self.worker_count >= self.limits["workers"]:
                    self.deny("workers")
                if self.depths[owner] >= self.limits["worker_depth"]:
                    self.deny("worker_depth")
                role = arguments.get("subagent_type")
                if role not in {"general-purpose"} | (self.saved_roles - {"generalist"}):
                    self.deny("unapproved_worker_type")
                temporary = role == "general-purpose"
                self.worker_count += 1
                child = self.run_id + ":worker:" + str(self.worker_count)
                self.depths[child] = self.depths[owner] + 1
                self.task_workers[str(run_id)] = child
                if not temporary:
                    self.saved_workers += 1
                self.store.worker_start(self.run_id, child, owner, role, temporary, self.clean(arguments.get("description", "")))
                self.record("worker_started", child, parent_id=owner, role=role, temporary=temporary,
                            description=arguments.get("description", ""))
            elif owner != self.root:
                self.child_tool_calls += 1
                self.child_tools.add(name)
            self.tool_calls += 1
            self.record("tool_started", owner, call_id=str(run_id), name=name, arguments=arguments)

    def on_tool_end(self, output, *, run_id, **kwargs):
        with self._lock:
            value = getattr(output, "content", output)
            try:
                value = json.loads(value) if isinstance(value, str) else value
            except (ValueError, TypeError):
                value = None
            name = self.tool_names.get(str(run_id))
            if name in (*PROJECT_TOOLS, "python_execute") and isinstance(value, dict) and value.get("status") in ("error", "timed_out"):
                fingerprint = hashlib.sha256(json.dumps({"name": name, "arguments": self.tool_arguments.get(str(run_id)),
                    "workspace": value.get("workspace_digest"), "error": value.get("error") or value.get("stderr") or value.get("persistence_error"),
                    "reported_error": value.get("reported_error")}, sort_keys=True).encode()).hexdigest()
                key = (self.tool_owners.get(str(run_id)), fingerprint)
                self.failures[key] = self.failures.get(key, 0) + 1
                if self.failures[key] >= 3:
                    self.stall_reason = "Stopped after the same tool failed three times on unchanged project files. Inspect the saved files and error before continuing."
                    self.record("no_progress", self.tool_owners.get(str(run_id), self.root), reason=self.stall_reason, tool=name)
            if self.tool_names.get(str(run_id)) == "python_execute":
                if isinstance(value, dict) and value.get("status") == "ok":
                    self.python_successes += 1
                    if value.get("workspace_digest"):
                        fingerprint = hashlib.sha256(json.dumps({"arguments": self.tool_arguments.get(str(run_id)),
                            "workspace": value["workspace_digest"], "stdout": value.get("stdout"),
                            "stderr": value.get("stderr"), "exit_code": value.get("exit_code")}, sort_keys=True).encode()).hexdigest()
                        key = (self.tool_owners.get(str(run_id)), fingerprint)
                        self.executions[key] = self.executions.get(key, 0) + 1
                        if self.executions[key] >= 5:
                            self.stall_reason = "Stopped after five identical Python executions on unchanged project files with identical output. Inspect the saved files before continuing."
                            self.record("no_progress", self.tool_owners.get(str(run_id), self.root), reason=self.stall_reason, tool=name)
            self.record("tool_finished", self.tool_owners.get(str(run_id), self.root), call_id=str(run_id), name=self.tool_names.get(str(run_id)), output=getattr(output, "content", output))
            if child := self.task_workers.get(str(run_id)):
                status = "incomplete" if child in self.incomplete_workers else "completed"
                self.store.worker_finish(child, status)
                self.record("worker_finished", child, status=status)

    def on_tool_error(self, error, *, run_id, **kwargs):
        with self._lock:
            self.record("tool_error", self.tool_owners.get(str(run_id), self.root), call_id=str(run_id), error_type=type(error).__name__)
            if child := self.task_workers.get(str(run_id)):
                status = "incomplete" if child in self.incomplete_workers or isinstance(error, IncompleteResponse) else "failed"
                self.store.worker_finish(child, status)
                self.record("worker_finished", child, status=status)

    def usage(self):
        return {"phase": self.phase, "model_calls": self.calls, "completed_calls": self.completed,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "tool_calls": self.tool_calls, "temporary_workers": self.worker_count - self.saved_workers, "saved_role_workers": self.saved_workers,
                "complete": self.completed == self.calls and self.usage_missing == 0}


def build_agent(manifest: dict, settings: Settings, project: Project | None = None):
    validate_manifest(manifest)
    inference = manifest["inference"]
    # Do not send the user's credential to a different endpoint stored in a proposal.
    if inference["base_url"] != settings.base_url:
        raise ValueError("Saved provider endpoint differs from configured endpoint")
    pinned = replace(settings, model=inference["model"], max_tokens=inference["max_tokens"], timeout=inference["timeout"],
                     enable_thinking=inference["enable_thinking"], reasoning_effort=inference.get("reasoning_effort"))
    # Shared by parent and children. Pace requests without hidden retry calls.
    model = pinned.chat_model()
    model.rate_limiter = InMemoryRateLimiter(requests_per_second=0.5, check_every_n_seconds=0.1, max_bucket_size=1)
    project = project or Project()
    root_role = manifest["topology"]["roles"][0]
    def bound_tools(role, workspace):
        registry = {**TOOLS, **project_tools(workspace)}
        return [registry[name] for name in role.get("tools", manifest["tools"]["names"])]
    tools = bound_tools(root_role, project)
    backend = StateBackend()
    prompt = role_prompt(manifest) + "\n\n" + EXECUTION_PROTOCOL + "\nYour saved configuration is available under /organization/; read /organization/README.md for the file index if needed."
    def compile_worker(role, name, description):
        async def invoke(state, config):
            branch = project.fork()
            child = create_agent(model=model, tools=bound_tools(role, branch),
                                 system_prompt=role_prompt(manifest, role["id"]) + "\n\n" + EXECUTION_PROTOCOL +
                                 "\nYou work in an isolated project copy. Edit your copy and report what changed; the parent reviews and merges.",
                                 middleware=[FilesystemMiddleware(backend=StateBackend(), tools=["read_file"])])
            try:
                result = await child.ainvoke({"messages": state["messages"], "files": worker_files(manifest, role["id"])}, config=config)
                require_complete_response(result["messages"][-1], max_tokens=pinned.max_tokens)
                branch.status = "completed"
                summary = result["messages"][-1].text
                return {"messages": [AIMessage(content=summary + "\n\nWorkspace ID: " + branch.branch_id +
                                               "\nChanged files: " + json.dumps(branch.changed()) +
                                               "\nReview with project_diff and accept files with project_merge.")]}
            except IncompleteResponse:
                branch.status = "incomplete"
                raise
            finally:
                if branch.status not in ("completed", "incomplete"):
                    branch.status = "interrupted"
                branch.persist()
        return {"name": name, "description": description, "runnable": RunnableLambda(invoke)}
    subagents = [compile_worker(root_role, "general-purpose", "A temporary worker with a copy of the project; include a bounded task and review its changes.")]
    subagents.extend(compile_worker(role, role["id"], role["description"]) for role in manifest["topology"]["roles"][1:])
    return create_deep_agent(
        model=model, tools=tools, system_prompt=prompt, backend=backend,
        middleware=[FilesystemMiddleware(backend=backend, tools=["read_file"])], subagents=subagents,
    )


async def execute(store: Store, settings: Settings, *, task_id: str, split: str, prompt: str, expected,
                  require_delegation: bool = False, version_id: str | None = None, budget=None, phase="execution",
                  ungraded: bool = False, conversation=None, chat_turn_id: str | None = None, initial_files: dict | None = None,
                  current_request: str | None = None) -> dict:
    """Caller owns the controller lock. The evaluator's expected value never enters the agent."""
    run = store.start_run(task_id, split, prompt, version_id=version_id)
    if chat_turn_id:
        store.link_chat_run(chat_turn_id, run["id"])
    trace = RunTrace(store, run, settings.api_key, budget=budget, phase=phase)
    start = time.monotonic()
    output, grade, error, status = None, None, None, "failed"
    try:
        files = store.start_project(run["id"], split, chat_turn_id, initial_files)
        project = Project(files, save=lambda current, branches: store.save_project(run["id"], current, branches))
        agent = build_agent(run["manifest"], settings, project)
        trace.record("runtime_config", trace.root, request_interval_seconds=2,
                     filesystem="project_snapshot_v1", readable_paths=sorted(worker_files(run["manifest"])),
                     project_paths=sorted(files))
        needs_execution = "python_execute" in run["manifest"]["tools"]["names"] and requests_python_execution(current_request if current_request is not None else prompt)
        async def work():
            inputs = {"messages": [*(conversation or []), HumanMessage(content=prompt)], "files": worker_files(run["manifest"])}
            # A protocol repair is distinct from a run-wide budget: if the model
            # repeatedly refuses execution, return an honest incomplete result.
            for attempt in range(3):
                result = await agent.ainvoke(inputs, config={"callbacks": [trace], "recursion_limit": sys.maxsize})
                if trace.response_error:
                    raise IncompleteResponse(trace.response_error)
                require_complete_response(result["messages"][-1], max_tokens=run["manifest"]["inference"]["max_tokens"])
                if not needs_execution or trace.python_successes or attempt == 2:
                    return result
                trace.record("execution_retry", trace.root, attempt=attempt + 1,
                             reason="Explicit execution requested, but no successful Python tool execution was observed")
                inputs = {**result, "messages": [*result["messages"], HumanMessage(content=(
                    "The task explicitly requests actual execution. No successful python_execute call was observed. "
                    "A printed tool-call JSON, plan, or code listing is not execution. "
                    "Save implementation and tests with project_write, then call python_execute(file_path=...) through "
                    "the native tool interface. Inspect output and report actual results. If you cannot execute, say so."
                ))]}
            raise AssertionError("Unreachable")
        result = await asyncio.wait_for(work(), timeout=run["manifest"]["limits"]["wall_seconds"])
        if trace.violation:
            raise BudgetExceeded(trace.violation)
        if trace.stall_reason:
            raise NoProgress(trace.stall_reason)
        output = result["messages"][-1].text.strip()
        grade = None if ungraded else grade_output(output, expected)
        if require_delegation and (trace.worker_count == 0 or "decimal_product" not in trace.child_tools):
            grade = {"passed": False, "reason": "delegation_not_observed"}
        status = "completed"  # Completion and independently checked correctness are separate.
        if needs_execution and not trace.python_successes:
            status = "incomplete"
            error = "Execution was requested, but no successful Python execution was observed"
            if not ungraded:
                grade = {"passed": False, "reason": "execution_not_observed"}
        if grade is not None:
            trace.record("evaluation_finished", trace.root, **grade)
    except BudgetExceeded as exc:
        status, error = "budget_exceeded", str(exc)
    except NoProgress as exc:
        status, error, output = "incomplete", str(exc), str(exc)
    except IncompleteResponse as exc:
        status, error, output = "incomplete", str(exc), str(exc)
        trace.record("run_incomplete", trace.root, reason=str(exc))
    except TimeoutError:
        status, error = "timed_out", "Run exceeded its wall-clock limit"
    except asyncio.CancelledError:
        status, error = "interrupted", "Controller was interrupted"
        trace.record("run_interrupted", trace.root, reason="Execution cancelled; saved files and trace preserved")
        raise
    except Exception as exc:
        status = "budget_exceeded" if trace.violation else "failed"
        error = trace.violation or type(exc).__name__  # Provider exception strings can contain credentials.
        if not trace.violation and getattr(exc, "status_code", None) == 401:
            error = "Crusoe rejected the API key (HTTP 401). Update CRUSOE_API_KEY in .env, restart the server, and try again."
        trace.record("run_error", trace.root, error_type=type(exc).__name__,
                     http_status=getattr(exc, "status_code", None), detail=str(exc),
                     retry_after=getattr(getattr(exc, "response", None), "headers", {}).get("retry-after"))
    finally:
        usage = trace.usage()
        usage["elapsed_seconds"] = round(time.monotonic() - start, 3)
        store.finish(run["id"], status, trace.clean(output, limit=None), grade, usage, error)
    return store.replay(run["id"])
