"""
Tests for versions.py
"""

import pytest

from app.agents.versions import (
    AGENT_HARNESS_VERSION,
    AGENT_MODE_FIXED_EVIDENCE,
    CONTEXT_BUDGET_VERSION,
    EVIDENCE_SCHEMA_VERSION,
    OUTPUT_SCHEMA_VERSION,
    TRADE_DECISION_AGENT_VERSION,
    TRADE_DECISION_EVIDENCE_BUILDER_VERSION,
    TRADE_DECISION_PROMPT_VERSION,
    TRADE_DECISION_TOOLSET_VERSION,
    TRADE_REVIEW_AGENT_VERSION,
    TRADE_REVIEW_EVIDENCE_BUILDER_VERSION,
    TRADE_REVIEW_PROMPT_VERSION,
    TRADE_REVIEW_TOOLSET_VERSION,
    DAILY_POSITION_REVIEW_AGENT_VERSION,
    DAILY_POSITION_REVIEW_EVIDENCE_BUILDER_VERSION,
    DAILY_POSITION_REVIEW_PROMPT_VERSION,
    DAILY_POSITION_REVIEW_TOOLSET_VERSION,
    build_metadata,
)


class TestVersionConstants:
    def test_harness_version_format(self):
        assert AGENT_HARNESS_VERSION.startswith("p")

    def test_agent_versions_exist(self):
        assert TRADE_DECISION_AGENT_VERSION
        assert TRADE_REVIEW_AGENT_VERSION
        assert DAILY_POSITION_REVIEW_AGENT_VERSION
        assert "_v2" in TRADE_DECISION_AGENT_VERSION
        assert "_v2" in TRADE_REVIEW_AGENT_VERSION
        assert "_v2" in DAILY_POSITION_REVIEW_AGENT_VERSION

    def test_prompt_versions_contain_date(self):
        assert "2026_05" in TRADE_DECISION_PROMPT_VERSION
        assert "2026_05" in TRADE_REVIEW_PROMPT_VERSION
        assert "2026_05" in DAILY_POSITION_REVIEW_PROMPT_VERSION

    def test_toolset_versions_contain_v2(self):
        assert "_v2" in TRADE_DECISION_TOOLSET_VERSION
        assert "_v2" in TRADE_REVIEW_TOOLSET_VERSION
        assert "_v2" in DAILY_POSITION_REVIEW_TOOLSET_VERSION

    def test_evidence_builder_versions_contain_v2(self):
        assert "_v2" in TRADE_DECISION_EVIDENCE_BUILDER_VERSION
        assert "_v2" in TRADE_REVIEW_EVIDENCE_BUILDER_VERSION
        assert "_v2" in DAILY_POSITION_REVIEW_EVIDENCE_BUILDER_VERSION

    def test_agent_modes_are_documented(self):
        assert AGENT_MODE_FIXED_EVIDENCE == "fixed_evidence"

    def test_schema_versions_exist(self):
        assert OUTPUT_SCHEMA_VERSION == "output_schema_v1"
        assert EVIDENCE_SCHEMA_VERSION == "evidence_schema_v1"
        assert CONTEXT_BUDGET_VERSION == "context_budget_v1"


class TestBuildMetadata:
    def test_build_metadata_returns_all_fields(self):
        meta = build_metadata(
            agent_version="test_agent_v1",
            prompt_version="test_prompt_2026_05",
            schema_version="output_schema_v1",
            toolset_version="test_tools_v1",
            evidence_builder_version="test_builder_v1",
            agent_mode="fixed_evidence",
        )
        assert "agent_version" in meta
        assert "prompt_version" in meta
        assert "schema_version" in meta
        assert "toolset_version" in meta
        assert "evidence_builder_version" in meta
        assert "evidence_schema_version" in meta
        assert "context_budget_version" in meta
        assert "invariant_version" in meta
        assert "harness_version" in meta
        assert "agent_mode" in meta
        assert "model_provider_snapshot" in meta
        assert "generated_at" in meta

    def test_build_metadata_includes_provider_snapshot(self):
        provider = {"provider_name": "openai", "model": "gpt-4o", "base_url": "https://api.openai.com"}
        meta = build_metadata(
            agent_version="test",
            prompt_version="test",
            schema_version="test",
            toolset_version="test",
            evidence_builder_version="test",
            agent_mode="fixed_evidence",
            model_provider_snapshot=provider,
        )
        assert meta["model_provider_snapshot"] == provider

    def test_build_metadata_defaults_empty_provider_snapshot(self):
        meta = build_metadata(
            agent_version="test",
            prompt_version="test",
            schema_version="test",
            toolset_version="test",
            evidence_builder_version="test",
            agent_mode="fixed_evidence",
        )
        assert meta["model_provider_snapshot"] == {}

    def test_build_metadata_includes_generated_at(self):
        import re

        meta = build_metadata(
            agent_version="test",
            prompt_version="test",
            schema_version="test",
            toolset_version="test",
            evidence_builder_version="test",
            agent_mode="fixed_evidence",
        )
        # ISO format timestamp
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", meta["generated_at"])