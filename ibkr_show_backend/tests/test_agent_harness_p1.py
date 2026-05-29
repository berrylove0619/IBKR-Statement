"""
Tests for P1 Agent Harness fixes:
1. TradeReviewAgent._run_tool_agent writes metadata/evidence_summary/run_trace_summary
2. evidence_summary sanitization
3. DailyPositionReviewAgent agent_mode = fixed_evidence_with_single_tool
"""

import pytest
from unittest.mock import MagicMock, patch

from app.agents.evidence_summary import (
    _sanitize_text,
    _sanitize_value,
    build_evidence_summary,
)
from app.agents.versions import AGENT_MODE_FIXED_EVIDENCE_WITH_SINGLE_TOOL


class TestEvidenceSummarySanitization:
    """Issue 2: SENSITIVE_KEYS and _is_sensitive_key are defined but not used."""

    def test_sanitize_text_replaces_token(self):
        assert _sanitize_text("token=my-secret-token") == "token=[REDACTED]"
        assert _sanitize_text("token:my-secret-token") == "token=[REDACTED]"

    def test_sanitize_text_replaces_api_key(self):
        assert _sanitize_text("api_key=abc123") == "api_key=[REDACTED]"
        assert _sanitize_text("api_key:abc123") == "api_key=[REDACTED]"

    def test_sanitize_text_replaces_password(self):
        assert _sanitize_text("password=qwer5637") == "password=[REDACTED]"
        assert _sanitize_text("password:secret") == "password=[REDACTED]"

    def test_sanitize_text_replaces_authorization_bearer_eq(self):
        result = _sanitize_text("authorization=Bearer secret-token")
        assert "secret-token" not in result
        assert "Bearer secret-token" not in result
        assert result == "authorization=[REDACTED]"

    def test_sanitize_text_replaces_authorization_bearer_colon(self):
        result = _sanitize_text("authorization: Bearer secret-token")
        assert "secret-token" not in result
        assert "Bearer secret-token" not in result
        assert result == "authorization=[REDACTED]"

    def test_sanitize_text_replaces_authorization_bearer_jwt(self):
        result = _sanitize_text("Authorization: Bearer abc.def.ghi")
        assert "abc.def.ghi" not in result
        assert "Bearer abc.def.ghi" not in result
        assert result == "authorization=[REDACTED]"

    def test_sanitize_text_replaces_bearer_standalone(self):
        result = _sanitize_text("Bearer standalone-token")
        assert "standalone-token" not in result
        assert result == "Bearer [REDACTED]"

    def test_sanitize_text_replaces_authorization_plain_token(self):
        result = _sanitize_text("authorization=token-xyz")
        assert "token-xyz" not in result
        assert result == "authorization=[REDACTED]"

    def test_sanitize_text_replaces_bearer(self):
        result = _sanitize_text("Bearer secret-token-here")
        assert "secret-token-here" not in result

    def test_sanitize_text_replaces_smtp_password(self):
        assert _sanitize_text("smtp_password=smtp-secret") == "smtp_password=[REDACTED]"

    def test_sanitize_text_replaces_access_token(self):
        assert _sanitize_text("access_token=access-xyz") == "access_token=[REDACTED]"

    def test_sanitize_text_replaces_refresh_token(self):
        assert _sanitize_text("refresh_token=refresh-xyz") == "refresh_token=[REDACTED]"

    def test_sanitize_text_replaces_flex_token(self):
        assert _sanitize_text("flex_token=flex-xyz") == "flex_token=[REDACTED]"

    def test_sanitize_text_preserves_normal_text(self):
        assert _sanitize_text("This is normal text") == "This is normal text"
        assert _sanitize_text("symbol=AMD.US cash=10000") == "symbol=AMD.US cash=10000"

    def test_sanitize_text_non_string_passthrough(self):
        assert _sanitize_text(123) == 123
        assert _sanitize_text(None) is None

    def test_sanitize_value_dict_redacts_sensitive_keys(self):
        d = {"api_key": "secret123", "symbol": "AMD.US", "token": "tok123"}
        result = _sanitize_value(d)
        assert result["api_key"] == "[REDACTED]"
        assert result["symbol"] == "AMD.US"
        assert result["token"] == "[REDACTED]"

    def test_sanitize_value_list_recursively(self):
        lst = ["token=abc", "password=xyz", "normal"]
        result = _sanitize_value(lst)
        assert result == ["token=[REDACTED]", "password=[REDACTED]", "normal"]

    def test_sanitize_value_nested(self):
        d = {
            "data": {
                "api_key": "secret",
                "nested": {"password": "pw", "symbol": "NVDA.US"},
            },
            "top_token": "tok123",
        }
        result = _sanitize_value(d)
        assert result["data"]["api_key"] == "[REDACTED]"
        assert result["data"]["nested"]["password"] == "[REDACTED]"
        assert result["data"]["nested"]["symbol"] == "NVDA.US"
        assert result["top_token"] == "[REDACTED]"

    def test_evidence_pack_with_api_key_not_exposed_in_summary(self):
        evidence = {
            "account_context": {
                "data": {"cash": 10000},
                "data_limitations": ["api_key=abc123 is missing"],
            }
        }
        result = build_evidence_summary(evidence)
        result_str = str(result)
        assert "abc123" not in result_str
        assert "api_key=[REDACTED]" in result_str

    def test_run_trace_authorization_bearer_not_exposed(self):
        evidence = {}
        run_trace = [
            {
                "event": "tool_finish",
                "tool": "get_account",
                "ok": True,
                "summary": "request failed with Authorization: Bearer secret-token",
                "observation": {},
            }
        ]
        result = build_evidence_summary(evidence, run_trace)
        result_str = str(result)
        assert "secret-token" not in result_str
        assert "Bearer secret-token" not in result_str
        assert "[REDACTED]" in result["tools_used"][0]["summary"]

    def test_smtp_password_not_exposed_in_summary(self):
        evidence = {
            "review_context": {
                "smtp_password": "email-secret",
                "symbol": "AMD.US",
            }
        }
        result = build_evidence_summary(evidence)
        result_str = str(result)
        assert "email-secret" not in result_str
        # smtp_password key is sanitized to [REDACTED] value
        assert result["evidence_sections"][3]["item_count"] == 2

    def test_raw_sensitive_data_exposed_still_false(self):
        evidence = {"account_context": {"api_key": "secret123", "data": {}}}
        result = build_evidence_summary(evidence)
        assert result["llm_input_policy"]["raw_sensitive_data_exposed"] is False

    def test_non_string_types_preserved(self):
        evidence = {
            "account_context": {
                "data": {"cash": 10000, "positions": []},
                "budget_report": {"original_size": 5000, "truncated": False},
            }
        }
        result = build_evidence_summary(evidence)
        assert result["budget_summary"]["total_original_size"] == 5000
        assert isinstance(result["budget_summary"]["total_original_size"], int)


class TestTradeReviewAgentToolAgentMetadata:
    """TradeReviewAgent now uses LangGraph runner. Verify metadata/evidence_summary/run_trace_summary."""

    def test_run_tool_agent_saves_metadata(self):
        from app.services.trade_review_agent import TradeReviewAgent

        mock_evidence_builder = MagicMock()
        mock_llm = MagicMock()
        mock_repo = MagicMock()

        agent = TradeReviewAgent(
            evidence_builder=mock_evidence_builder,
            llm_service=mock_llm,
            repository=mock_repo,
        )

        with patch.object(agent, "_get_graph_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.generate_single_trade_review.return_value = {
                "id": "test-trade-123",
                "metadata": {
                    "agent_mode": "trade_review_langgraph_v1",
                    "agent_version": "trade_review_v2",
                    "graph_version": "trade_review_graph_v1",
                },
                "evidence_summary": {},
                "run_trace_summary": {},
            }
            mock_get_runner.return_value = mock_runner
            result = agent.generate_single_trade_review(trade_id="test-trade-123")

        assert "metadata" in result
        assert result["metadata"]["agent_version"] == "trade_review_v2"
        assert result["metadata"]["agent_mode"] == "trade_review_langgraph_v1"

    def test_run_tool_agent_saves_evidence_summary(self):
        from app.services.trade_review_agent import TradeReviewAgent

        mock_evidence_builder = MagicMock()
        mock_llm = MagicMock()
        mock_repo = MagicMock()

        agent = TradeReviewAgent(
            evidence_builder=mock_evidence_builder,
            llm_service=mock_llm,
            repository=mock_repo,
        )

        with patch.object(agent, "_get_graph_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.generate_single_trade_review.return_value = {
                "id": "test-trade-123",
                "metadata": {"agent_mode": "trade_review_langgraph_v1"},
                "evidence_summary": {"llm_input_policy": {"raw_sensitive_data_exposed": False}},
                "run_trace_summary": {},
            }
            mock_get_runner.return_value = mock_runner
            result = agent.generate_single_trade_review(trade_id="test-trade-123")

        assert "evidence_summary" in result
        assert "llm_input_policy" in result["evidence_summary"]
        assert result["evidence_summary"]["llm_input_policy"]["raw_sensitive_data_exposed"] is False

    def test_run_tool_agent_saves_run_trace_summary(self):
        from app.services.trade_review_agent import TradeReviewAgent

        mock_evidence_builder = MagicMock()
        mock_llm = MagicMock()
        mock_repo = MagicMock()

        agent = TradeReviewAgent(
            evidence_builder=mock_evidence_builder,
            llm_service=mock_llm,
            repository=mock_repo,
        )

        with patch.object(agent, "_get_graph_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.generate_single_trade_review.return_value = {
                "id": "test-trade-123",
                "metadata": {"agent_mode": "trade_review_langgraph_v1"},
                "evidence_summary": {},
                "run_trace_summary": {"tool_call_count": 0, "llm_rounds": 1},
            }
            mock_get_runner.return_value = mock_runner
            result = agent.generate_single_trade_review(trade_id="test-trade-123")

        assert "run_trace_summary" in result
        assert "tool_call_count" in result["run_trace_summary"]
        assert "llm_rounds" in result["run_trace_summary"]

    def test_run_tool_agent_metadata_agent_mode_is_langgraph(self):
        from app.services.trade_review_agent import TradeReviewAgent

        mock_evidence_builder = MagicMock()
        mock_llm = MagicMock()
        mock_repo = MagicMock()

        agent = TradeReviewAgent(
            evidence_builder=mock_evidence_builder,
            llm_service=mock_llm,
            repository=mock_repo,
        )

        with patch.object(agent, "_get_graph_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.generate_symbol_review.return_value = {
                "id": "test",
                "metadata": {"agent_mode": "trade_review_langgraph_v1"},
                "evidence_summary": {},
                "run_trace_summary": {},
            }
            mock_get_runner.return_value = mock_runner
            result = agent.generate_symbol_review(symbol="AMD.US", start_date="2025-01-01", end_date="2025-12-31")

        assert result["metadata"]["agent_mode"] == "trade_review_langgraph_v1"

    def test_symbol_review_also_saves_p1_fields(self):
        from app.services.trade_review_agent import TradeReviewAgent

        mock_evidence_builder = MagicMock()
        mock_llm = MagicMock()
        mock_repo = MagicMock()

        agent = TradeReviewAgent(
            evidence_builder=mock_evidence_builder,
            llm_service=mock_llm,
            repository=mock_repo,
        )

        with patch.object(agent, "_get_graph_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.generate_symbol_review.return_value = {
                "id": "test",
                "metadata": {
                    "agent_mode": "trade_review_langgraph_v1",
                    "agent_version": "trade_review_v2",
                    "graph_version": "trade_review_graph_v1",
                },
                "evidence_summary": {"llm_input_policy": {}},
                "run_trace_summary": {"tool_call_count": 0, "llm_rounds": 1},
            }
            mock_get_runner.return_value = mock_runner
            result = agent.generate_symbol_review(symbol="NVDA.US", start_date="2025-01-01", end_date="2025-12-31")

        assert "metadata" in result
        assert "evidence_summary" in result
        assert "run_trace_summary" in result
        assert result["metadata"]["agent_mode"] == "trade_review_langgraph_v1"
        assert result["metadata"]["agent_version"] == "trade_review_v2"


class TestDailyPositionReviewAgentMode:
    """Issue 3: DailyPositionReviewAgent now uses LangGraph runner."""

    def test_daily_review_generates_with_correct_agent_mode(self):
        from app.services.daily_position_review_agent import DailyPositionReviewAgent

        mock_service = MagicMock()
        mock_llm = MagicMock()
        mock_repo = MagicMock()

        agent = DailyPositionReviewAgent(
            review_service=mock_service,
            llm_service=mock_llm,
            repository=mock_repo,
        )

        mock_provider = MagicMock()
        mock_provider.name = "test"
        mock_provider.base_url = "https://test.com"
        mock_provider.default_model = "test"
        mock_provider.context_window_tokens = 200000
        mock_provider.input_token_limit = 150000
        mock_provider.output_token_limit = 10000
        mock_llm.get_active_provider.return_value = mock_provider

        # Mock the graph runner
        with patch.object(agent, "_get_graph_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.generate_review.return_value = {
                "id": "2025-01-01",
                "report_date": "2025-01-01",
                "metadata": {
                    "agent_mode": "daily_position_review_langgraph_v1",
                    "agent_version": "daily_position_review_v2",
                    "graph_version": "daily_position_review_graph_v1",
                },
            }
            mock_get_runner.return_value = mock_runner
            result = agent.generate_review(report_date="2025-01-01")

        assert result["metadata"]["agent_mode"] == "daily_position_review_langgraph_v1"
        assert result["metadata"]["agent_version"] == "daily_position_review_v2"
