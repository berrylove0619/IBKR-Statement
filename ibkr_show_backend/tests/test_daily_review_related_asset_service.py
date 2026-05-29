"""
Tests for DailyReviewRelatedAssetService.

Covers:
- MSTR returns IBIT/GBTC/COIN/BTC proxy
- XIACY returns 1810.HK and EV peers
- AMD returns SMH/NVDA/AVGO/INTC
- IBKR returns XLF/HOOD/SCHW
- Does not return self
- Max 5 related assets per main symbol
"""
from unittest.mock import MagicMock

import pytest

from app.services.daily_review_related_asset_service import (
    DailyReviewRelatedAssetService,
    STRONG_RULES,
    MAX_RELATED_ASSETS,
    SCORE_STRONG_BUSINESS,
    SCORE_SAME_INDUSTRY_ETF,
    SCORE_CORE_PEER,
    SCORE_SAME_THEME,
)


class DummyLongbridgeClient:
    def __init__(self):
        self.get_candles_count = 0
        self.get_quote_snapshot_count = 0
        self.get_calc_indexes_count = 0
        self.get_news_count = 0
        self.get_static_info_count = 0

    def get_candles(self, symbol, start, end, period, adjust_type):
        self.get_candles_count += 1
        return MagicMock(items=[
            MagicMock(model_dump=MagicMock(return_value={"close": 100.0, "volume": 1000000})),
            MagicMock(model_dump=MagicMock(return_value={"close": 105.0, "volume": 1200000})),
        ])

    def get_quote_snapshot(self, symbol):
        self.quote_snapshot_count += 1
        return {"last_price": 105.0, "change_ratio": 0.05}

    def get_calc_indexes(self, symbol):
        self.get_calc_indexes_count += 1
        return {"pe_ttm": 25.0, "pb": 5.0}

    def get_news(self, symbol, limit):
        self.get_news_count += 1
        return MagicMock(items=[])

    def get_static_info(self, symbol):
        self.get_static_info_count += 1
        return {"name": symbol, "industry": "Technology"}


class DummySettings:
    pass


class TestRelatedAssetServiceDiscover:
    """Test related asset discovery for various symbols."""

    def _make_service(self):
        client = DummyLongbridgeClient()
        settings = DummySettings()
        return DailyReviewRelatedAssetService(client, settings), client

    def test_mstr_returns_crypto_proxies(self):
        """MSTR should discover IBIT, GBTC, COIN, BTC as crypto proxies."""
        service, _ = self._make_service()
        candidates = service._discover_candidates("MSTR.US")

        symbols = [c[0] for c in candidates]
        assert "IBIT.US" in symbols
        assert "GBTC.US" in symbols
        assert "COIN.US" in symbols
        assert "BTC.X" in symbols

    def test_mstr_does_not_return_self(self):
        """MSTR should not include itself in related assets."""
        service, _ = self._make_service()
        candidates = service._discover_candidates("MSTR.US")
        symbols = [c[0] for c in candidates]
        assert "MSTR.US" not in symbols

    def test_xiacy_returns_1810hkd_and_ev_peers(self):
        """XIACY should discover 1810.HK, XPEV.US, LI.US."""
        service, _ = self._make_service()
        candidates = service._discover_candidates("XIACY.US")

        symbols = [c[0] for c in candidates]
        assert "1810.HK" in symbols
        assert "XPEV.US" in symbols
        assert "LI.US" in symbols

    def test_amd_returns_semiconductor_peers(self):
        """AMD should discover SMH, NVDA, AVGO, INTC, QCOM."""
        service, _ = self._make_service()
        candidates = service._discover_candidates("AMD.US")

        symbols = [c[0] for c in candidates]
        assert "SMH.US" in symbols
        assert "NVDA.US" in symbols
        assert "AVGO.US" in symbols
        assert "INTC.US" in symbols
        assert "QCOM.US" in symbols

    def test_ibkr_returns_broker_peers(self):
        """IBKR should discover XLF, HOOD, SCHW."""
        service, _ = self._make_service()
        candidates = service._discover_candidates("IBKR.US")

        symbols = [c[0] for c in candidates]
        assert "XLF.US" in symbols
        assert "HOOD.US" in symbols
        assert "SCHW.US" in symbols

    def test_intc_returns_semiconductor_context(self):
        """INTC should discover SMH, AMD, NVDA, QCOM."""
        service, _ = self._make_service()
        candidates = service._discover_candidates("INTC.US")

        symbols = [c[0] for c in candidates]
        assert "SMH.US" in symbols
        assert "AMD.US" in symbols
        assert "NVDA.US" in symbols
        assert "QCOM.US" in symbols

    def test_qcom_returns_semiconductor_context(self):
        """QCOM should discover SMH, AMD, NVDA, AVGO."""
        service, _ = self._make_service()
        candidates = service._discover_candidates("QCOM.US")

        symbols = [c[0] for c in candidates]
        assert "SMH.US" in symbols
        assert "AMD.US" in symbols
        assert "NVDA.US" in symbols
        assert "AVGO.US" in symbols


class TestRelatedAssetServiceScoring:
    """Test confidence scoring for related assets."""

    def _make_service(self):
        client = DummyLongbridgeClient()
        settings = DummySettings()
        return DailyReviewRelatedAssetService(client, settings), client

    def test_strong_business_has_high_confidence(self):
        """Assets from STRONG_RULES should score >= 60 (high confidence)."""
        service, _ = self._make_service()
        candidates = service._discover_candidates("MSTR.US")
        scored = service._score_candidates("MSTR.US", candidates, {})

        # Find IBIT - should have high confidence due to STRONG_RULES
        ibit = next((c for c in scored if c.symbol == "IBIT.US"), None)
        assert ibit is not None
        assert ibit.score >= 60
        assert ibit.confidence == "high"

    def test_industry_etf_has_medium_confidence(self):
        """Industry ETFs should have medium confidence (score 30-60)."""
        service, _ = self._make_service()
        candidates = service._discover_candidates("AMD.US")
        scored = service._score_candidates("AMD.US", candidates, {})

        # SMH is industry ETF - should have score 30
        smh = next((c for c in scored if c.symbol == "SMH.US"), None)
        assert smh is not None
        assert smh.score == 30
        assert smh.confidence == "medium"


class TestRelatedAssetServiceSelection:
    """Test asset selection with composition constraints."""

    def _make_service(self):
        client = DummyLongbridgeClient()
        settings = DummySettings()
        return DailyReviewRelatedAssetService(client, settings), client

    def test_max_5_assets_selected(self):
        """Should select at most MAX_RELATED_ASSETS per symbol."""
        service, _ = self._make_service()
        candidates = service._discover_candidates("AMD.US")
        scored = service._score_candidates("AMD.US", candidates, {})
        selected = service._select_assets("AMD.US", scored)

        assert len(selected) <= MAX_RELATED_ASSETS

    def test_mstr_keeps_crypto_proxies(self):
        """MSTR must prioritize IBIT/GBTC/COIN/BTC."""
        service, _ = self._make_service()
        candidates = service._discover_candidates("MSTR.US")
        scored = service._score_candidates("MSTR.US", candidates, {})
        selected = service._select_assets("MSTR.US", scored)

        selected_symbols = [c.symbol for c in selected]
        # Crypto proxies should be in the selection
        crypto_proxies = ["IBIT.US", "GBTC.US", "COIN.US", "BTC.X"]
        has_crypto_proxy = any(sym in selected_symbols for sym in crypto_proxies)
        assert has_crypto_proxy, f"MSTR selection should include at least one crypto proxy: {selected_symbols}"


class TestRelatedAssetServiceBuildContext:
    """Test build_related_asset_context output structure."""

    def _make_service(self):
        client = DummyLongbridgeClient()
        settings = DummySettings()
        return DailyReviewRelatedAssetService(client, settings), client

    def test_output_structure(self):
        """Output should have symbol, relation_type_summary, assets, limitations."""
        service, _ = self._make_service()
        context = service.build_related_asset_context(
            symbol="MSTR",
            normalized_symbol="MSTR.US",
            report_date="2026-05-20",
            public_context={},
            benchmark_context={},
        )

        assert "symbol" in context
        assert context["symbol"] == "MSTR.US"
        assert "relation_type_summary" in context
        assert isinstance(context["relation_type_summary"], list)
        assert "assets" in context
        assert isinstance(context["assets"], list)
        assert "limitations" in context
        assert isinstance(context["limitations"], list)

    def test_assets_have_required_fields(self):
        """Each asset should have symbol, relation_type, confidence, score."""
        service, _ = self._make_service()
        context = service.build_related_asset_context(
            symbol="MSTR",
            normalized_symbol="MSTR.US",
            report_date="2026-05-20",
            public_context={},
            benchmark_context={},
        )

        for asset in context.get("assets", []):
            assert "symbol" in asset
            assert "relation_type" in asset
            assert "confidence" in asset
            assert "score" in asset
            assert asset["confidence"] in ("high", "medium", "low")


class TestSpecialRulesConsistency:
    """Test that STRONG_RULES are consistent with expected linkages."""

    def test_mstr_strong_rules(self):
        """MSTR strong rules should include IBIT, GBTC, COIN, BTC."""
        mstr_rules = STRONG_RULES.get("MSTR.US") or STRONG_RULES.get("MSTR")
        assert mstr_rules is not None
        assert "IBIT.US" in mstr_rules
        assert "GBTC.US" in mstr_rules
        assert "COIN.US" in mstr_rules
        assert "BTC.X" in mstr_rules

    def test_xiacy_strong_rules(self):
        """XIACY strong rules should include 1810.HK, XPEV.US, LI.US."""
        xiacy_rules = STRONG_RULES.get("XIACY.US") or STRONG_RULES.get("XIACY")
        assert xiacy_rules is not None
        assert "1810.HK" in xiacy_rules
        assert "XPEV.US" in xiacy_rules
        assert "LI.US" in xiacy_rules

    def test_amd_strong_rules(self):
        """AMD strong rules should include SMH, NVDA, AVGO, INTC, QCOM."""
        amd_rules = STRONG_RULES.get("AMD.US") or STRONG_RULES.get("AMD")
        assert amd_rules is not None
        assert "SMH.US" in amd_rules
        assert "NVDA.US" in amd_rules
        assert "AVGO.US" in amd_rules
        assert "INTC.US" in amd_rules
        assert "QCOM.US" in amd_rules

    def test_ibkr_strong_rules(self):
        """IBKR strong rules should include XLF, HOOD, SCHW."""
        ibkr_rules = STRONG_RULES.get("IBKR.US") or STRONG_RULES.get("IBKR")
        assert ibkr_rules is not None
        assert "XLF.US" in ibkr_rules
        assert "HOOD.US" in ibkr_rules
        assert "SCHW.US" in ibkr_rules


if __name__ == "__main__":
    pytest.main([__file__, "-v"])