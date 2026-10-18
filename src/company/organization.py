"""Immutable configuration snapshots; live worker instances belong to runs."""

import hashlib
from importlib.metadata import version
import json
from pathlib import Path

from company.config import Settings


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def behavior_digest(manifest: dict) -> str:
    """Display labels do not make an otherwise identical configuration a new experiment."""
    return digest({key: value for key, value in manifest.items() if key != "label"})


def tool_revision() -> str:
    sources = ("agent_tools.py", "python_runner.py")
    return hashlib.sha256(b"".join(name.encode() + b"\0" + Path(__file__).with_name(name).read_bytes()
                                   for name in sources)).hexdigest()


def initial_manifest(settings: Settings) -> dict:
    return {
        "schema_version": 1,
        "label": "v0",
        "inference": {
            "model": settings.model, "base_url": settings.base_url,
            "max_tokens": settings.max_tokens, "timeout": settings.timeout,
            "temperature": 0, "max_retries": 0, "enable_thinking": False,
        },
        "runtime": {name: version(name) for name in ("deepagents", "langchain-openai", "langgraph")},
        "prompts": {"generalist": (
            "You are a capable generalist. Complete the user's task and obey its output format. "
            "Use Python to implement and test code or process data when useful; exact decimal tools "
            "are also available. You may delegate a bounded "
            "subtask to a temporary general-purpose worker when useful; include all necessary "
            "context in its task description. You are responsible for the final answer."
        )},
        "skills": {},
        "task_memory": {},
        "tools": {
            "names": ["decimal_product", "decimal_sum", "python_execute"], "source_sha256": tool_revision(),
            "framework": ["read_file", "write_todos", "task"], "filesystem": "ephemeral_state",
        },
        "topology": {
            "root": "generalist",
            "roles": [{"id": "generalist", "prompt": "generalist", "skills": [], "memory": []}],
            "edges": [],
            "temporary_worker": {"type": "general-purpose", "inherits_role": "generalist"},
        },
        "limits": {"model_calls": None, "tool_calls": None, "workers": None, "worker_depth": 1, "wall_seconds": None},
    }


def validate_manifest(manifest: dict) -> None:
    """Validate a generalist with up to two optional retained specialist roles."""
    if manifest["schema_version"] != 1:
        raise ValueError("Unsupported manifest schema")
    topology = manifest["topology"]
    roles = topology["roles"]
    if topology["root"] != "generalist" or not 1 <= len(roles) <= 3 or roles[0]["id"] != "generalist":
        raise ValueError("Expected a generalist and at most two retained specialists")
    ids = {role["id"] for role in roles}
    if len(ids) != len(roles) or "general-purpose" in ids:
        raise ValueError("Duplicate or reserved role ID")
    if topology["temporary_worker"] != {"type": "general-purpose", "inherits_role": "generalist"}:
        raise ValueError("Unsupported worker binding")
    for role in roles:
        if role["prompt"] not in manifest["prompts"]:
            raise ValueError("Unresolved prompt")
        if any(name not in manifest["skills"] for name in role["skills"]) or any(name not in manifest["task_memory"] for name in role["memory"]):
            raise ValueError("Unresolved skill or memory binding")
        if set(role.get("tools", manifest["tools"]["names"])) - set(manifest["tools"]["names"]):
            raise ValueError("Role requests an unapproved tool")
    targets = []
    for edge in topology["edges"]:
        if edge.get("from") != "generalist" or edge.get("to") not in ids - {"generalist"} or edge.get("type") != "delegate" or not isinstance(edge.get("condition"), str):
            raise ValueError("Only optional root-to-specialist delegation edges are supported")
        targets.append(edge["to"])
    if set(targets) != ids - {"generalist"} or len(targets) != len(set(targets)):
        raise ValueError("Each specialist needs exactly one root delegation edge")
    if manifest["tools"]["source_sha256"] != tool_revision():
        raise ValueError("Tool implementation changed; create an explicit new version before running")
    if manifest["tools"].get("filesystem") != "ephemeral_state" or manifest["tools"].get("framework") != ["read_file", "write_todos", "task"]:
        raise ValueError("Unsupported framework tool configuration")
    inference = manifest["inference"]
    if (inference["temperature"], inference["max_retries"], inference["enable_thinking"]) != (0, 0, False):
        raise ValueError("Unsupported inference policy")
    if not 1 <= inference["max_tokens"] <= 8192 or not 0 < inference["timeout"] <= 120:
        raise ValueError("Inference limits outside controller policy")
    from company.agent_tools import TOOLS
    if set(manifest["tools"]["names"]) - TOOLS.keys():
        raise ValueError("Unknown tool binding")
    for package, pinned in manifest["runtime"].items():
        if version(package) != pinned:
            raise ValueError(f"Runtime package differs from saved version: {package}")
    for name in ("model_calls", "tool_calls", "workers", "wall_seconds"):
        value = manifest["limits"][name]
        if value is not None and (type(value) is not int or value < 1):
            raise ValueError(f"Invalid controller limit: {name}")
    if type(manifest["limits"]["worker_depth"]) is not int or manifest["limits"]["worker_depth"] != 1:
        raise ValueError("Only one level of worker delegation is supported")


def role_prompt(manifest: dict, role_id: str = "generalist") -> str:
    role = next(role for role in manifest["topology"]["roles"] if role["id"] == role_id)
    parts = [manifest["prompts"][role["prompt"]]]
    parts += [f"Skill {name}:\n{manifest['skills'][name]}" for name in role["skills"]]
    parts += [f"Project memory {name}:\n{manifest['task_memory'][name]}" for name in role["memory"]]
    return "\n\n".join(parts)


def worker_files(manifest: dict, role_id: str = "generalist") -> dict:
    """Stage only the pinned role's readable configuration in graph-local state.

    Deep Agents passes a snapshot of this state to each temporary child. No
    host mount is involved; filesystem write tools are not enabled.
    """
    from deepagents.backends.utils import create_file_data
    from urllib.parse import quote
    role = next(role for role in manifest["topology"]["roles"] if role["id"] == role_id)
    contents = {"/organization/prompt.md": manifest["prompts"][role["prompt"]]}
    for name in role["skills"]:
        contents[f"/organization/skills/{quote(name, safe='')}.md"] = manifest["skills"][name]
    for name in role["memory"]:
        contents[f"/organization/memory/{quote(name, safe='')}.md"] = manifest["task_memory"][name]
    contents["/organization/README.md"] = (
        "Read-only configuration for this run. Files:\n" + "\n".join(sorted(contents))
    )
    return {path: create_file_data(text) for path, text in contents.items()}
