"""
Tests for evidence_summary.py
"""

import pytest

from app.agents.evidence_summary import (
    build_evidence_summary,
)


class TestBuildEvidenceSummary:
    def test_empty_evidence_pack(self):
        result = build_evidence_summary({})
        assert "data_sources" in result
        assert "evidence_sections" in result
        assert "tools_used" in result
        assert "missing_data" in result
        assert "data_limitations" in result
        assert "budget_summary" in result

    def test_evidence_sections_has_expected_fields(self):
        result = build_evidence_summary({})
        for section in result["evidence_sections"]:
            assert "section" in section
            assert "source" in section
            assert "status" in section
            assert "summary" in section
            assert "item_count" in section

    def test_missing_data_detects_empty_required_sections(self):
        result = build_evidence_summary({})
        missing_str = " ".join(result["missing_data"])
        assert "account_context" in missing_str
        assert "position_context" in missing_str

    def test_sensitive_fields_are_not_exposed(self):
        evidence = {
            "account_context": {
                "api_key": "secret123",
                "token": "mytoken",
                "data": {"cash": 10000},
            }
        }
        result = build_evidence_summary(evidence)
        # evidence_summary should not contain raw api_key or token
        result_str = str(result)
        assert "secret123" not in result_str
        assert "mytoken" not in result_str

    def test_budget_summary_calculates_sizes(self):
        evidence = {
            "account_context": {
                "data": {"cash": 10000},
                "budget_report": {
                    "original_size": 5000,
                    "final_size": 2000,
                    "truncated": True,
                    "dropped_items": {"detail": "trimmed"},
                },
            }
        }
        result = build_evidence_summary(evidence)
        assert result["budget_summary"]["total_original_size"] == 5000
        assert result["budget_summary"]["total_final_size"] == 2000
        assert "account_context" in result["budget_summary"]["truncated_sections"]

    def test_evidence_with_run_trace(self):
        evidence = {"account_context": {"data": {"cash": 10000}}}
        run_trace = [
            {"event": "llm_start", "created_at_ms": 1000},
            {"event": "tool_start", "tool": "get_account"},
            {"event": "tool_finish", "tool": "get_account", "ok": True, "summary": "ok", "observation": {"original_size": 1000, "final_size": 500}},
            {"event": "llm_finish", "created_at_ms": 2000},
        ]
        result = build_evidence_summary(evidence, run_trace)
        assert len(result["tools_used"]) == 1
        assert result["tools_used"][0]["name"] == "get_account"
        assert result["tools_used"][0]["ok"] is True

    def test_llm_input_policy_defaults(self):
        result = build_evidence_summary({})
        assert result["llm_input_policy"]["account_data_policy"] == "IBKR_ONLY"
        assert result["llm_input_policy"]["public_data_policy"] == "LONGBRIDGE_PUBLIC_ONLY"
        assert result["llm_input_policy"]["raw_sensitive_data_exposed"] is False

    def test_data_sources_reflected(self):
        evidence = {
            "data_sources": {"account_data": "IBKR_ONLY", "public_market_data": "LONGBRIDGE_PUBLIC_ONLY"}
        }
        result = build_evidence_summary(evidence)
        assert result["data_sources"]["account_data"] == "IBKR_ONLY"


class TestBuildEvidenceSummarySectionStatus:
    def test_none_section_is_missing(self):
        from app.agents.evidence_summary import _section_status
        assert _section_status("account_context", None, None) == "missing"

    def test_empty_dict_is_missing(self):
        from app.agents.evidence_summary import _section_status
        assert _section_status("account_context", {}, None) == "missing"

    def test_empty_list_is_missing(self):
        from app.agents.evidence_summary import _section_status
        assert _section_status("account_context", [], None) == "missing"

    def test_with_data_is_available(self):
        from app.agents.evidence_summary import _section_status
        assert _section_status("account_context", {"data": {}}, None) == "available"


class TestIsSensitiveKey:
    def test_sensitive_keys_detected(self):
        from app.agents.evidence_summary import _is_sensitive_key
        assert _is_sensitive_key("token") is True
        assert _is_sensitive_key("api_key") is True
        assert _is_sensitive_key("secret") is True
        assert _is_sensitive_key("password") is True
        assert _is_sensitive_key("authorization") is True
        assert _is_sensitive_key("my_token_value") is True

    def test_non_sensitive_keys_pass(self):
        from app.agents.evidence_summary import _is_sensitive_key
        assert _is_sensitive_key("symbol") is False
        assert _is_sensitive_key("cash") is False
        assert _is_sensitive_key("score") is False