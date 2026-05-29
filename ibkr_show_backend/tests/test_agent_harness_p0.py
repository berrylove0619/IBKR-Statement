import json
from typing import Any

import pytest

from app.agents.context_budget import (
    compact_news_items,
    enforce_section_budget,
    estimate_json_chars,
    limit_list,
    trim_text,
)
from app.agents.evidence_schema import build_daily_position_review_evidence_pack, build_trade_decision_evidence_pack
from app.agents.runtime import AgentTool, ToolCallingRuntime
from app.services.daily_position_review_agent import DailyPositionReviewAgent, DailyPositionReviewAgentError
from app.services.trade_decision_agent import TradeDecisionAgent
from app.services.trade_review_agent import TradeReviewAgent
from tests.test_trade_decision_agent import valid_decision_payload
from tests.test_trade_review_agent import valid_llm_payload


def test_runtime_output_budget_section_is_used_when_output_compactor_is_absent() -> None:
    from app.agents.runtime import AgentTool, ToolCallingRuntime

    class CheckBudgetLLM:
        def get_active_provider(self):
            class P:
                name = "test"
                base_url = "http://test"
                default_model = "test"
            return P()

        def chat_with_tools(self, messages, **kwargs):
            return {"role": "assistant", "content": '{"ok": true}', "tool_calls": []}

    def tool_handler() -> dict:
        return {"items": [{"text": "x" * 200} for _ in range(5)], "source": "test"}

    runtime = ToolCallingRuntime(CheckBudgetLLM(), max_observation_chars=50000)
    result = runtime.run(
        messages=[{"role": "user", "content": "run"}],
        tools=[
            AgentTool(
                "budget_tool",
                "Test tool",
                {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
                tool_handler,
                output_budget_section="account_context",
            )
        ],
        initial_tool_calls=[{"name": "budget_tool", "arguments": {}}],
    )
    tool_finish = next((e for e in result["trace"] if e.get("event") == "tool_finish"), None)
    assert tool_finish is not None
    assert tool_finish.get("ok") is True
    summary = tool_finish.get("summary", "")
    assert "budget_report" in summary or "object keys" in summary


def test_runtime_output_compactor_takes_priority_over_output_budget_section() -> None:
    from app.agents.runtime import AgentTool, ToolCallingRuntime

    def custom_compactor(value: Any) -> dict:
        return {"compacted": True, "custom": True}

    class CheckCompactorLLM:
        def get_active_provider(self):
            class P:
                name = "test"
                base_url = "http://test"
                default_model = "test"
            return P()

        def chat_with_tools(self, messages, **kwargs):
            return {"role": "assistant", "content": '{"ok": true}', "tool_calls": []}

    runtime = ToolCallingRuntime(CheckCompactorLLM(), max_observation_chars=50000)
    result = runtime.run(
        messages=[{"role": "user", "content": "run"}],
        tools=[
            AgentTool(
                "compactor_tool",
                "Test",
                {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
                lambda: {"items": [1, 2, 3]},
                output_budget_section="account_context",
                output_compactor=custom_compactor,
            )
        ],
        initial_tool_calls=[{"name": "compactor_tool", "arguments": {}}],
    )
    tool_finish = next((e for e in result["trace"] if e.get("event") == "tool_finish"), None)
    assert tool_finish is not None
    summary = tool_finish.get("summary", "")
    assert "compacted" in summary
    payload = {
        "source": "Longbridge public data",
        "news": [
            {
                "title": f"News item {index} " + "T" * 300,
                "summary": "S" * 1000,
                "content": "C" * 5000,
                "published_at": f"2026-05-{index + 1:02d}",
                "source": "LB",
            }
            for index in range(12)
        ],
        "filings": [{"title": f"10-Q-{index}", "body": "x" * 5000} for index in range(6)],
        "data_quality": {"warnings": ["W" * 1000 for _ in range(12)]},
    }

    compact = enforce_section_budget("external_events", payload, 4000)
    encoded = json.dumps(compact, ensure_ascii=False)

    assert json.loads(encoded)["source"] == "Longbridge public data"
    assert compact["dropped_news_count"] == 7
    assert len(compact["news"]) <= 5
    assert len(compact["news"][0]["summary"]) <= 223
    assert "content" not in compact["news"][0]
    assert compact["truncated"] is True


def test_context_budget_helpers_trim_and_limit_without_string_json_cutoff() -> None:
    assert trim_text("abcdef", 5) == "ab..."
    assert limit_list([1, 2, 3, 4], 2, from_end=True) == [3, 4]
    compacted = compact_news_items([{"title": "t", "summary": "s" * 500}], 1, summary_limit=20)
    assert compacted[0]["summary"].endswith("...")
    assert estimate_json_chars({"items": compacted}) == len(json.dumps({"items": compacted}, ensure_ascii=False))


def test_single_trade_review_context_budget_preserves_key_facts() -> None:
    related_trades = [
        {
            "trade_id": f"trade-{index}",
            "symbol": "SMCI.US",
            "date": f"2026-05-{index + 1:02d}",
            "side": "BUY" if index % 3 else "SELL",
            "quantity": 10 + index,
            "price": 30 + index,
            "amount": (10 + index) * (30 + index),
            "commission": 1,
            "realized_pnl": index * 11 if index % 3 == 0 else None,
            "notes": "x" * 500,
        }
        for index in range(30)
    ]
    wrapper = {
        "source": "IBKR + Longbridge",
        "trade_id": "reviewed-trade",
        "review_context": {
            "review_type": "single_trade_review",
            "symbol": "SMCI.US",
            "account_context": {"account_value_at_start": 100000, "cash_ratio_at_start": 0.5, "unused": "y" * 1000},
            "trade_facts": {
                "trades": [
                    {
                        "trade_id": "reviewed-trade",
                        "symbol": "SMCI.US",
                        "date": "2026-05-13",
                        "side": "BUY",
                        "quantity": 40,
                        "price": 32.18,
                        "amount": 1287.2,
                        "commission": 1,
                        "realized_pnl": None,
                    }
                ],
                "related_symbol_trades": related_trades,
                "reviewed_trade_id": "reviewed-trade",
                "is_currently_holding": True,
                "lifecycle_stage": "entry_only_open_position",
                "current_position": {"symbol": "SMCI.US", "quantity": 40, "market_value": 1400, "unrealized_pnl": 112.8},
            },
            "performance_metrics": {
                "single_trade_summary": {"unrealized_pnl": 112.8, "realized_pnl": None, "return_pct": 0.08},
                "post_trade_return_7d": 0.05,
                "benchmark_alpha": "z" * 1000,
            },
            "market_context": {
                "symbol_candles": [{"date": f"2026-05-{index + 1:02d}", "open": 30, "high": 40, "low": 25, "close": 35} for index in range(60)],
                "price_at_first_buy": 32.18,
                "period_high": 40,
                "period_low": 25,
            },
            "external_events": {"pre_entry_events": [{"title": f"news-{index}", "content": "n" * 2000} for index in range(10)]},
            "data_quality": {"warnings": ["Longbridge news API may not provide complete historical news range"]},
        },
    }

    compact = enforce_section_budget("review_context", wrapper, 3000)
    encoded = json.dumps(compact, ensure_ascii=False)
    review_context = compact["review_context"]
    facts = review_context["review_context"]["trade_facts"]

    assert json.loads(encoded)["trade_id"] == "reviewed-trade"
    assert "preview" not in compact
    assert facts["reviewed_trade_id"] == "reviewed-trade"
    assert facts["trades"][0]["side"] == "BUY"
    assert facts["is_currently_holding"] is True
    assert facts["lifecycle_stage"] == "entry_only_open_position"
    assert len(facts["related_symbol_trades"]) <= 8
    assert "symbol_candles" not in review_context["market_context"]
    assert review_context["market_context"]["candles_count"] == 60
    assert compact["truncated"] is True


def test_direct_single_trade_review_context_budget_uses_structured_compaction() -> None:
    payload = {
        "trade_facts": {
            "reviewed_trade_id": "reviewed-trade",
            "trades": [
                {
                    "trade_id": "reviewed-trade",
                    "symbol": "SMCI.US",
                    "date": "2026-05-13",
                    "side": "BUY",
                    "quantity": 40,
                    "price": 32.18,
                    "amount": 1287.2,
                }
            ],
            "related_symbol_trades": [
                {"trade_id": f"trade-{index}", "symbol": "SMCI.US", "date": f"2026-05-{index + 1:02d}", "side": "BUY", "amount": index * 100}
                for index in range(40)
            ],
            "is_currently_holding": True,
        },
        "performance_metrics": {
            "single_trade_summary": {"unrealized_pnl": 112.8, "return_pct": 0.08},
            "raw_commentary": "x" * 4000,
        },
    }

    compact = enforce_section_budget("review_context", payload, 3000)
    encoded = json.dumps(compact, ensure_ascii=False)

    assert json.loads(encoded)["review_type"] == "single_trade_review"
    assert "preview" not in compact
    assert compact["review_context"]["trade_facts"]["reviewed_trade_id"] == "reviewed-trade"
    assert compact["review_context"]["trade_facts"]["trades"][0]["side"] == "BUY"


def test_evidence_pack_schema_fields_are_stable_for_decision_and_daily() -> None:
    decision_pack = build_trade_decision_evidence_pack(
        {
            "decision_type": "entry_decision",
            "symbol": "AAPL.US",
            "account_context": {"top_positions": [{"symbol": "AAPL"}]},
            "data_quality": {},
        }
    )
    daily_pack = build_daily_position_review_evidence_pack({"report_date": "2026-05-16", "overview": {"summary": "ok"}})

    for pack in (decision_pack, daily_pack):
        for key in (
            "agent_name",
            "agent_task",
            "data_sources",
            "facts",
            "derived_metrics",
            "account_context",
            "position_context",
            "trade_history_context",
            "review_context",
            "market_context",
            "company_context",
            "valuation_context",
            "external_events",
            "risk_context",
            "data_quality",
            "budget_report",
            "evidence_used",
        ):
            assert key in pack
    assert daily_pack["daily_position_context"]["overview"]["summary"] == "ok"


@pytest.mark.skip(reason="V2 card architecture - validate_llm_output removed")
def test_trade_decision_output_invariants_normalize_action_confidence_and_target_pct() -> None:
    agent = TradeDecisionAgent(None, None, None)
    payload = valid_decision_payload()
    payload["action"] = "add_batch"
    payload["confidence"] = "high"
    payload["position_advice"] = {
        "current_position_pct": 3,
        "suggested_target_position_pct": 8,
        "max_position_pct": 5,
        "suggested_cash_amount": 0,
        "position_size_label": "small",
    }
    payload["execution_plan"] = {"should_act_now": False, "plan": [], "invalid_conditions": [], "recheck_triggers": []}
    payload["data_limitations"] = ["missing quote", "missing news", "missing valuation", "missing filings"]

    result = agent.validate_llm_output(payload, expected_decision_type="holding_decision")

    assert result["position_advice"]["current_position_pct"] == 0.03
    assert result["position_advice"]["suggested_target_position_pct"] == 0.05
    assert result["overall_score"] == 76
    assert result["rating"] == "positive"
    assert result["action"] == "hold"
    assert result["confidence"] == "medium"
    assert any("capped at max_position_pct" in item for item in result["data_limitations"])


def test_trade_review_output_invariants_fill_missing_dimensions_and_filter_tags() -> None:
    agent = TradeReviewAgent(None, None, None)
    payload = valid_llm_payload()
    payload["score_detail"].pop("exit_quality_score")
    payload["mistake_tags"] = ["SELL_TOO_EARLY", "BAD_TAG"]

    result = agent.validate_llm_output(payload)

    assert result["score_detail"]["exit_quality_score"]["score"] is None
    assert result["score_detail"]["exit_quality_score"]["applicable"] is False
    assert result["mistake_tags"] == ["SELL_TOO_EARLY"]
    # exit_quality excluded: raw=68, applicable_max=85, normalized=68/85*100=80.0
    assert result["overall_score"] == 80.0
    assert result["rating"] == "good"


def test_daily_position_output_invariants_fallback_and_soften_watchlist_language() -> None:
    agent = DailyPositionReviewAgent(None, None, None)
    payload = {
        "report_date": "2026-05-16",
        "summary": "",
        "account_conclusion": "",
        "attribution_summary": "",
        "market_context": "",
        "risk_analysis": "",
        "operation_observation": "",
        "tomorrow_watchlist": [{"symbol": "AMD.US", "conditions": ["必须买入", "立即清仓"]}],
        "data_limitations": [],
        "evidence_used": "tool",
    }

    result = agent.validate_llm_output(payload, expected_report_date="2026-05-16")

    assert result["summary"]
    assert "必须买入" not in json.dumps(result["tomorrow_watchlist"], ensure_ascii=False)
    assert "立即清仓" not in json.dumps(result["tomorrow_watchlist"], ensure_ascii=False)
    assert any("Forceful trading language softened" in item for item in result["data_limitations"])
    assert result["evidence_used"] == ["tool"]


def test_daily_position_output_rejects_report_date_mismatch() -> None:
    agent = DailyPositionReviewAgent(None, None, None)
    with pytest.raises(DailyPositionReviewAgentError):
        agent.validate_llm_output({"report_date": "2026-05-15"}, expected_report_date="2026-05-16")


class HugeObservationLLM:
    def __init__(self) -> None:
        self.calls = 0

    def chat_with_tools(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "huge", "type": "function", "function": {"name": "huge_tool", "arguments": "{}"}},
                ],
            }
        return {"role": "assistant", "content": '{"ok": true}', "tool_calls": []}


def test_runtime_large_observation_returns_valid_json_fallback_and_trace_meta() -> None:
    runtime = ToolCallingRuntime(HugeObservationLLM(), max_observation_chars=500)
    result = runtime.run(
        messages=[{"role": "user", "content": "run"}],
        tools=[
            AgentTool(
                "huge_tool",
                "Huge test tool",
                {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
                lambda: {"items": [{"text": "x" * 2000} for _ in range(3)]},
            )
        ],
    )
    tool_message = next(message for message in result["messages"] if message.get("role") == "tool")
    observation = json.loads(tool_message["content"])
    finish = next(item for item in result["trace"] if item["event"] == "tool_finish")

    assert observation["truncated"] is True
    assert observation["reason"] == "observation exceeded runtime max chars"
    assert finish["observation"]["truncated"] is True
    assert finish["observation"]["original_size"] > finish["observation"]["final_size"]


def test_context_budget_dropped_items_does_not_include_zero_counts() -> None:
    from app.agents.context_budget import build_budget_report

    report = build_budget_report(
        original_size=1000,
        final_size=800,
        dropped_items={"top_positions": 0, "cash_equivalent_positions": 0, "news": 3},
        truncated_fields=[],
    )
    assert "top_positions" not in report["dropped_items"]
    assert "cash_equivalent_positions" not in report["dropped_items"]
    assert report["dropped_items"]["news"] == 3
    assert report["truncated"] is True


def test_context_budget_no_truncated_when_nothing_dropped() -> None:
    from app.agents.context_budget import build_budget_report

    report = build_budget_report(
        original_size=1000,
        final_size=1000,
        dropped_items={"top_positions": 0, "cash_equivalent_positions": 0},
        truncated_fields=[],
    )
    assert report["truncated"] is False


def test_context_budget_limit_list_under_limit_no_dropped_items() -> None:
    from app.agents.context_budget import limit_list

    items = [1, 2, 3]
    result = limit_list(items, 10)
    assert result == [1, 2, 3]
    dropped = len(items) - len(result)
    assert dropped == 0


def test_context_budget_compact_daily_position_context_drops_correctly() -> None:
    from app.agents.context_budget import compact_daily_position_context

    payload = {
        "report_date": "2026-05-16",
        "rankings": {
            "profit_contributors": [{"symbol": f"S{i}", "daily_pnl": i * 10, "daily_change_percent": i} for i in range(10)],
            "loss_drags": [{"symbol": f"L{i}", "daily_pnl": -i * 5, "previous_day_change_percent": -i} for i in range(10)],
            "top_weights": [{"symbol": f"W{i}", "position_pct": 0.01 * i} for i in range(10)],
        },
        "positions": [{"symbol": "X"}] * 30,
        "symbol_public_context": {},
        "data_quality": {"warnings": ["a"] * 15},
    }
    result = compact_daily_position_context(payload)
    assert len(result["rankings"]["profit_contributors"]) == 5
    assert len(result["rankings"]["loss_drags"]) == 5
    assert len(result["rankings"]["top_weights"]) == 5
    assert result["rankings"]["profit_contributors"][1]["daily_change_percent"] == 1
    assert result["rankings"]["loss_drags"][1]["previous_day_change_percent"] == -1


def test_daily_position_context_budget_override_preserves_full_payload_under_limit() -> None:
    long_news = "important context " * 600
    raw = {
        "report_date": "2026-05-16",
        "overview": {"summary": "ok"},
        "rankings": {
            "profit_contributors": [{"symbol": f"P{i}", "daily_pnl": i * 10, "note": "x" * 200} for i in range(10)],
            "loss_drags": [{"symbol": f"L{i}", "daily_pnl": -i * 5, "note": "y" * 200} for i in range(10)],
            "top_weights": [{"symbol": f"W{i}", "position_pct": 0.01 * i, "note": "z" * 200} for i in range(10)],
        },
        "risk": {"risk_flags": ["集中度偏高"]},
        "benchmarks": {},
        "focus_symbols": ["AMD.US"],
        "symbol_public_context": {
            "AMD.US": {
                "news": [{"title": "AMD update", "content": long_news, "summary": long_news}],
                "technical_levels": {"support": 100},
            }
        },
        "data_quality": {"warnings": []},
    }

    compact_default = build_daily_position_review_evidence_pack(raw)
    expanded = build_daily_position_review_evidence_pack(raw, daily_position_context_budget=150000)

    assert compact_default["daily_position_context"]["budget_report"]["truncated"] is True
    daily_context = expanded["daily_position_context"]
    assert daily_context["budget_report"]["truncated"] is False
    assert len(daily_context["rankings"]["profit_contributors"]) == 10
    assert daily_context["symbol_public_context"]["AMD.US"]["news"][0]["content"] == long_news


@pytest.mark.skip(reason="V2 card architecture - evidence_pack replaced by card_pack")
def test_trade_decision_fixed_evidence_pack_saved_not_tool_trace() -> None:
    from tests.test_trade_decision_agent import StubESClient, StubLongbridgeClient, DummySettings, valid_decision_payload
    from app.services.trade_decision_agent import TradeDecisionAgent

    class StubLLMService:
        def get_active_provider(self):
            class P:
                name = "test"
                base_url = "http://test"
                default_model = "test"
            return P()

        def chat(self, messages, **kwargs):
            payload = valid_decision_payload()
            payload["decision_type"] = "entry_decision"
            return json.dumps(payload, ensure_ascii=False)

    class StubRepository:
        def save_decision(self, document: dict) -> dict:
            return {**document, "id": "test-decision"}

    from app.services.trade_decision_evidence import TradeDecisionEvidenceBuilder

    builder = TradeDecisionEvidenceBuilder(StubESClient(), DummySettings(), StubLongbridgeClient())
    agent = TradeDecisionAgent(builder, StubLLMService(), StubRepository())

    result = agent.analyze_entry("AAPL")

    assert "evidence_pack" in result
    assert "agent_name" in result["evidence_pack"], "evidence_pack should contain stable evidence fields, not just tool_trace"
    assert result["evidence_pack"].get("agent_mode") != "tool_calling" or "account_context" in result["evidence_pack"]


def test_trade_review_open_buy_single_trade_protection_normalizes_zero_score() -> None:
    from app.services.trade_review_agent import TradeReviewAgent

    agent = TradeReviewAgent(None, None, None)
    payload = valid_llm_payload()
    payload["review_type"] = "single_trade_review"
    payload["overall_score"] = 0
    payload["score_detail"]["return_result_score"]["score"] = 0
    payload["score_detail"]["relative_performance_score"]["score"] = 0
    payload["score_detail"]["entry_quality_score"]["score"] = 0
    payload["score_detail"]["exit_quality_score"]["score"] = 0
    payload["score_detail"]["position_sizing_score"]["score"] = 0
    payload["score_detail"]["holding_period_score"]["score"] = 0
    payload["score_detail"]["risk_control_score"]["score"] = 0
    payload["score_detail"]["decision_attribution_score"]["score"] = 0
    payload["data_limitations"] = []

    review_context = {
        "review_type": "single_trade_review",
        "trade_facts": {
            "trades": [{"side": "BUY", "symbol": "SMCI.US"}],
            "is_currently_holding": True,
        },
    }

    result = agent.validate_llm_output(payload, review_context=review_context)

    assert result["overall_score"] > 0
    assert any("Open BUY single-trade review normalized" in item for item in result.get("data_limitations") or [])


def test_trade_review_non_open_buy_does_not_trigger_normalization() -> None:
    from app.services.trade_review_agent import TradeReviewAgent

    agent = TradeReviewAgent(None, None, None)
    payload = valid_llm_payload()
    payload["review_type"] = "single_trade_review"
    payload["overall_score"] = 0
    for key in payload["score_detail"]:
        payload["score_detail"][key]["score"] = 0
    payload["data_limitations"] = []

    review_context = {
        "review_type": "single_trade_review",
        "trade_facts": {
            "trades": [{"side": "BUY", "symbol": "SMCI.US"}],
            "is_currently_holding": False,
        },
    }

    result = agent.validate_llm_output(payload, review_context=review_context)

    assert result["overall_score"] == 0
    assert not any("Open BUY" in str(item) for item in result.get("data_limitations") or [])


def test_trade_review_open_buy_single_trade_protection_with_wrapper_review_context() -> None:
    from app.services.trade_review_agent import TradeReviewAgent

    agent = TradeReviewAgent(None, None, None)
    payload = valid_llm_payload()
    payload["review_type"] = "single_trade_review"
    payload["overall_score"] = 0
    for key in payload["score_detail"]:
        payload["score_detail"][key]["score"] = 0
    payload["data_limitations"] = []

    review_context = {
        "source": "IBKR + Longbridge",
        "trade_id": "xxx",
        "review_context": {
            "review_type": "single_trade_review",
            "trade_facts": {
                "trades": [{"side": "BUY", "symbol": "SMCI.US"}],
                "is_currently_holding": True,
            },
        },
    }

    result = agent.validate_llm_output(payload, review_context=review_context)

    assert result["overall_score"] > 0
    assert any("Open BUY single-trade review normalized" in item for item in result.get("data_limitations") or [])


def test_trade_review_wrapper_non_open_buy_does_not_trigger_warning() -> None:
    from app.services.trade_review_agent import TradeReviewAgent

    agent = TradeReviewAgent(None, None, None)
    payload = valid_llm_payload()
    payload["review_type"] = "single_trade_review"
    payload["overall_score"] = 0
    for key in payload["score_detail"]:
        payload["score_detail"][key]["score"] = 0
    payload["data_limitations"] = []

    review_context = {
        "source": "IBKR + Longbridge",
        "trade_id": "xxx",
        "review_context": {
            "review_type": "single_trade_review",
            "trade_facts": {
                "trades": [{"side": "BUY", "symbol": "SMCI.US"}],
                "is_currently_holding": False,
            },
        },
    }

    result = agent.validate_llm_output(payload, review_context=review_context)

    assert result["overall_score"] == 0
    assert not any("Open BUY" in str(item) for item in result.get("data_limitations") or [])


def test_daily_position_review_validate_receives_deterministic_context() -> None:
    from app.services.daily_position_review_agent import DailyPositionReviewAgent

    agent = DailyPositionReviewAgent(None, None, None)
    payload = {
        "report_date": "2026-05-16",
        "summary": "",
        "account_conclusion": "",
        "attribution_summary": "",
        "market_context": "",
        "risk_analysis": "",
        "operation_observation": "",
        "tomorrow_watchlist": [],
        "data_limitations": [],
        "evidence_used": [],
    }
    det_context = {
        "overview": {"summary": "账户今日上涨 2%"},
        "risk": {"risk_flags": ["集中度偏高"]},
    }

    result = agent.validate_llm_output(payload, expected_report_date="2026-05-16", deterministic_context=det_context)

    assert result["summary"] == "账户今日上涨 2%"
    assert result["risk_analysis"] == "集中度偏高"


def test_daily_position_review_build_review_context_called_once() -> None:
    from app.services.daily_position_review_agent import DailyPositionReviewAgent

    call_count = 0

    class CountingService:
        def build_review_context(self, report_date, **kwargs):
            nonlocal call_count
            call_count += 1
            return {"report_date": report_date, "overview": {"summary": "ok"}}

    class DummyRepository:
        def save_review(self, doc):
            return doc

    agent = DailyPositionReviewAgent(CountingService(), None, DummyRepository())

    class StubLLMService:
        def get_active_provider(self):
            class P:
                name = "test"
                base_url = "http://test"
                default_model = "test"
            return P()

        def chat_with_tools(self, messages, **kwargs):
            return {"role": "assistant", "content": '{"report_date":"2026-05-16","summary":"test","account_conclusion":"","attribution_summary":"","market_context":"","risk_analysis":"","operation_observation":"","tomorrow_watchlist":[],"data_limitations":[],"evidence_used":[]}', "tool_calls": []}

    agent.llm_service = StubLLMService()
    agent.generate_review("2026-05-16")

    assert call_count == 1, f"build_review_context should be called once, got {call_count}"


def test_daily_position_review_tool_handler_rejects_wrong_report_date() -> None:
    from app.services.daily_position_review_agent import DailyPositionReviewAgent

    agent = DailyPositionReviewAgent(None, None, None)
    evidence_pack = {"overview": {"summary": "test"}}
    tools = agent._tools(evidence_pack, "2026-05-16")
    mismatch_result = tools[0].handler("2026-05-15")
    assert "error" in mismatch_result
    assert "report_date mismatch" in mismatch_result["error"]
    match_result = tools[0].handler("2026-05-16")
    assert match_result == evidence_pack


def test_daily_position_review_tool_handler_no_output_budget_section() -> None:
    from app.services.daily_position_review_agent import DailyPositionReviewAgent

    agent = DailyPositionReviewAgent(None, None, None)
    evidence_pack = {"overview": {"summary": "test"}}
    tools = agent._tools(evidence_pack, "2026-05-16")
    assert tools[0].output_budget_section is None, "AgentTool should not set output_budget_section on daily_position_review tool"
    assert tools[0].output_compactor is None, "AgentTool should not set output_compactor on daily_position_review tool"
    from app.agents.context_budget import enforce_section_budget

    payload = {
        "source": "Longbridge",
        "financial_context": {
            "currency": "USD",
            "report_type": "quarterly",
            "period_count": 8,
            "latest_metrics": {"revenue": 100},
            "periods": [
                {
                    "label": f"Q{i}",
                    "fiscal_year": 2024 - i // 4,
                    "fiscal_quarter": (i % 4) + 1,
                    "end_date": f"202{4 - i // 4}-0{(i % 4) * 3 + 1}-01",
                    "content": "x" * 5000,
                    "raw": "y" * 5000,
                    "metrics": {
                        "revenue": 100 + i,
                        "gross_profit": 50 + i,
                        "gross_margin": 0.5,
                        "operating_income": 20 + i,
                        "operating_margin": 0.2,
                        "net_income": 10 + i,
                        "net_margin": 0.1,
                        "eps": 1.5 + i * 0.1,
                        "operating_cash_flow": 30 + i,
                        "free_cash_flow": 25 + i,
                        "cash_and_equivalents": 200 + i * 10,
                        "total_debt": 150,
                        "shareholders_equity": 300,
                        "roe": 0.15,
                        "irrelevant_field": "should_be_removed",
                    },
                }
                for i in range(8)
            ],
        },
        "static_info": {"name_en": "Test Co"},
    }

    result = enforce_section_budget("company_context", payload, budget=5000)

    fc = result["financial_context"]
    assert len(fc["periods"]) == 4, f"Expected 4 periods, got {len(fc['periods'])}"
    assert fc["currency"] == "USD"
    assert fc["report_type"] == "quarterly"
    assert fc["period_count"] == 8
    for period in fc["periods"]:
        assert "content" not in period, "Long text keys should be removed"
        assert "raw" not in period
        assert "irrelevant_field" not in period["metrics"]
        assert "revenue" in period["metrics"]
    # periods[0] is the latest period (latest_metrics = periods[0]["metrics"]),
    # so first 4 items (Q0-Q3 = most recent) should be kept
    labels = [p["label"] for p in fc["periods"]]
    assert labels == ["Q0", "Q1", "Q2", "Q3"], f"Expected most recent 4 periods Q0-Q3, got {labels}"
