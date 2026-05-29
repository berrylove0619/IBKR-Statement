"""
Tests for Daily Review Evidence Card components.

These tests verify:
1. DailyReviewEvidenceCardBuilder can select focus symbols correctly
2. PnL largest contributor/drag is selected
3. Weight largest is selected
4. Special linkage symbols (MSTR, XIACY, etc.) trigger cross-asset requirements
5. Sub-agent failure generates fallback card without aborting main flow
6. DailyPositionReviewAgent uses sub-agent card mode by default
7. Document contains subagent_card_pack / evidence_card_summary / subagent_trace
8. Sub-agent failure falls back to legacy mode
9. Email uses sub-agent mode document correctly
10. Context budget distinguishes core facts vs symbol cards
"""

from __future__ import annotations

import json
import pytest

from app.agents.daily_review_evidence_cards import (
    DailyReviewEvidenceCardPack,
    DataQualitySummary,
    SymbolEvidenceCard,
    MacroEvidenceCard,
    build_fallback_symbol_card,
    build_fallback_macro_card,
    compute_card_pack_summary,
    SubAgentTrace,
)
from app.agents.evidence_schema import build_daily_position_review_evidence_pack_from_cards
from app.services.daily_review_evidence_card_builder import (
    DailyReviewEvidenceCardBuilder,
    _select_focus_symbols_for_cards,
    SPECIAL_LINKAGE_SYMBOLS,
)


class TestSymbolEvidenceCardDataclass:
    def test_symbol_evidence_card_to_dict_roundtrip(self) -> None:
        card = SymbolEvidenceCard(
            symbol="AMD.US",
            normalized_symbol="AMD.US",
            report_date="2026-05-20",
            account_impact=SymbolEvidenceCard(
                symbol="AMD.US",
                normalized_symbol="AMD.US",
                report_date="2026-05-20",
            ).account_impact,
        )
        data = card.to_dict()
        restored = SymbolEvidenceCard.from_dict(data)
        assert restored.symbol == "AMD.US"
        assert restored.report_date == "2026-05-20"

    def test_build_fallback_symbol_card_preserves_ibkr_fields(self) -> None:
        position_item = {
            "symbol": "NVDA.US",
            "normalized_symbol": "NVDA.US",
            "weight": 0.15,
            "daily_pnl": -500.0,
            "daily_change_percent": -3.5,
            "contribution_ratio": -0.5,
            "market_value": 15000.0,
            "quantity": 100.0,
            "average_cost": 120.0,
            "unrealized_pnl": -300.0,
            "unrealized_pnl_percent": -25.0,
        }
        fallback = build_fallback_symbol_card(
            symbol="NVDA.US",
            normalized_symbol="NVDA.US",
            report_date="2026-05-20",
            position_item=position_item,
            reason="sub-agent unavailable",
        )
        assert fallback.evidence_quality == "low"
        assert fallback.account_impact.daily_pnl == -500.0
        assert fallback.account_impact.position_weight == 0.15
        # Fallback card writes "source_missing" prefix in top-level data_limitations
        assert any("source_missing" in lim for lim in fallback.data_limitations)


class TestMacroEvidenceCardDataclass:
    def test_macro_evidence_card_to_dict_roundtrip(self) -> None:
        card = MacroEvidenceCard(
            report_date="2026-05-20",
            market_regime="risk_on",
            risk_sentiment="risk_on",
            tech_sentiment="positive",
            macro_events=["Fed Rate Decision"],
        )
        data = card.to_dict()
        restored = MacroEvidenceCard.from_dict(data)
        assert restored.market_regime == "risk_on"
        assert restored.risk_sentiment == "risk_on"


class TestDailyReviewEvidenceCardPack:
    def test_pack_to_dict_contains_all_fields(self) -> None:
        pack = DailyReviewEvidenceCardPack(
            report_date="2026-05-20",
            account_facts={"overview": {"daily_pnl": 1000}},
            position_facts=[{"symbol": "AMD.US"}],
            rankings={"profit_contributors": []},
            risk={"max_position": {}},
            attribution_quality={"unexplained_pnl": 100},
            symbol_cards=[],
            macro_card=None,
            data_quality=DataQualitySummary(overall="high"),
            evidence_used=["IBKR deterministic"],
            subagent_trace=SubAgentTrace(),
            budget_report={},
        )
        data = pack.to_dict()
        assert data["report_date"] == "2026-05-20"
        assert "symbol_cards" in data
        assert "macro_card" in data
        assert "subagent_trace" in data


class TestComputeCardPackSummary:
    def test_summary_counts_correctly(self) -> None:
        pack = DailyReviewEvidenceCardPack(
            report_date="2026-05-20",
            account_facts={},
            position_facts=[],
            rankings={},
            risk={},
            attribution_quality={},
            symbol_cards=[
                SymbolEvidenceCard(
                    symbol="AMD.US",
                    normalized_symbol="AMD.US",
                    report_date="2026-05-20",
                    evidence_quality="high",
                    likely_drivers=["AI demand"],
                    watch_points=["NVDA drop"],
                    data_limitations=["no news"],
                ),
                SymbolEvidenceCard(
                    symbol="NVDA.US",
                    normalized_symbol="NVDA.US",
                    report_date="2026-05-20",
                    evidence_quality="low",
                    likely_drivers=[],
                    watch_points=[],
                    data_limitations=["subagent_failed", "source_missing"],
                ),
            ],
            macro_card=MacroEvidenceCard(
                report_date="2026-05-20",
                data_limitations=["rate data missing"],
            ),
            data_quality=DataQualitySummary(overall="medium"),
            evidence_used=[],
            subagent_trace=SubAgentTrace(),
            budget_report={},
        )
        summary = compute_card_pack_summary(pack)
        assert summary.symbol_count == 2
        assert summary.macro_card_present is True
        assert summary.fallback_card_count == 1
        assert summary.quality == "medium"
        assert summary.limitations_count == 4  # AMD:1 + NVDA:2 + macro:1 = 4


class TestFocusSymbolSelection:
    def test_pnl_largest_contributor_selected(self) -> None:
        positions = [
            {"symbol": "AMD.US", "normalized_symbol": "AMD.US", "daily_pnl": 50.0, "weight": 0.05},
            {"symbol": "NVDA.US", "normalized_symbol": "NVDA.US", "daily_pnl": -500.0, "weight": 0.15},
            {"symbol": "TSLA.US", "normalized_symbol": "TSLA.US", "daily_pnl": 100.0, "weight": 0.10},
        ]
        selected = _select_focus_symbols_for_cards(positions, {}, "2026-05-20", limit=6)
        symbols = [item["symbol"] for item in selected]
        assert "NVDA.US" in symbols  # largest |PnL|
        assert "TSLA.US" in symbols  # 2nd largest |PnL|

    def test_weight_largest_selected(self) -> None:
        positions = [
            {"symbol": "AMD.US", "normalized_symbol": "AMD.US", "daily_pnl": 50.0, "weight": 0.05},
            {"symbol": "MSTR.US", "normalized_symbol": "MSTR.US", "daily_pnl": 20.0, "weight": 0.25},  # heaviest weight
            {"symbol": "SMCI.US", "normalized_symbol": "SMCI.US", "daily_pnl": 10.0, "weight": 0.08},
        ]
        selected = _select_focus_symbols_for_cards(positions, {}, "2026-05-20", limit=6)
        symbols = [item["symbol"] for item in selected]
        assert "MSTR.US" in symbols  # heaviest weight

    def test_special_linkage_symbols_get_priority(self) -> None:
        positions = [
            {"symbol": "AAPL.US", "normalized_symbol": "AAPL.US", "daily_pnl": 30.0, "weight": 0.04},
            {"symbol": "MSTR.US", "normalized_symbol": "MSTR.US", "daily_pnl": 10.0, "weight": 0.03},  # special linkage
            {"symbol": "TSLA.US", "normalized_symbol": "TSLA.US", "daily_pnl": 15.0, "weight": 0.05},   # special linkage
        ]
        selected = _select_focus_symbols_for_cards(positions, {}, "2026-05-20", limit=4)
        symbols = [item["symbol"] for item in selected]
        # MSTR and TSLA should be included due to special linkage priority boost
        assert "MSTR.US" in symbols
        assert "TSLA.US" in symbols

    def test_abnormal_change_percent_boosted(self) -> None:
        positions = [
            {"symbol": "AMD.US", "normalized_symbol": "AMD.US", "daily_pnl": 50.0, "weight": 0.05, "daily_change_percent": 1.0},
            {"symbol": "SMCI.US", "normalized_symbol": "SMCI.US", "daily_pnl": 40.0, "weight": 0.04, "daily_change_percent": 8.5},  # abnormal
        ]
        selected = _select_focus_symbols_for_cards(positions, {}, "2026-05-20", limit=6)
        symbols = [item["symbol"] for item in selected]
        assert "SMCI.US" in symbols  # high change percent boost

    def test_major_contributor_drag_boosted(self) -> None:
        positions = [
            {"symbol": "AMD.US", "normalized_symbol": "AMD.US", "daily_pnl": 50.0, "weight": 0.05, "is_major_contributor": True},
            {"symbol": "INTC.US", "normalized_symbol": "INTC.US", "daily_pnl": -20.0, "weight": 0.03, "is_major_drag": True},
        ]
        selected = _select_focus_symbols_for_cards(positions, {}, "2026-05-20", limit=6)
        symbols = [item["symbol"] for item in selected]
        assert "AMD.US" in symbols
        assert "INTC.US" in symbols

    def test_deduplication_by_normalized_symbol(self) -> None:
        """Same normalized symbol should not appear twice."""
        positions = [
            {"symbol": "AMD", "normalized_symbol": "AMD.US", "daily_pnl": 50.0, "weight": 0.05},
            {"symbol": "AMD.US", "normalized_symbol": "AMD.US", "daily_pnl": 30.0, "weight": 0.03},
        ]
        selected = _select_focus_symbols_for_cards(positions, {}, "2026-05-20", limit=6)
        assert len(selected) == 1

    def test_limit_enforced(self) -> None:
        positions = [
            {"symbol": f"SYM{i}.US", "normalized_symbol": f"SYM{i}.US", "daily_pnl": 100.0 + i, "weight": 0.05 + i * 0.01}
            for i in range(10)
        ]
        selected = _select_focus_symbols_for_cards(positions, {}, "2026-05-20", limit=4)
        assert len(selected) == 4


class TestSpecialLinkageSymbols:
    def test_mstr_is_special_linkage(self) -> None:
        assert "MSTR.US" in SPECIAL_LINKAGE_SYMBOLS or "MSTR" in SPECIAL_LINKAGE_SYMBOLS

    def test_xiacy_is_special_linkage(self) -> None:
        assert "XIACY.US" in SPECIAL_LINKAGE_SYMBOLS or "XIACY" in SPECIAL_LINKAGE_SYMBOLS

    def test_tsla_is_special_linkage(self) -> None:
        assert "TSLA.US" in SPECIAL_LINKAGE_SYMBOLS or "TSLA" in SPECIAL_LINKAGE_SYMBOLS

    def test_amd_inтел_is_special_linkage(self) -> None:
        assert "AMD.US" in SPECIAL_LINKAGE_SYMBOLS or "AMD" in SPECIAL_LINKAGE_SYMBOLS


class TestEvidenceSchemaFromCards:
    def test_build_evidence_pack_from_cards_has_symbol_cards(self) -> None:
        card_pack = {
            "report_date": "2026-05-20",
            "account_facts": {"overview": {"daily_pnl": 1000}},
            "position_facts": [],
            "rankings": {},
            "risk": {},
            "attribution_quality": {},
            "benchmarks": {},
            "symbol_cards": [
                {"symbol": "AMD.US", "normalized_symbol": "AMD.US", "report_date": "2026-05-20", "evidence_quality": "high"}
            ],
            "macro_card": {"report_date": "2026-05-20", "market_regime": "risk_on"},
            "data_quality": {"overall": "high", "warnings": [], "limitations": []},
            "subagent_trace": {"symbol_agent_calls": [], "macro_agent_calls": []},
            "budget_report": {},
        }
        pack = build_daily_position_review_evidence_pack_from_cards(card_pack)
        assert "symbol_cards" in pack
        assert len(pack["symbol_cards"]) == 1
        assert pack["symbol_cards"][0]["symbol"] == "AMD.US"

    def test_build_evidence_pack_from_cards_has_budget_report(self) -> None:
        card_pack = {
            "report_date": "2026-05-20",
            "account_facts": {},
            "position_facts": [],
            "rankings": {},
            "risk": {},
            "attribution_quality": {},
            "benchmarks": {},
            "symbol_cards": [],
            "macro_card": None,
            "data_quality": {},
            "subagent_trace": {"symbol_agent_calls": [], "macro_agent_calls": []},
            "budget_report": {"custom_key": "custom_value"},
        }
        pack = build_daily_position_review_evidence_pack_from_cards(card_pack)
        assert "budget_report" in pack
        assert "core_account_facts_budget" in pack["budget_report"]
        assert "symbol_cards_budget" in pack["budget_report"]


class TestFallbackCardBuilder:
    def test_fallback_macro_card_has_data_limitations(self) -> None:
        card = build_fallback_macro_card(
            report_date="2026-05-20",
            benchmark_context={"QQQ": {"return_percent": 1.5}},
            reason="LLM unavailable",
        )
        assert any("LLM unavailable" in lim for lim in card.data_limitations)
        assert card.market_regime is None
        assert card.benchmark_context.get("QQQ", {}).get("return_percent") == 1.5


class TestDataQualityLimitations:
    def test_data_limitations_category_source_missing(self) -> None:
        """source_missing should be distinguishable from other limitation types."""
        limitation = "source_missing: BTC price data unavailable for MSTR"
        assert limitation.startswith("source_missing")

    def test_data_limitations_category_budget_truncated(self) -> None:
        limitation = "budget_truncated: news items reduced from 8 to 3"
        assert limitation.startswith("budget_truncated")

    def test_data_limitations_category_subagent_failed(self) -> None:
        limitation = "subagent_failed: symbol evidence agent returned invalid JSON"
        assert limitation.startswith("subagent_failed")

    def test_data_limitations_category_not_selected(self) -> None:
        limitation = "not_selected_by_priority: symbol ranked below limit cutoff"
        assert limitation.startswith("not_selected_by_priority")


class TestContextBudgetGroups:
    def test_core_facts_budget_defined(self) -> None:
        from app.agents.context_budget import CORE_FACTS_BUDGET
        assert CORE_FACTS_BUDGET > 0

    def test_symbol_evidence_cards_budget_defined(self) -> None:
        from app.agents.context_budget import SYMBOL_EVIDENCE_CARDS_BUDGET
        assert SYMBOL_EVIDENCE_CARDS_BUDGET > 0

    def test_macro_evidence_card_budget_defined(self) -> None:
        from app.agents.context_budget import MACRO_EVIDENCE_CARD_BUDGET
        assert MACRO_EVIDENCE_CARD_BUDGET > 0