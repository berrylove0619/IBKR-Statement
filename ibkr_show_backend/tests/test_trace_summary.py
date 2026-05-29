"""
Tests for trace_summary.py
"""

import pytest

from app.agents.trace_summary import build_run_trace_summary


class TestBuildRunTraceSummary:
    def test_empty_trace(self):
        result = build_run_trace_summary([])
        assert result["tool_call_count"] == 0
        assert result["tool_success_count"] == 0
        assert result["tool_error_count"] == 0
        assert result["llm_rounds"] == 0
        assert result["truncated_observations"] == 0
        assert result["tools"] == []
        assert result["llm_started"] is None
        assert result["llm_finished"] is None

    def test_single_llm_round(self):
        trace = [
            {"event": "llm_start", "created_at_ms": 1000},
            {"event": "llm_finish", "created_at_ms": 2000},
        ]
        result = build_run_trace_summary(trace)
        assert result["llm_rounds"] == 1
        assert result["llm_started"] == 1000
        assert result["llm_finished"] == 2000

    def test_multiple_llm_rounds(self):
        trace = [
            {"event": "llm_start", "created_at_ms": 100},
            {"event": "llm_finish", "created_at_ms": 200},
            {"event": "llm_start", "created_at_ms": 300},
            {"event": "llm_finish", "created_at_ms": 400},
        ]
        result = build_run_trace_summary(trace)
        assert result["llm_rounds"] == 2

    def test_tool_success(self):
        trace = [
            {"event": "llm_start", "created_at_ms": 100},
            {"event": "tool_start", "tool": "get_account"},
            {"event": "tool_finish", "tool": "get_account", "ok": True, "summary": "got account"},
            {"event": "llm_finish", "created_at_ms": 500},
        ]
        result = build_run_trace_summary(trace)
        assert result["tool_call_count"] == 1
        assert result["tool_success_count"] == 1
        assert result["tool_error_count"] == 0
        assert len(result["tools"]) == 1
        assert result["tools"][0]["tool"] == "get_account"
        assert result["tools"][0]["ok"] is True

    def test_tool_error(self):
        trace = [
            {"event": "llm_start", "created_at_ms": 100},
            {"event": "tool_error", "tool": "get_account", "summary": "failed to call"},
            {"event": "llm_finish", "created_at_ms": 500},
        ]
        result = build_run_trace_summary(trace)
        assert result["tool_call_count"] == 1
        assert result["tool_success_count"] == 0
        assert result["tool_error_count"] == 1
        assert len(result["tools"]) == 1
        assert result["tools"][0]["ok"] is False

    def test_truncated_observation(self):
        trace = [
            {"event": "llm_start", "created_at_ms": 100},
            {
                "event": "tool_finish",
                "tool": "get_account",
                "ok": True,
                "summary": "got account",
                "observation": {"truncated": True, "original_size": 5000, "final_size": 2000},
            },
            {"event": "llm_finish", "created_at_ms": 500},
        ]
        result = build_run_trace_summary(trace)
        assert result["truncated_observations"] == 1
        assert result["tools"][0]["truncated"] is True
        assert result["tools"][0]["original_size"] == 5000
        assert result["tools"][0]["final_size"] == 2000

    def test_mixed_success_and_error(self):
        trace = [
            {"event": "llm_start", "created_at_ms": 100},
            {"event": "tool_start", "tool": "tool1"},
            {"event": "tool_finish", "tool": "tool1", "ok": True, "summary": "ok"},
            {"event": "tool_start", "tool": "tool2"},
            {"event": "tool_error", "tool": "tool2", "summary": "error"},
            {"event": "tool_start", "tool": "tool3"},
            {"event": "tool_finish", "tool": "tool3", "ok": True, "summary": "ok"},
            {"event": "llm_finish", "created_at_ms": 500},
        ]
        result = build_run_trace_summary(trace)
        # tool_call_count = tool_start (3) + tool_error (1) = 4
        assert result["tool_call_count"] == 4
        assert result["tool_success_count"] == 2
        assert result["tool_error_count"] == 1