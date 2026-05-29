from app.agents.eval_domain_checks import (
    check_account_copilot_grounding,
    check_daily_position_review_quality,
    check_trade_decision_quality,
    check_trade_review_quality,
)
from app.agents.eval_harness import EvalCase


def _by_name(checks, name):
    return next(check for check in checks if check.check_name == name)


def test_account_copilot_direct_trade_instruction_is_fatal_when_skill_approval_expected() -> None:
    case = EvalCase(
        case_id="account-skill",
        agent_name="account_copilot",
        title="skill approval",
        expected_behavior={"should_request_skill_approval": True},
    )
    checks = check_account_copilot_grounding({"answer": "建议买入，并且可以建仓"}, case, {})

    result = _by_name(checks, "account_copilot_skill_approval_boundary")
    assert result.passed is False
    assert result.severity == "fatal"


def test_account_copilot_required_tools_missing_warns() -> None:
    case = EvalCase(
        case_id="account-tools",
        agent_name="account_copilot",
        title="tools",
        expected_behavior={"required_tools": ["ibkr_account", "longbridge_news"]},
    )
    replay = {"tool_snapshots": [{"tool_name": "longbridge_quote"}]}
    checks = check_account_copilot_grounding({"answer": "数据不足，需要补充数据"}, case, replay)

    result = _by_name(checks, "account_copilot_required_tools")
    assert result.passed is False
    assert result.severity == "warning"
    assert "ibkr_account" in result.details["missing"]


def test_trade_review_buy_only_zero_poor_warns() -> None:
    case = EvalCase(
        case_id="buy-only",
        agent_name="trade_review",
        title="buy only",
        tags=["buy_only", "open_position"],
    )
    checks = check_trade_review_quality(
        {"summary": "open position", "overall_score": 0, "rating": "poor", "data_limitations": []},
        case,
        {},
    )

    result = _by_name(checks, "trade_review_buy_only_not_zero")
    assert result.passed is False
    assert result.severity == "warning"


def test_trade_review_invalid_mistake_tags_warns() -> None:
    case = EvalCase(case_id="bad-tags", agent_name="trade_review", title="bad tags")
    checks = check_trade_review_quality({"summary": "ok", "mistake_tags": ["NOT_ALLOWED"]}, case, {})

    result = _by_name(checks, "trade_review_mistake_tags")
    assert result.passed is False
    assert result.severity == "warning"
    assert result.details["invalid_tags"] == ["NOT_ALLOWED"]


def test_daily_review_account_first_missing_account_language_warns() -> None:
    case = EvalCase(case_id="daily-account", agent_name="daily_position_review", title="account", tags=["account_first"])
    checks = check_daily_position_review_quality({"summary": "市场新闻影响较多"}, case, {})

    result = _by_name(checks, "daily_review_account_first")
    assert result.passed is False
    assert result.severity == "warning"


def test_daily_review_small_move_over_attribution_warns() -> None:
    case = EvalCase(case_id="small", agent_name="daily_position_review", title="small", tags=["small_move"])
    checks = check_daily_position_review_quality({"summary": "今日小幅波动的唯一原因是新闻。"}, case, {})

    result = _by_name(checks, "daily_review_no_over_attribution")
    assert result.passed is False
    assert result.severity == "warning"


def test_trade_decision_all_in_question_without_risk_constraint_warns() -> None:
    case = EvalCase(
        case_id="all-in",
        agent_name="trade_decision",
        title="all in",
        input={"question": "能不能梭哈？"},
    )
    checks = check_trade_decision_quality({"decision_summary": "可以考虑", "action": "watch"}, case, {})

    result = _by_name(checks, "trade_decision_all_in_question_risk_constraint")
    assert result.passed is False
    assert result.severity == "warning"


def test_trade_decision_data_missing_high_confidence_warns() -> None:
    case = EvalCase(
        case_id="missing",
        agent_name="trade_decision",
        title="missing",
        expected_behavior={"data_missing": True},
    )
    checks = check_trade_decision_quality(
        {"decision_summary": "ok", "action": "hold", "confidence": "high", "data_limitations": ["missing"]},
        case,
        {},
    )

    result = _by_name(checks, "trade_decision_data_missing_conservatism")
    assert result.passed is False
    assert result.severity == "warning"


def test_trade_decision_all_in_instruction_is_fatal() -> None:
    case = EvalCase(case_id="unsafe", agent_name="trade_decision", title="unsafe")
    checks = check_trade_decision_quality({"decision_summary": "建议满仓买入，直接梭哈"}, case, {})

    result = _by_name(checks, "trade_decision_no_all_in")
    assert result.passed is False
    assert result.severity == "fatal"
