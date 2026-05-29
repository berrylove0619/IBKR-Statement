"""Tests for summarize_trace_for_progress inference logic."""

from __future__ import annotations

from app.agents.graph.progress import summarize_trace_for_progress


class TestSummarizeTraceForProgress:
    def test_top_level_rounds_used(self):
        trace = {"rounds_used": 2, "status": "success"}
        result = summarize_trace_for_progress(trace)
        assert result["rounds_used"] == 2

    def test_infer_rounds_from_runtime_trace(self):
        trace = {
            "status": "success",
            "runtime_trace": [
                {"event": "llm_start", "round": 1},
                {"event": "llm_finish", "round": 1},
            ],
        }
        result = summarize_trace_for_progress(trace)
        assert result["rounds_used"] == 1

    def test_infer_multi_rounds_from_runtime_trace(self):
        trace = {
            "status": "success",
            "runtime_trace": [
                {"event": "llm_start", "round": 1},
                {"event": "llm_finish", "round": 1},
                {"event": "tool_start", "tool": "quote"},
                {"event": "tool_finish", "tool": "quote", "ok": True},
                {"event": "llm_start", "round": 2},
                {"event": "llm_finish", "round": 2},
                {"event": "final"},
            ],
        }
        result = summarize_trace_for_progress(trace)
        assert result["rounds_used"] == 2

    def test_tool_calls_no_double_count(self):
        trace = {
            "status": "success",
            "runtime_trace": [
                {"event": "tool_start", "tool": "quote", "tool_call_id": "tc1"},
                {"event": "tool_finish", "tool": "quote", "tool_call_id": "tc1", "ok": True},
            ],
        }
        result = summarize_trace_for_progress(trace)
        assert result["tool_call_count"] == 1
        assert "quote" in result["tools_called"]

    def test_tool_error_shows_failure(self):
        trace = {
            "status": "success",
            "runtime_trace": [
                {"event": "tool_start", "tool": "news_search"},
                {"event": "tool_error", "tool": "news_search", "error": "timeout"},
            ],
        }
        result = summarize_trace_for_progress(trace)
        assert result["tool_call_count"] == 1
        assert result["tool_calls"][0]["success"] is False

    def test_top_level_tool_calls_take_priority(self):
        trace = {
            "status": "success",
            "tools_called": ["ibkr_get_position", "ibkr_get_account"],
            "tool_calls": [
                {"tool_name": "ibkr_get_position", "success": True},
                {"tool_name": "ibkr_get_account", "success": True},
            ],
            "runtime_trace": [
                {"event": "tool_finish", "tool": "other_tool", "ok": True},
            ],
        }
        result = summarize_trace_for_progress(trace)
        assert result["tool_call_count"] == 2
        assert result["tools_called"] == ["ibkr_get_position", "ibkr_get_account"]

    def test_structured_output_does_not_inflate_llm_rounds(self):
        trace = {
            "status": "success",
            "runtime_trace": [
                {"event": "llm_start", "round": 1},
                {"event": "llm_finish", "round": 1},
                {"event": "structured_output_parse_start"},
                {"event": "structured_output_success"},
                {"event": "structured_output_result", "contract_name": "test"},
            ],
        }
        result = summarize_trace_for_progress(trace)
        assert result["rounds_used"] == 1

    def test_empty_trace(self):
        result = summarize_trace_for_progress(None)
        assert result["rounds_used"] == 0
        assert result["tool_call_count"] == 0
        assert result["tools_called"] == []
        assert result["status"] == "success"

    def test_data_limitations_from_top_level(self):
        trace = {
            "status": "success",
            "data_limitations": ["missing news", "missing earnings"],
        }
        result = summarize_trace_for_progress(trace)
        assert result["data_limitations_count"] == 2

    def test_node_trace_as_fallback_source(self):
        trace = {
            "status": "success",
            "trace": [
                {"event": "llm_start", "round": 1},
                {"event": "llm_finish", "round": 1},
            ],
        }
        result = summarize_trace_for_progress(trace)
        assert result["rounds_used"] == 1

    def test_fallback_status(self):
        trace = {"status": "success", "fallback_used": True, "fallback_reason": "LLM failed"}
        result = summarize_trace_for_progress(trace)
        assert result["status"] == "fallback"
        assert result["fallback_used"] is True

    def test_evidence_node_tool_calls(self):
        trace = {
            "status": "success",
            "tools_called": ["tool_get_symbol_trades"],
            "tool_calls": [{"tool_name": "tool_get_symbol_trades", "success": True}],
            "tool_call_count": 1,
        }
        result = summarize_trace_for_progress(trace)
        assert result["tool_call_count"] == 1
        assert result["tools_called"] == ["tool_get_symbol_trades"]
        assert result["rounds_used"] == 0
