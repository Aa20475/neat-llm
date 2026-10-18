"""Compile the saved v0 layout into Deep Agents and persist actual execution."""

import asyncio
from dataclasses import replace
import sys
import threading
import time

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain.agents import create_agent
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_core.runnables import RunnableLambda

from company.agent_tools import TOOLS
from company.config import Settings
from company.organization import role_prompt, validate_manifest, worker_files
from company.store import Store
from company.workload import grade_output


class BudgetExceeded(RuntimeError):
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
        self.calls = self.completed = self.tool_calls = self.worker_count = 0
        self.input_tokens = self.output_tokens = self.usage_missing = 0
        self.child_tool_calls = 0
        self.child_tools: set[str] = set()
        self.violation: str | None = None
        self._lock = threading.RLock()

    def clean(self, value):
        if isinstance(value, dict):
            return {str(key): self.clean(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.clean(item) for item in value]
        if value is None or type(value) in (int, float, bool):
            return value
        text = str(value)
        if self.secret:
            text = text.replace(self.secret, "[REDACTED]")
        return text[:12000]

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
                    self.record("model_finished", self.owner(run_id), call_id=str(run_id), usage=usage,
                                output=getattr(message, "text", ""), tool_calls=getattr(message, "tool_calls", []))

    def on_llm_error(self, error, *, run_id, **kwargs):
        with self._lock:
            self.record("model_error", self.owner(run_id), call_id=str(run_id), error_type=type(error).__name__)

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, inputs=None, **kwargs):
        with self._lock:
            self.link(run_id, parent_run_id)
            if self.violation:
                raise BudgetExceeded(self.violation)
            if self.limits["tool_calls"] is not None and self.tool_calls >= self.limits["tool_calls"]:
                self.deny("tool_calls")
            name = serialized.get("name", "unknown")
            # Explicit allowlist also applies to framework-injected tools.
            if name not in (*TOOLS, "task", "write_todos", "read_file"):
                self.deny("unapproved_tool")
            owner = self.owner(parent_run_id)
            self.tool_names[str(run_id)] = name
            self.tool_owners[str(run_id)] = owner
            arguments = inputs if isinstance(inputs, dict) else {"input": input_str}
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
            self.record("tool_finished", self.tool_owners.get(str(run_id), self.root), call_id=str(run_id), name=self.tool_names.get(str(run_id)), output=getattr(output, "content", output))
            if child := self.task_workers.get(str(run_id)):
                self.store.worker_finish(child, "completed")
                self.record("worker_finished", child, status="completed")

    def on_tool_error(self, error, *, run_id, **kwargs):
        with self._lock:
            self.record("tool_error", self.tool_owners.get(str(run_id), self.root), call_id=str(run_id), error_type=type(error).__name__)
            if child := self.task_workers.get(str(run_id)):
                self.store.worker_finish(child, "failed")
                self.record("worker_finished", child, status="failed")

    def usage(self):
        return {"phase": self.phase, "model_calls": self.calls, "completed_calls": self.completed,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "tool_calls": self.tool_calls, "temporary_workers": self.worker_count - self.saved_workers, "saved_role_workers": self.saved_workers,
                "complete": self.completed == self.calls and self.usage_missing == 0}


def build_agent(manifest: dict, settings: Settings):
    validate_manifest(manifest)
    inference = manifest["inference"]
    # Do not send the user's credential to a different endpoint stored in a proposal.
    if inference["base_url"] != settings.base_url:
        raise ValueError("Saved provider endpoint differs from configured endpoint")
    pinned = replace(settings, model=inference["model"], max_tokens=inference["max_tokens"], timeout=inference["timeout"])
    # Shared by parent and children. Pace requests without hidden retry calls.
    model = pinned.chat_model()
    model.rate_limiter = InMemoryRateLimiter(requests_per_second=0.5, check_every_n_seconds=0.1, max_bucket_size=1)
    root_role = manifest["topology"]["roles"][0]
    tools = [TOOLS[name] for name in root_role.get("tools", manifest["tools"]["names"])]
    backend = StateBackend()
    prompt = role_prompt(manifest) + "\nYour saved configuration is available under /organization/; read /organization/README.md for the file index if needed."
    subagents = [{
            "name": "general-purpose", "description": "A temporary generalist for a bounded subtask; include the necessary input and instructions.",
            "system_prompt": prompt, "model": model, "tools": tools,
            "middleware": [FilesystemMiddleware(backend=backend, tools=["read_file"])],
        }]
    def compile_specialist(role):
        # A compiled child stages its own role tree and returns only messages.
        # Its role files never merge back into the parent's filesystem state.
        child = create_agent(model=model, tools=[TOOLS[name] for name in role.get("tools", manifest["tools"]["names"])],
                             system_prompt=role_prompt(manifest, role["id"]),
                             middleware=[FilesystemMiddleware(backend=StateBackend(), tools=["read_file"])])
        async def invoke(state, config):
            result = await child.ainvoke({"messages": state["messages"], "files": worker_files(manifest, role["id"])}, config=config)
            return {"messages": result["messages"]}
        return {"name": role["id"], "description": role["description"], "runnable": RunnableLambda(invoke)}
    subagents.extend(compile_specialist(role) for role in manifest["topology"]["roles"][1:])
    return create_deep_agent(
        model=model, tools=tools, system_prompt=prompt, backend=backend,
        middleware=[FilesystemMiddleware(backend=backend, tools=["read_file"])], subagents=subagents,
    )


async def execute(store: Store, settings: Settings, *, task_id: str, split: str, prompt: str, expected,
                  require_delegation: bool = False, version_id: str | None = None, budget=None, phase="execution",
                  ungraded: bool = False, conversation=None, chat_turn_id: str | None = None) -> dict:
    """Caller owns the controller lock. The evaluator's expected value never enters the agent."""
    run = store.start_run(task_id, split, prompt, version_id=version_id)
    if chat_turn_id:
        store.link_chat_run(chat_turn_id, run["id"])
    trace = RunTrace(store, run, settings.api_key, budget=budget, phase=phase)
    start = time.monotonic()
    output, grade, error, status = None, None, None, "failed"
    try:
        agent = build_agent(run["manifest"], settings)
        trace.record("runtime_config", trace.root, request_interval_seconds=2,
                     filesystem="state_snapshot", readable_paths=sorted(worker_files(run["manifest"])))
        result = await asyncio.wait_for(agent.ainvoke(
            {"messages": [*(conversation or []), HumanMessage(content=prompt)], "files": worker_files(run["manifest"])},
            # LangGraph requires a positive integer. Use its effectively unbounded
            # range so an unrelated 50-step ceiling does not replace the call cap.
            config={"callbacks": [trace], "recursion_limit": sys.maxsize},
        ), timeout=run["manifest"]["limits"]["wall_seconds"])
        if trace.violation:
            raise BudgetExceeded(trace.violation)
        output = result["messages"][-1].text.strip()
        grade = None if ungraded else grade_output(output, expected)
        if require_delegation and (trace.worker_count == 0 or "decimal_product" not in trace.child_tools):
            grade = {"passed": False, "reason": "delegation_not_observed"}
        status = "completed"  # Completion and independently checked correctness are separate.
        if grade is not None:
            trace.record("evaluation_finished", trace.root, **grade)
    except BudgetExceeded as exc:
        status, error = "budget_exceeded", str(exc)
    except TimeoutError:
        status, error = "timed_out", "Run exceeded its wall-clock limit"
    except asyncio.CancelledError:
        status, error = "interrupted", "Controller was interrupted"
        raise
    except Exception as exc:
        status = "budget_exceeded" if trace.violation else "failed"
        error = trace.violation or type(exc).__name__  # Provider exception strings can contain credentials.
        trace.record("run_error", trace.root, error_type=type(exc).__name__,
                     http_status=getattr(exc, "status_code", None), detail=str(exc),
                     retry_after=getattr(getattr(exc, "response", None), "headers", {}).get("retry-after"))
    finally:
        usage = trace.usage()
        usage["elapsed_seconds"] = round(time.monotonic() - start, 3)
        store.finish(run["id"], status, trace.clean(output), grade, usage, error)
    return store.replay(run["id"])
