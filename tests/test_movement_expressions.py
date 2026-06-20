import pytest

from susumu_agent.agent.prompt import build_system_prompt
from susumu_agent.business.movement_expressions import (
    ASR_RULES,
    CONTEXT_GOLDEN_CASES,
    GOLDEN_CASES,
    MOTION_RULES,
    UNSUPPORTED_RULES,
    MovementInterpreter,
)

KNOWN_TOOLS = {"move_robot", "rotate_robot", "curve_robot", "execute_sequence", "report_unsupported"}


def test_movement_interpreter_golden_cases():
    interpreter = MovementInterpreter()
    for case in GOLDEN_CASES:
        plan = interpreter.interpret(case.utterance)
        assert plan is not None, case.utterance
        assert plan.tool == case.tool, case.utterance
        _assert_args_subset(case.args, plan.args, case.utterance)


def test_movement_interpreter_context_golden_cases():
    interpreter = MovementInterpreter()
    for case in CONTEXT_GOLDEN_CASES:
        plan = interpreter.interpret_with_context(case.utterance, case.last_command)
        assert plan is not None, case.utterance
        assert plan.tool == case.tool, case.utterance
        _assert_args_subset(case.args, plan.args, case.utterance)


def test_movement_interpreter_context_without_last_command():
    plan = MovementInterpreter().interpret_with_context("もう一回", None)
    assert plan is not None
    assert plan.tool == "report_unsupported"
    assert "直前のコマンドがない" in plan.args["reason"]


def test_explicit_movement_takes_precedence_over_context_replay():
    last_command = {"tool": "rotate_robot", "angle_deg": 90.0, "speed": "medium", "continuous": False}
    plan = MovementInterpreter().interpret_with_context("さっきより速く前進して", last_command)
    assert plan is not None
    assert plan.tool == "move_robot"
    assert plan.args["direction"] == "forward"
    assert plan.args["speed"] == "high"


def test_expression_rule_ids_are_unique():
    rules = ASR_RULES + MOTION_RULES + UNSUPPORTED_RULES
    ids = [rule.id for rule in rules]
    assert len(ids) == len(set(ids))


def test_golden_cases_use_known_tools():
    assert {case.tool for case in GOLDEN_CASES} <= KNOWN_TOOLS


def test_prompt_contains_expanded_movement_rules():
    prompt = build_system_prompt()
    for text in ("進め", "バックして", "右向け右", "時計回り", "円を描いて", "ジグザグに進む", "curve_robot"):
        assert text in prompt


def test_prompt_size_budget_for_llm_performance():
    assert len(build_system_prompt()) <= 3800


def _assert_args_subset(expected: dict, actual: dict, label: str) -> None:
    for key, expected_value in expected.items():
        assert key in actual, label
        actual_value = actual[key]
        if isinstance(expected_value, float):
            assert actual_value == pytest.approx(expected_value), label
        else:
            assert actual_value == expected_value, label
