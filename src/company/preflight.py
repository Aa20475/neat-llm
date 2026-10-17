"""Bounded live checks for Crusoe, tool calling, and Deep Agents delegation.

Run with: python -m company.preflight
This command makes paid inference calls; it never runs benchmark held-out tasks.
"""

import asyncio
from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
import threading
import time
from typing import Any

from deepagents import create_deep_agent
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool
from openai import AsyncOpenAI

from company.config import PROJECT_ROOT, Settings


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two integers exactly; use this to verify tool execution."""
    return a * b


class UsageMeter(BaseCallbackHandler):
    """Meter parent and child calls without recording prompts or credentials."""

    raise_error = True

    def __init__(self, limit: int = 8):
        self.limit = limit
        self.calls = 0
        self.completions: list[dict[str, Any]] = []
        self.tools: list[dict[str, str]] = []
        self._lock = threading.Lock()

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        with self._lock:
            if self.calls >= self.limit:
                raise RuntimeError("Preflight model-call limit reached")
            self.calls += 1

    def on_llm_end(self, response, *, run_id, **kwargs):
        for batch in response.generations:
            for generation in batch:
                message = getattr(generation, "message", None)
                usage = getattr(message, "usage_metadata", None) or {}
                metadata = getattr(message, "response_metadata", None) or {}
                with self._lock:
                    self.completions.append({
                        "run_id": str(run_id),
                        "usage": usage,
                        "model": metadata.get("model_name"),
                        "finish_reason": metadata.get("finish_reason"),
                    })

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kwargs):
        with self._lock:
            self.tools.append({
                "name": serialized.get("name", "unknown"),
                "run_id": str(run_id),
                "parent_run_id": str(parent_run_id),
            })

    def report(self) -> dict[str, Any]:
        return {
            "model_calls": self.calls,
            "completed_calls": len(self.completions),
            "input_tokens": sum(item["usage"].get("input_tokens", 0) for item in self.completions),
            "output_tokens": sum(item["usage"].get("output_tokens", 0) for item in self.completions),
            "calls": self.completions,
            "tool_events": self.tools,
        }


async def check(settings: Settings, report: dict, meter: UsageMeter) -> None:
    async with AsyncOpenAI(
        api_key=settings.api_key, base_url=settings.base_url,
        timeout=settings.timeout, max_retries=0,
    ) as client:
        catalog = await client.models.list()
    available = {item.id: item.model_dump() for item in catalog.data}
    if settings.model not in available:
        raise RuntimeError("Configured model is absent from the live catalog")
    selected = available[settings.model]
    capabilities = selected.get("supported_parameters", [])
    if capabilities and not {"tools", "tool_choice"}.issubset(capabilities):
        raise RuntimeError("Configured model does not advertise required tool capabilities")
    report["discovery"] = {"passed": True, "model_count": len(available), "model": selected}
    print(f"PASS model discovery: {settings.model}", flush=True)

    model = settings.chat_model()
    callbacks = {"callbacks": [meter]}
    prompt = HumanMessage(content="Call multiply with a=7 and b=6. After receiving the tool result, reply with only the integer result.")
    first = await model.bind_tools([multiply], tool_choice="auto").ainvoke([prompt], config=callbacks)
    if len(first.tool_calls) != 1 or first.tool_calls[0]["name"] != "multiply":
        raise RuntimeError("Model did not produce the expected tool call")
    call = first.tool_calls[0]
    if call["args"] != {"a": 7, "b": 6}:
        raise RuntimeError("Model supplied incorrect tool arguments")
    value = multiply.invoke(call["args"])
    second = await model.ainvoke([
        prompt, first, ToolMessage(content=str(value), tool_call_id=call["id"]),
    ], config=callbacks)
    if second.text.strip() != "42":
        raise RuntimeError("Tool result did not round-trip correctly")
    report["tool_round_trip"] = {"passed": True, "tool": "multiply", "result": value}
    print("PASS model -> multiply(7, 6) -> model: 42", flush=True)

    agent = create_deep_agent(
        model=model,
        tools=[multiply],
        system_prompt=(
            "You are running a small integration check. Follow the requested delegation exactly. "
            "Do not read or write files, create a todo list, or run shell commands. "
            "For arithmetic, use the multiply tool. Return only the final integer."
        ),
    )
    start_tools = len(meter.tools)
    result = await asyncio.wait_for(agent.ainvoke({
        "messages": [HumanMessage(content=(
            "Use the task tool exactly once with subagent_type='general-purpose'. "
            "Ask the child to call multiply(a=7, b=6) and return the result. "
            "When the child returns, reply only with its integer result."
        ))],
    }, config={"callbacks": [meter], "recursion_limit": 12}), timeout=150)
    events = meter.tools[start_tools:]
    names = [event["name"] for event in events]
    answer = result["messages"][-1].text.strip()
    if names.count("task") != 1 or "multiply" not in names or answer != "42":
        raise RuntimeError("Deep Agents delegation or child tool execution did not pass")
    report["deepagents_delegation"] = {"passed": True, "tools": names, "result": answer}
    print("PASS Deep Agents -> general-purpose child -> multiply -> parent: 42", flush=True)


async def main() -> int:
    started = time.monotonic()
    meter = UsageMeter()
    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "versions": {name: version(name) for name in ("deepagents", "langchain-openai", "langgraph")},
        "limits": {"max_model_calls": meter.limit, "max_retries": 0, "wall_seconds": 210},
    }
    path = PROJECT_ROOT / "artifacts" / "preflight.json"
    try:
        settings = Settings.load()
        report["limits"].update(max_output_tokens_per_call=settings.max_tokens, request_timeout=settings.timeout)
        await asyncio.wait_for(check(settings, report, meter), timeout=210)
        report["status"] = "passed"
    except Exception as error:
        # Exception messages may contain request details; only emit safe classifications.
        report["status"] = "failed"
        report["error_type"] = type(error).__name__
        report["http_status"] = getattr(error, "status_code", None)
        if "settings" in locals():
            report["error_detail"] = str(error).replace(settings.api_key, "[REDACTED]")[:1500]
        print(f"FAIL preflight: {report['error_type']} (HTTP {report['http_status']})", flush=True)
        if report.get("error_detail"):
            print(report["error_detail"], flush=True)
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report["usage"] = meter.report()
        path.parent.mkdir(exist_ok=True)
        history_name = "preflight-" + report["started_at"].replace(":", "-") + ".json"
        (path.parent / history_name).write_text(json.dumps(report, indent=2, default=str) + "\n")
        path.write_text(json.dumps(report, indent=2, default=str) + "\n")
        print(f"Report: {path.relative_to(PROJECT_ROOT)}", flush=True)
        print(f"Model calls: {meter.calls}; input tokens: {report['usage']['input_tokens']}; output tokens: {report['usage']['output_tokens']}", flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
