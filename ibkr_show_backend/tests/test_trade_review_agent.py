from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.api.routes.trade_review_agent import _single_trade_task_metadata
from app.main import app
from app.schemas.longbridge import LongbridgeCandleItem, LongbridgeCandlesResponse, LongbridgeNewsResponse
from app.services.trade_review_agent import TradeReviewAgent, TradeReviewAgentError, extract_json_object, rating_for_score
from app.services.trade_review_evidence import TradeReviewEvidenceBuilder
from app.services.trade_review_scoring import TradeReviewMetricsCalculator

client = TestClient(app)


@dataclass
class DummySettings:
    es_trade_index: str = "trade-index"
    es_position_index: str = "position-index"
    es_account_index: str = "account-index"


class StubESClient:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)

    def search(self, index: str, body: dict) -> dict:
        return self.responses.pop(0)


class StubLongbridgeClient:
    def get_candles(self, symbol: str, start: str, end: str, period: str, adjust_type: str) -> LongbridgeCandlesResponse:
        return LongbridgeCandlesResponse(
            symbol=symbol,
            start=start,
            end=end,
            period=period,
            items=[
                LongbridgeCandleItem(date=start, open=100, high=110, low=95, close=100, volume=1000, turnover=100000),
                LongbridgeCandleItem(date=end, open=120, high=130, low=115, close=120, volume=1000, turnover=120000),
            ],
        )

    def get_news(self, symbol: str, limit: int) -> LongbridgeNewsResponse:
        return LongbridgeNewsResponse(symbol=symbol, items=[])


class StubEvidenceBuilder:
    def tool_get_single_trade(self, trade_id: str) -> dict:
        return {"symbol": "SMCI.US", "trade": {"trade_id": trade_id, "symbol": "SMCI.US"}}


def valid_llm_payload() -> dict:
    return {
        "symbol": "AAPL.US",
        "review_type": "symbol_level_review",
        "overall_score": 80,
        "rating": "good",
        "score_detail": {
            "return_result_score": {"score": 18, "max_score": 20, "reason": "ok"},
            "relative_performance_score": {"score": 12, "max_score": 15, "reason": "ok"},
            "entry_quality_score": {"score": 11, "max_score": 15, "reason": "ok"},
            "exit_quality_score": {"score": 8, "max_score": 15, "reason": "ok"},
            "position_sizing_score": {"score": 9, "max_score": 15, "reason": "ok"},
            "holding_period_score": {"score": 4, "max_score": 5, "reason": "ok"},
            "risk_control_score": {"score": 9, "max_score": 10, "reason": "ok"},
            "decision_attribution_score": {"score": 5, "max_score": 5, "reason": "ok"},
        },
        "summary": "核心结论",
        "strengths": [],
        "weaknesses": [],
        "mistake_tags": ["SELL_TOO_EARLY"],
        "improvement_suggestions": [],
        "data_limitations": [],
        "evidence_used": [],
    }


def test_score_validation_rejects_scores_above_max() -> None:
    agent = TradeReviewAgent(None, None, None)
    payload = valid_llm_payload()
    payload["score_detail"]["return_result_score"]["score"] = 21

    with pytest.raises(TradeReviewAgentError):
        agent.validate_llm_output(payload)


def test_score_validation_normalizes_rating_from_total_score() -> None:
    agent = TradeReviewAgent(None, None, None)
    payload = agent.validate_llm_output(valid_llm_payload())

    # exit_quality excluded (no sell trades): raw=68, applicable_max=85, normalized=80.0
    assert payload["overall_score"] == 80.0
    assert payload["rating"] == "good"
    assert rating_for_score(49) == "poor"
    assert rating_for_score(85) == "excellent"


def test_mistake_tags_validation_filters_unknown_tags() -> None:
    agent = TradeReviewAgent(None, None, None)
    payload = valid_llm_payload()
    payload["mistake_tags"] = ["SELL_TOO_EARLY", "NOT_A_TAG"]

    validated = agent.validate_llm_output(payload)

    assert validated["mistake_tags"] == ["SELL_TOO_EARLY"]
    assert "Unknown mistake tags filtered: NOT_A_TAG" in validated["data_limitations"]


def test_benchmark_return_calculation() -> None:
    calculator = TradeReviewMetricsCalculator()
    candles = [
        {"date": "2025-01-02", "close": 100},
        {"date": "2025-01-31", "close": 125},
    ]

    assert calculator.calculate_benchmark_return(candles, "2025-01-01", "2025-01-31") == 0.25


def test_post_trade_return_calculation() -> None:
    calculator = TradeReviewMetricsCalculator()
    candles = [
        {"date": "2025-01-02", "close": 100},
        {"date": "2025-01-09", "close": 110},
        {"date": "2025-02-03", "close": 130},
        {"date": "2025-04-02", "close": 90},
    ]

    assert calculator.calculate_post_trade_returns(candles, "2025-01-02") == {
        "7d": 0.1,
        "30d": 0.3,
        "90d": -0.1,
    }


def test_json_parse_handles_plain_and_markdown_json() -> None:
    raw = '{"summary":"ok"}'
    markdown = '```json\n{"summary":"ok"}\n```'

    assert extract_json_object(raw)["summary"] == "ok"
    assert extract_json_object(markdown)["summary"] == "ok"


def test_single_trade_task_label_includes_symbol() -> None:
    agent = TradeReviewAgent(StubEvidenceBuilder(), None, None)

    label, payload = _single_trade_task_metadata(agent, "9497082631")

    assert label == "SMCI.US 9497082631 单笔交易复盘"
    assert payload == {"trade_id": "9497082631", "symbol": "SMCI.US"}


def test_symbol_level_evidence_contains_required_sections() -> None:
    es_client = StubESClient(
        [
            {
                "hits": {
                    "hits": [
                        {
                            "_id": "doc-1",
                            "_source": {
                                "account_id": "U1",
                                "symbol": "AAPL",
                                "trade_date": "2025-01-02",
                                "buy_sell": "BUY",
                                "quantity": 10,
                                "trade_price": 100,
                                "proceeds": -1000,
                                "currency": "USD",
                            },
                        }
                    ]
                }
            },
            {
                "hits": {
                    "hits": [
                        {
                            "_id": "doc-1",
                            "_source": {
                                "account_id": "U1",
                                "symbol": "AAPL",
                                "trade_date": "2025-01-02",
                                "buy_sell": "BUY",
                                "quantity": 10,
                                "trade_price": 100,
                                "proceeds": -1000,
                                "currency": "USD",
                            },
                        }
                    ]
                }
            },
            {
                "hits": {
                    "hits": [
                        {
                            "_id": "doc-1",
                            "_source": {
                                "account_id": "U1",
                                "symbol": "AAPL",
                                "trade_date": "2025-01-02",
                                "buy_sell": "BUY",
                                "quantity": 10,
                                "trade_price": 100,
                                "proceeds": -1000,
                                "currency": "USD",
                            },
                        }
                    ]
                }
            },
            {"hits": {"hits": []}},
            {"hits": {"hits": []}},
            {"hits": {"hits": []}},
            {"hits": {"hits": []}},
        ]
    )
    builder = TradeReviewEvidenceBuilder(es_client, DummySettings(), StubLongbridgeClient())

    evidence = builder.build_symbol_review_evidence("AAPL")

    assert evidence["review_type"] == "symbol_level_review"
    assert evidence["symbol"] == "AAPL.US"
    assert evidence["trade_facts"]["trades"][0]["trade_id"] == "doc-1"
    assert "performance_metrics" in evidence


def test_single_trade_evidence_contains_reviewed_trade_id() -> None:
    es_client = StubESClient(
        [
            {
                "hits": {
                    "hits": [
                        {
                            "_id": "doc-1",
                            "_source": {
                                "account_id": "U1",
                                "symbol": "AAPL",
                                "trade_date": "2025-01-02",
                                "buy_sell": "BUY",
                                "quantity": 10,
                                "trade_price": 100,
                                "proceeds": -1000,
                                "currency": "USD",
                            },
                        }
                    ]
                }
            },
            {
                "hits": {
                    "hits": [
                        {
                            "_id": "doc-1",
                            "_source": {
                                "account_id": "U1",
                                "symbol": "AAPL",
                                "trade_date": "2025-01-02",
                                "buy_sell": "BUY",
                                "quantity": 10,
                                "trade_price": 100,
                                "proceeds": -1000,
                                "currency": "USD",
                            },
                        }
                    ]
                }
            },
            {"hits": {"hits": []}},
            {"hits": {"hits": []}},
            {"hits": {"hits": []}},
            {"hits": {"hits": []}},
        ]
    )
    builder = TradeReviewEvidenceBuilder(es_client, DummySettings(), StubLongbridgeClient())

    evidence = builder.build_single_trade_review_evidence("doc-1")

    assert evidence["review_type"] == "single_trade_review"
    assert evidence["trade_facts"]["reviewed_trade_id"] == "doc-1"
    assert evidence["trade_facts"]["lifecycle_stage"] == "entry_without_detected_position"
    assert evidence["trade_facts"]["related_symbol_trades"][0]["trade_id"] == "doc-1"
    assert "single_trade_summary" in evidence["performance_metrics"]


def test_single_buy_evidence_marks_open_position_as_reviewable_entry() -> None:
    es_client = StubESClient(
        [
            {
                "hits": {
                    "hits": [
                        {
                            "_id": "doc-1",
                            "_source": {
                                "account_id": "U1",
                                "symbol": "SMCI",
                                "trade_date": "2026-05-13",
                                "buy_sell": "BUY",
                                "quantity": 40,
                                "trade_price": 32.18,
                                "proceeds": -1287.2,
                                "currency": "USD",
                            },
                        }
                    ]
                }
            },
            {
                "hits": {
                    "hits": [
                        {
                            "_id": "doc-1",
                            "_source": {
                                "account_id": "U1",
                                "symbol": "SMCI",
                                "trade_date": "2026-05-13",
                                "buy_sell": "BUY",
                                "quantity": 40,
                                "trade_price": 32.18,
                                "proceeds": -1287.2,
                                "currency": "USD",
                            },
                        }
                    ]
                }
            },
            {"hits": {"hits": [{"_source": {"report_date": "2026-05-16"}}]}},
            {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "account_id": "U1",
                                "report_date": "2026-05-16",
                                "symbol": "SMCI",
                                "quantity": 40,
                                "mark_price": 35,
                                "position_value": 1400,
                                "total_unrealized_pnl": 112.8,
                            }
                        }
                    ]
                }
            },
            {"hits": {"hits": [{"_source": {"total_equity": 100000}}]}},
            {"hits": {"hits": [{"_source": {"total_equity": 101000}}]}},
            {"hits": {"hits": [{"_source": {"cash": 50000, "total_equity": 100000}}]}},
        ]
    )
    builder = TradeReviewEvidenceBuilder(es_client, DummySettings(), StubLongbridgeClient())

    evidence = builder.build_single_trade_review_evidence("doc-1")

    assert evidence["trade_facts"]["lifecycle_stage"] == "entry_only_open_position"
    assert evidence["trade_facts"]["is_currently_holding"] is True
    assert evidence["performance_metrics"]["single_trade_summary"]["unrealized_pnl"] == 112.8


def test_trade_review_generate_requires_login() -> None:
    response = client.post("/api/agent/trade-review/symbol/AAPL/generate", json={})

    assert response.status_code == 401
