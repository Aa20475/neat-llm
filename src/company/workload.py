"""Explicit dataset splits and a strict deterministic output grader."""

import json
from typing import Any

from company.config import PROJECT_ROOT

FIXTURES = PROJECT_ROOT / "fixtures" / "orders"
SPLITS = ("learning", "validation", "heldout")


def load_cases(split: str) -> list[dict[str, Any]]:
    if split not in SPLITS:
        raise ValueError("Unknown dataset split")
    return json.loads((FIXTURES / f"{split}.json").read_text())


def task_prompt(case: dict[str, Any]) -> str:
    """Expose the task specification and input, never the evaluator answer."""
    return (FIXTURES / "spec.md").read_text() + "\nInput:\n" + json.dumps(case["input"])


def _strict_equal(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            _strict_equal(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _strict_equal(a, b) for a, b in zip(actual, expected)
        )
    return actual == expected


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def grade_output(output: str, expected: Any) -> dict[str, Any]:
    try:
        actual = json.loads(output, object_pairs_hook=_unique_object)
    except (ValueError, TypeError):
        return {"passed": False, "reason": "invalid_json"}
    passed = _strict_equal(actual, expected)
    return {"passed": passed, "reason": "exact_match" if passed else "output_mismatch"}
