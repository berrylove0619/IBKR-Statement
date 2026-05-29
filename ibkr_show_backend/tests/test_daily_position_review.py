from dataclasses import dataclass
import inspect
import json
from types import SimpleNamespace

import pytest

from app.schemas.longbridge import LongbridgeCandleItem, LongbridgeCandlesResponse, LongbridgeNewsResponse
from app.api.routes.daily_position_review import _run_daily_review_task
from app.services.daily_position_review_agent import DailyPositionReviewAgent, DailyPositionReviewAgentError
from app.services.daily_position_review_service import DailyPositionReviewService
from app.services import daily_position_review_service


@dataclass
class DummySettings:
    es_account_index: str = "account-index"
    es_position_index: str = "position-index"
    es_daily_position_review_index: str = "daily-review-index"


class StubESClient:
    def search(self, index: str, body: dict) -> dict:
        if index == "account-index":
            query_text = str(body.get("query", {}))
            if "range" in query_text:
                return {
                    "hits": {
                        "hits": [
                            {
                                "_source": {
                                    "report_date": "2026-05-15",
                                    "total_equity": 100000,
                                    "cash": 9000,
                                }
                            }
                        ]
                    }
                }
            if "term" in query_text:
                return {
                    "hits": {
                        "hits": [
                            {
                                "_source": {
                                    "account_id": "U1",
                                    "report_date": "2026-05-16",
                                    "currency": "USD",
                                    "total_equity": 101000,
                                    "cash": 10000,
                                    "stock_value": 81000,
                                    "cnav_mtm": 1000,
                                    "cnav_twr": 1.0,
                                    "cnav_realized": 0,
                                    "cnav_change_in_unrealized": 1000,
                                }
                            }
                        ]
                    }
                }
            return {"hits": {"hits": [{"_source": {"report_date": "2026-05-16"}}]}}
        if index == "position-index":
            return {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "symbol": "AMD",
                                "description": "Advanced Micro Devices",
                                "asset_class": "STK",
                                "quantity": 100,
                                "mark_price": 110,
                                "position_value": 11000,
                                "percent_of_nav": 10.89,
                                "average_cost_price": 80,
                                "cost_basis_money": 8000,
                                "total_unrealized_pnl": 3000,
                                "unrealized_pnl_percent": 37.5,
                                "previous_day_change_percent": 10,
                            }
                        },
                        {
                            "_source": {
                                "symbol": "NVDA",
                                "description": "NVIDIA",
                                "asset_class": "STK",
                                "quantity": 10,
                                "mark_price": 90,
                                "position_value": 900,
                                "percent_of_nav": 0.89,
                                "average_cost_price": 120,
                                "cost_basis_money": 1200,
                                "total_unrealized_pnl": -300,
                                "unrealized_pnl_percent": -25,
                                "previous_day_change_percent": -10,
                            }
                        },
                    ]
                }
            }
        return {"hits": {"hits": []}}


class StubLongbridgeClient:
    def get_candles(self, symbol: str, start: str, end: str, period: str, adjust_type: str) -> LongbridgeCandlesResponse:
        return LongbridgeCandlesResponse(
            symbol=symbol,
            start=start,
            end=end,
            period=period,
            items=[
                LongbridgeCandleItem(date=start, open=100, high=105, low=95, close=100, volume=1000, turnover=100000),
                LongbridgeCandleItem(date=end, open=110, high=115, low=105, close=110, volume=2000, turnover=220000),
            ],
        )

    def get_quote_snapshot(self, symbol: str) -> dict:
        return {"symbol": symbol, "last_done": 110, "volume": 2000}

    def get_static_info(self, symbol: str) -> dict:
        return {"symbol": symbol, "name_en": symbol, "industry": "Semiconductors"}

    def get_calc_indexes(self, symbol: str) -> dict:
        return {"symbol": symbol, "pe_ttm_ratio": 30, "total_market_value": 1000000000}

    def get_news(self, symbol: str, limit: int) -> LongbridgeNewsResponse:
        return LongbridgeNewsResponse(symbol=symbol, items=[])

    def get_filings(self, symbol: str, limit: int = 5) -> list[dict]:
        return [{"title": "10-Q", "released_at": "2026-05-01"}]

    def get_topics(self, symbol: str, limit: int = 5) -> list[dict]:
        return [{"title": "AI demand"}]


def test_daily_position_review_calculates_position_attribution_from_ibkr_positions() -> None:
    service = DailyPositionReviewService(StubESClient(), DummySettings(), StubLongbridgeClient())

    context = service.build_review_context("2026-05-16", include_public_context=True)

    assert context["data_sources"]["account_data"] == "IBKR_ONLY"
    assert context["data_sources"]["public_market_data"] == "LONGBRIDGE_PUBLIC_ONLY"
    assert context["overview"]["daily_pnl"] == 1000
    assert context["overview"]["daily_return_percent"] == 1.0
    amd = next(item for item in context["positions"] if item["symbol"] == "AMD")
    nvda = next(item for item in context["positions"] if item["symbol"] == "NVDA")
    assert amd["daily_pnl"] == pytest.approx(1000)
    assert amd["contribution_ratio"] == pytest.approx(1.0)
    assert nvda["daily_pnl"] == pytest.approx(-100)
    assert nvda["contribution_ratio"] == pytest.approx(-0.1)
    assert context["rankings"]["profit_contributors"][0]["symbol"] == "AMD"
    assert context["rankings"]["loss_drags"][0]["symbol"] == "NVDA"
    assert context["risk"]["max_position"]["symbol"] == "AMD"
    assert context["attribution_quality"]["unexplained_pnl"] == pytest.approx(100)
    assert "tuple" not in " ".join(context["data_quality"]["warnings"])
    assert context["symbol_public_context"]["AMD.US"]["news"] == []


def test_daily_position_review_service_does_not_reference_longbridge_account_or_trade_apis() -> None:
    source = inspect.getsource(daily_position_review_service)
    forbidden = ["TradeContext", "AsyncTradeContext", "submit_order", "stock_positions", "executions"]
    for token in forbidden:
        assert token not in source


def test_daily_position_review_agent_validation_requires_matching_report_date() -> None:
    agent = DailyPositionReviewAgent(None, None, None)
    payload = {
        "report_date": "2026-05-16",
        "summary": "ok",
        "account_conclusion": "ok",
        "attribution_summary": "ok",
        "market_context": "ok",
        "risk_analysis": "ok",
        "operation_observation": "ok",
        "major_contributors_analysis": [],
        "major_drags_analysis": [],
        "focus_symbol_analyses": [],
        "tomorrow_watchlist": [],
        "data_limitations": [],
        "evidence_used": [],
    }

    assert agent.validate_llm_output(payload, expected_report_date="2026-05-16")["summary"] == "ok"
    with pytest.raises(DailyPositionReviewAgentError):
        agent.validate_llm_output({**payload, "report_date": "2026-05-15"}, expected_report_date="2026-05-16")


def test_daily_position_review_agent_builds_fallback_payload_when_llm_json_is_invalid() -> None:
    service = DailyPositionReviewService(StubESClient(), DummySettings(), StubLongbridgeClient())
    context = service.build_review_context("2026-05-16")
    agent = DailyPositionReviewAgent(None, None, None)

    payload = agent._build_fallback_review_payload(
        report_date="2026-05-16",
        context=context,
        parse_error="LLM output could not be parsed after repair: LLM response is not valid JSON",
    )

    assert payload["report_date"] == "2026-05-16"
    assert payload["summary"]
    assert "LLM output could not be parsed" in payload["data_limitations"][0]
    assert payload["major_contributors_analysis"][0]["symbol"] == "AMD"
    assert payload["major_drags_analysis"][0]["symbol"] == "NVDA"


def test_daily_position_review_uses_active_provider_token_profile_for_budget() -> None:
    class TokenProfileLLMService:
        def get_active_provider(self):
            return SimpleNamespace(input_token_limit=150000, output_token_limit=10000)

    agent = DailyPositionReviewAgent(None, TokenProfileLLMService(), None)

    assert agent._active_token_budget() == (150000, 10000)


def _valid_daily_review_payload(report_date: str = "2026-05-16") -> dict:
    return {
        "report_date": report_date,
        "summary": "ok",
        "account_conclusion": "ok",
        "attribution_summary": "ok",
        "market_context": "ok",
        "risk_analysis": "ok",
        "operation_observation": "ok",
        "major_contributors_analysis": [],
        "major_drags_analysis": [],
        "focus_symbol_analyses": [],
        "tomorrow_watchlist": [],
        "data_limitations": [],
        "evidence_used": [],
    }


class RepairLLMService:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    def chat(self, messages: list[dict], **kwargs) -> str:
        self.prompts.append(str(messages[-1]["content"]))
        return self.responses.pop(0)


def test_daily_position_review_repair_retries_with_report_date_validation_error() -> None:
    fixed_payload = _valid_daily_review_payload()
    llm_service = RepairLLMService([json.dumps(fixed_payload)])
    agent = DailyPositionReviewAgent(None, llm_service, None)
    invalid_payload = {**fixed_payload, "report_date": "2026-05-15"}

    validated, raw_response, error = agent._validate_or_repair_llm_response(
        report_date="2026-05-16",
        raw_response=json.dumps(invalid_payload),
        trace=[],
    )

    assert error is None
    assert validated["summary"] == "ok"
    assert len(llm_service.prompts) == 1
    assert "report_date does not match request" in llm_service.prompts[0]
    assert "第 1/3 次修复" in llm_service.prompts[0]
    assert "repair_attempt_1_for_LLM_SCHEMA_INVALID" in raw_response


def test_daily_position_review_uses_fallback_when_summary_is_empty() -> None:
    payload = _valid_daily_review_payload()
    invalid_payload = {key: value for key, value in payload.items() if key != "summary"}
    agent = DailyPositionReviewAgent(None, None, None)

    validated = agent.validate_llm_output(invalid_payload, expected_report_date="2026-05-16")

    assert validated["summary"]
    assert "summary was filled from deterministic fallback" in validated["data_limitations"]


def test_daily_position_review_repair_stops_after_three_failed_report_date_attempts() -> None:
    payload = _valid_daily_review_payload()
    invalid_payload = {**payload, "report_date": "2026-05-15"}
    llm_service = RepairLLMService([json.dumps(invalid_payload), json.dumps(invalid_payload), json.dumps(invalid_payload)])
    agent = DailyPositionReviewAgent(None, llm_service, None)

    validated, raw_response, error = agent._validate_or_repair_llm_response(
        report_date="2026-05-16",
        raw_response=json.dumps(invalid_payload),
        trace=[],
    )

    assert validated is None
    assert error is not None
    assert error.message == "report_date does not match request"
    assert len(llm_service.prompts) == 3
    assert "第 3/3 次修复" in llm_service.prompts[-1]
    assert "repair_attempt_3_for_LLM_SCHEMA_INVALID" in raw_response


class StubTaskRepository:
    def __init__(self, auto_email: bool) -> None:
        self.task = {
            "id": "task-1",
            "agent": "daily_position_review",
            "task_type": "daily_position_review",
            "payload": {"report_date": "2026-05-16", "force_refresh": True, "auto_email": auto_email},
            "status": "queued",
        }
        self.completed = False
        self.failed = False

    def mark_running(self, task_id: str) -> dict:
        self.task["status"] = "running"
        return self.task

    def mark_completed(self, task_id: str, *, result_id: str) -> dict:
        self.completed = True
        self.task.update({"status": "completed", "result_id": result_id})
        return self.task

    def mark_failed(self, task_id: str, *, error_code: str, error_message: str) -> dict:
        self.failed = True
        self.task.update({"status": "failed", "error_code": error_code, "error_message": error_message})
        return self.task


class StubDailyReviewAgent:
    def generate_review(self, report_date: str) -> dict:
        return {"id": "review-1", "report_date": report_date}


class StubEmailService:
    def __init__(self, should_raise: bool = False) -> None:
        self.should_raise = should_raise
        self.documents: list[dict] = []

    def send_daily_position_review(self, document: dict) -> bool:
        self.documents.append(document)
        if self.should_raise:
            raise RuntimeError("smtp down")
        return True


def test_daily_position_review_task_sends_email_when_auto_email_enabled() -> None:
    repository = StubTaskRepository(auto_email=True)
    email_service = StubEmailService()

    _run_daily_review_task("task-1", repository, StubDailyReviewAgent(), email_service)

    assert repository.completed is True
    assert repository.failed is False
    assert email_service.documents == [{"id": "review-1", "report_date": "2026-05-16"}]


def test_daily_position_review_task_stays_completed_when_email_fails() -> None:
    repository = StubTaskRepository(auto_email=True)
    email_service = StubEmailService(should_raise=True)

    _run_daily_review_task("task-1", repository, StubDailyReviewAgent(), email_service)

    assert repository.completed is True
    assert repository.failed is False
    assert repository.task["status"] == "completed"


def test_daily_position_review_task_does_not_send_email_when_auto_email_disabled() -> None:
    repository = StubTaskRepository(auto_email=False)
    email_service = StubEmailService()

    _run_daily_review_task("task-1", repository, StubDailyReviewAgent(), email_service)

    assert repository.completed is True
    assert email_service.documents == []
