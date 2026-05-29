from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.agents.trade_review_graph.nodes import (
    make_behavior_pattern_node,
    make_compose_trade_review_node,
    make_opportunity_cost_node,
)
from app.agents.trade_review_graph.prompts import (
    TRADE_REVIEW_BEHAVIOR_PATTERN_SYSTEM_PROMPT,
    TRADE_REVIEW_MAIN_SYSTEM_PROMPT,
    TRADE_REVIEW_OPPORTUNITY_COST_SYSTEM_PROMPT,
)
from app.agents.trade_review_graph.graph import TradeReviewGraphDeps
from app.schemas.trade_review import AgentRunTraceItem


class SequencedLLM:
    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[dict] = []

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return self.responses.pop(0) if self.responses else "not json"

    def get_active_provider(self):
        return None


class FakeRuntime:
    def __init__(self, content: str) -> None:
        self.content = content

    def run(self, **kwargs):
        return {"content": self.content, "trace": [{"event": "llm_finish", "total_tokens": 10}]}


def _deps(llm=None):
    deps = MagicMock(spec=TradeReviewGraphDeps)
    deps.llm_service = llm or SequencedLLM()
    deps.evidence_builder = MagicMock()
    deps.repository = MagicMock()
    return deps


def _state(**overrides) -> dict:
    state = {
        "review_type": "symbol_level_review",
        "symbol": "AMD.US",
        "trade_id": None,
        "start_date": "2026-01-01",
        "end_date": "2026-05-01",
        "merged_review_context": {"trade_facts": {"trades": [{"trade_id": "t1"}]}},
        "behavior_pattern_analysis": {},
        "opportunity_cost_analysis": {},
        "node_traces": [],
        "errors": [],
        "fallback_used": False,
        "fallback_reason": None,
    }
    state.update(overrides)
    return state


def behavior_json(**overrides) -> str:
    payload = {
        "behavior_patterns": ["分批买入后没有明确退出计划"],
        "behavior_score": 62,
        "behavior_summary": "交易行为整体有计划性。",
        "recurring_patterns": ["上涨趋势中加仓偏谨慎"],
        "positive_patterns": ["没有单笔满仓"],
        "negative_patterns": ["卖出前缺少替代机会检查"],
        "mistake_tags": ["POSITION_TOO_SMALL"],
        "improvement_notes": ["下次卖出前检查相对强弱"],
        "confidence": "medium",
        "data_limitations": [],
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def opportunity_json(**overrides) -> str:
    payload = {
        "opportunity_cost_score": 68,
        "benchmark_comparison": {"QQQ": "科技 beta 仍强"},
        "opportunity_cost_summary": "存在中等机会成本。",
        "missed_upside": ["可能错过趋势收益"],
        "avoided_downside": ["降低集中度"],
        "capital_redeployment": ["需要看资金去向"],
        "alternative_actions": ["可以考虑分批止盈"],
        "severity": "medium",
        "confidence": "medium",
        "data_limitations": [],
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def main_json(**overrides) -> str:
    payload = {
        "symbol": "AMD.US",
        "review_type": "symbol_level_review",
        "overall_score": 72,
        "rating": "good",
        "score_detail": {
            "return_result_score": {"score": 14, "max_score": 20, "reason": "ok"},
            "relative_performance_score": {"score": 10, "max_score": 15, "reason": "ok"},
            "entry_quality_score": {"score": 10, "max_score": 15, "reason": "ok"},
            "exit_quality_score": {"score": 10, "max_score": 15, "reason": "ok"},
            "position_sizing_score": {"score": 10, "max_score": 15, "reason": "ok"},
            "holding_period_score": {"score": 5, "max_score": 5, "reason": "ok"},
            "risk_control_score": {"score": 8, "max_score": 10, "reason": "ok"},
            "decision_attribution_score": {"score": 5, "max_score": 5, "reason": "ok"},
        },
        "summary": "这次交易方向判断较好。",
        "strengths": ["买入逻辑清晰"],
        "weaknesses": ["仓位偏小"],
        "mistake_tags": ["POSITION_TOO_SMALL"],
        "improvement_suggestions": ["提前设计分批规则"],
        "data_limitations": [],
        "evidence_used": ["IBKR trades"],
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def _last_trace(result: dict) -> dict:
    return result["node_traces"][-1]


def test_behavior_pattern_normal_json() -> None:
    node = make_behavior_pattern_node(_deps())
    with patch("app.agents.trade_review_graph.nodes.ToolCallingRuntime", return_value=FakeRuntime(behavior_json())):
        result = node(_state())

    assert result["behavior_pattern_analysis"]["behavior_score"] == 62
    assert result["behavior_structured_output"]["repaired"] is False
    assert _last_trace(result)["structured_output"]["schema_validation_passed"] is True


def test_behavior_pattern_non_json_repairs_successfully() -> None:
    node = make_behavior_pattern_node(_deps(SequencedLLM([behavior_json(behavior_score=70)])))
    with patch("app.agents.trade_review_graph.nodes.ToolCallingRuntime", return_value=FakeRuntime("not json")):
        result = node(_state())

    assert result["behavior_pattern_analysis"]["behavior_score"] == 70
    assert result["behavior_structured_output"]["repaired"] is True


def test_behavior_pattern_repair_failure_uses_existing_fallback() -> None:
    node = make_behavior_pattern_node(_deps(SequencedLLM(["still bad"])))
    with patch("app.agents.trade_review_graph.nodes.ToolCallingRuntime", return_value=FakeRuntime("not json")):
        result = node(_state())

    assert result["behavior_pattern_analysis"]["behavior_score"] == 0
    assert result["behavior_structured_output"]["error_code"] in {"LLM_REPAIR_FAILED", "LLM_JSON_PARSE_FAILED"}


def test_opportunity_cost_normal_json() -> None:
    node = make_opportunity_cost_node(_deps())
    with patch("app.agents.trade_review_graph.nodes.ToolCallingRuntime", return_value=FakeRuntime(opportunity_json())):
        result = node(_state())

    assert result["opportunity_cost_analysis"]["opportunity_cost_score"] == 68
    assert result["opportunity_cost_analysis"]["benchmark_comparison"]["QQQ"]


def test_opportunity_cost_schema_error_repairs_successfully() -> None:
    node = make_opportunity_cost_node(_deps(SequencedLLM([opportunity_json(severity="low")])))
    with patch(
        "app.agents.trade_review_graph.nodes.ToolCallingRuntime",
        return_value=FakeRuntime(opportunity_json(severity="severe")),
    ):
        result = node(_state())

    assert result["opportunity_cost_analysis"]["severity"] == "low"
    assert result["opportunity_structured_output"]["repaired"] is True


def test_opportunity_cost_repair_failure_uses_existing_fallback() -> None:
    node = make_opportunity_cost_node(_deps(SequencedLLM(["bad"])))
    with patch("app.agents.trade_review_graph.nodes.ToolCallingRuntime", return_value=FakeRuntime("not json")):
        result = node(_state())

    assert result["opportunity_cost_analysis"]["opportunity_cost_score"] == 0
    assert result["opportunity_structured_output"]["schema_validation_passed"] is False


def test_compose_trade_review_normal_json() -> None:
    node = make_compose_trade_review_node(_deps())
    with patch("app.agents.trade_review_graph.nodes.ToolCallingRuntime", return_value=FakeRuntime(main_json())):
        result = node(_state())

    # exit_quality excluded (no sell trades): raw=62, applicable_max=85, normalized=72.94
    assert abs(result["trade_review_output"]["overall_score"] - 72.94) < 0.01
    assert result["structured_output"]["trade_review_main"]["schema_validation_passed"] is True


def test_compose_trade_review_missing_fields_repairs_successfully() -> None:
    node = make_compose_trade_review_node(_deps(SequencedLLM([main_json(summary="repaired")])))
    with patch("app.agents.trade_review_graph.nodes.ToolCallingRuntime", return_value=FakeRuntime('{"summary": "bad"}')):
        result = node(_state())

    assert result["trade_review_output"]["summary"] == "repaired"
    assert result["structured_output"]["trade_review_main"]["repaired"] is True


def test_compose_trade_review_repair_failure_uses_fallback() -> None:
    node = make_compose_trade_review_node(_deps(SequencedLLM(["bad"])))
    with patch("app.agents.trade_review_graph.nodes.ToolCallingRuntime", return_value=FakeRuntime("not json")):
        result = node(_state())

    assert result["trade_review_output"]["overall_score"] == 0
    assert result["fallback_used"] is True
    assert result["structured_output"]["trade_review_main"]["fallback_used"] is True


def test_trade_review_prompts_include_examples_and_format_rules() -> None:
    assert "正常样例" in TRADE_REVIEW_BEHAVIOR_PATTERN_SYSTEM_PROMPT
    assert "数据不足样例" in TRADE_REVIEW_BEHAVIOR_PATTERN_SYSTEM_PROMPT
    assert "正常样例" in TRADE_REVIEW_OPPORTUNITY_COST_SYSTEM_PROMPT
    assert "数据不足样例" in TRADE_REVIEW_OPPORTUNITY_COST_SYSTEM_PROMPT
    for prompt in (
        TRADE_REVIEW_MAIN_SYSTEM_PROMPT,
        TRADE_REVIEW_BEHAVIOR_PATTERN_SYSTEM_PROMPT,
        TRADE_REVIEW_OPPORTUNITY_COST_SYSTEM_PROMPT,
    ):
        assert "JSON object" in prompt
        assert "不要 Markdown" in prompt
        assert "不要代码块" in prompt
        assert "不要省略字段" in prompt


def test_trade_review_public_run_trace_preserves_structured_output_fields() -> None:
    item = AgentRunTraceItem(
        event="node_success",
        node_name="compose_trade_review",
        structured_output={"contract_name": "trade_review_main"},
        runtime_trace=[{"event": "structured_output_result", "contract_name": "trade_review_main"}],
    )

    dumped = item.model_dump()
    assert dumped["structured_output"]["contract_name"] == "trade_review_main"
    assert dumped["runtime_trace"][0]["event"] == "structured_output_result"
