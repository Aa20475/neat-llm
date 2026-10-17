import copy
import json

import pytest

from company.workload import grade_output, load_cases, task_prompt


def test_splits_have_distinct_case_ids():
    groups = [{case["id"] for case in load_cases(split)} for split in ("learning", "validation", "heldout")]
    assert all(len(group) == 2 for group in groups)
    assert len(set.union(*groups)) == sum(map(len, groups))


def test_prompt_does_not_expose_evaluator_answer():
    case = {"input": [{"order_id": "example"}], "expected": "PRIVATE_EVALUATOR_SENTINEL"}
    assert "PRIVATE_EVALUATOR_SENTINEL" not in task_prompt(case)


def test_grader_accepts_object_key_reordering():
    expected = load_cases("learning")[1]["expected"]
    assert grade_output(json.dumps(expected, sort_keys=True), expected)["passed"]


@pytest.mark.parametrize("quantity", [True, 1.0, "1"])
def test_grader_rejects_wrong_json_types(quantity):
    expected = load_cases("learning")[1]["expected"]
    actual = copy.deepcopy(expected)
    actual[0]["items"][0]["quantity"] = quantity
    assert not grade_output(json.dumps(actual), expected)["passed"]


def test_grader_rejects_wrong_rounding_and_extra_keys():
    expected = load_cases("learning")[1]["expected"]
    actual = copy.deepcopy(expected)
    actual[0]["total"] = "3.68"
    assert not grade_output(json.dumps(actual), expected)["passed"]
    actual = copy.deepcopy(expected)
    actual[0]["explanation"] = "done"
    assert not grade_output(json.dumps(actual), expected)["passed"]


@pytest.mark.parametrize("output", ['```json\n[]\n```', '{"x":1,"x":2}', '[}'])
def test_grader_rejects_invalid_or_ambiguous_json(output):
    assert grade_output(output, []) == {"passed": False, "reason": "invalid_json"}
