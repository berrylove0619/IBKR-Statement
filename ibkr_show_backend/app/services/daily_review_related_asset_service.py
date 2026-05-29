"""
Service for building related asset context for daily review.

Responsibilities:
- Discover related/special linkage assets for a given symbol
- Score and rank related assets by confidence
- Pull public market data for each related asset (candles, quotes, calc indexes, news, static info)
- Output structured related asset context for use in evidence card generation
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings
from app.services.longbridge_service import LongbridgeExternalDataClient, LongbridgeExternalDataError, LongbridgeUnavailableError

# Strong business relationship rules (seed assets)
STRONG_RULES: dict[str, list[str]] = {
    "MSTR.US": ["IBIT.US", "GBTC.US", "COIN.US", "BTC.X"],
    "MSTR": ["IBIT.US", "GBTC.US", "COIN.US", "BTC.X"],
    "XIACY.US": ["1810.HK", "XPEV.US", "LI.US"],
    "XIACY": ["1810.HK", "XPEV.US", "LI.US"],
    "TSLA.US": ["RIVN.US", "XPEV.US", "LI.US"],
    "TSLA": ["RIVN.US", "XPEV.US", "LI.US"],
    "AMD.US": ["SMH.US", "NVDA.US", "AVGO.US", "INTC.US", "QCOM.US"],
    "AMD": ["SMH.US", "NVDA.US", "AVGO.US", "INTC.US", "QCOM.US"],
    "INTC.US": ["SMH.US", "AMD.US", "NVDA.US", "QCOM.US"],
    "INTC": ["SMH.US", "AMD.US", "NVDA.US", "QCOM.US"],
    "QCOM.US": ["SMH.US", "AMD.US", "NVDA.US", "AVGO.US"],
    "QCOM": ["SMH.US", "AMD.US", "NVDA.US", "AVGO.US"],
    "SMCI.US": ["SMH.US", "NVDA.US", "AMD.US", "AVGO.US"],
    "SMCI": ["SMH.US", "NVDA.US", "AMD.US", "AVGO.US"],
    "MSFT.US": ["QQQ.US", "XLK.US", "META.US", "GOOGL.US", "AMZN.US"],
    "MSFT": ["QQQ.US", "XLK.US", "META.US", "GOOGL.US", "AMZN.US"],
    "META.US": ["QQQ.US", "XLK.US", "MSFT.US", "GOOGL.US", "AMZN.US"],
    "META": ["QQQ.US", "XLK.US", "MSFT.US", "GOOGL.US", "AMZN.US"],
    "IBKR.US": ["XLF.US", "HOOD.US", "SCHW.US"],
    "IBKR": ["XLF.US", "HOOD.US", "SCHW.US"],
}

# Industry/theme mapping rules
THEME_RULES: dict[str, list[str]] = {
    "semiconductor": ["SMH.US", "SOXX.US", "NVDA.US", "AMD.US", "AVGO.US"],
    "mega_cap_tech": ["QQQ.US", "XLK.US", "MSFT.US", "GOOGL.US", "META.US", "AMZN.US"],
    "ev": ["TSLA.US", "XPEV.US", "LI.US", "NIO.US", "DRIV.US"],
    "crypto": ["IBIT.US", "GBTC.US", "COIN.US", "MSTR.US"],
    "broker": ["XLF.US", "SCHW.US", "HOOD.US", "IBKR.US"],
}

# Confidence scoring weights
SCORE_STRONG_BUSINESS = 50
SCORE_SAME_INDUSTRY_ETF = 30
SCORE_CORE_PEER = 25
SCORE_SAME_THEME = 20
SCORE_STATIC_INFO_HIT = 10
SCORE_LLM_CANDIDATE = 5

# Score thresholds
SCORE_THRESHOLD_HIGH = 60
SCORE_THRESHOLD_MEDIUM = 30

# Max related assets per symbol
MAX_RELATED_ASSETS = 5
MIN_INDUSTRY_ETF = 1
MAX_CORE_PEERS = 3
MAX_SPECIAL_PROXY = 1


@dataclass
class RelatedAssetItem:
    symbol: str
    relation_type: str
    reason: str
    confidence: str  # "high", "medium", "low"
    score: int
    day_change_percent: float | None = None
    period_14d_return_percent: float | None = None
    quote: dict = field(default_factory=dict)
    technical_levels: dict = field(default_factory=dict)
    news: list[dict] = field(default_factory=list)
    static_info: dict = field(default_factory=dict)
    data_quality: str = "high"
    limitations: list[str] = field(default_factory=list)


def _normalize_symbol(symbol: str) -> str:
    """Normalize symbol to US format."""
    s = symbol.strip().upper()
    if "." in s:
        return s
    return f"{s}.US"


def _is_industry_etf(symbol: str) -> bool:
    """Check if symbol is an industry/theme ETF."""
    industry_etfs = {
        "SMH.US", "SOXX.US", "QQQ.US", "XLK.US", "XLF.US",
        "DRIV.US", "IBIT.US", "GBTC.US", "HOOD.US", "SCHW.US",
    }
    return symbol in industry_etfs


def _is_core_peer(symbol: str) -> bool:
    """Check if symbol is a core peer (direct competitor)."""
    core_peers = {
        "NVDA.US", "AMD.US", "AVGO.US", "INTC.US", "QCOM.US",
        "XPEV.US", "LI.US", "NIO.US", "RIVN.US",
        "META.US", "MSFT.US", "GOOGL.US", "AMZN.US",
        "COIN.US", "IBIT.US", "GBTC.US",
        "1810.HK",
    }
    return symbol in core_peers


def _is_special_proxy(symbol: str) -> bool:
    """Check if symbol is a special proxy asset (e.g., BTC proxy)."""
    return symbol in {"BTC.X", "IBIT.US", "GBTC.US", "COIN.US"}


def _calculate_return_percent(candles: list[dict]) -> float | None:
    """Calculate period return from candles."""
    if len(candles) < 2:
        return None
    closes = [c.get("close") for c in candles if c.get("close") is not None]
    if len(closes) < 2:
        return None
    first = float(closes[0])
    last = float(closes[-1])
    if first == 0:
        return None
    return round((last - first) / abs(first) * 100.0, 4)


def _calculate_day_change(candles: list[dict]) -> float | None:
    """Calculate day change from last two candles."""
    if len(candles) < 2:
        return None
    closes = [c.get("close") for c in candles if c.get("close") is not None]
    if len(closes) < 2:
        return None
    prev = float(closes[-2])
    last = float(closes[-1])
    if prev == 0:
        return None
    return round((last - prev) / abs(prev) * 100.0, 4)


class DailyReviewRelatedAssetService:
    def __init__(self, longbridge_client: LongbridgeExternalDataClient, settings: Settings) -> None:
        self.longbridge_client = longbridge_client
        self.settings = settings

    def build_related_asset_context(
        self,
        symbol: str,
        normalized_symbol: str,
        report_date: str,
        public_context: dict,
        benchmark_context: dict,
    ) -> dict:
        """
        Build related asset context for a given symbol.

        Args:
            symbol: Raw symbol string
            normalized_symbol: Normalized symbol (e.g., "MSTR.US")
            report_date: The report date string
            public_context: Public context dict for the main symbol
            benchmark_context: Benchmark context dict

        Returns:
            dict with structure:
            {
                "symbol": "MSTR.US",
                "relation_type_summary": ["crypto_proxy"],
                "assets": [...],
                "limitations": []
            }
        """
        normalized = _normalize_symbol(symbol)
        key = normalized_symbol if normalized_symbol else normalized

        # Get candidate related assets
        candidates = self._discover_candidates(key)

        # Score and rank candidates
        scored = self._score_candidates(normalized, candidates, public_context)

        # Select top N assets respecting composition constraints
        selected = self._select_assets(normalized, scored)

        # Fetch data for each selected asset
        limitations: list[str] = []
        assets: list[dict] = []

        for item in selected:
            asset_data, item_limitations = self._fetch_asset_data(item, report_date)
            assets.append(asset_data)
            limitations.extend(item_limitations)

        # Build relation type summary
        relation_types = list(set(item.relation_type for item in selected))

        return {
            "symbol": normalized,
            "relation_type_summary": relation_types,
            "assets": assets,
            "limitations": limitations,
        }

    def _discover_candidates(self, symbol: str) -> list[tuple[str, str, str]]:
        """
        Discover candidate related assets.

        Returns:
            List of (asset_symbol, relation_type, reason) tuples
        """
        candidates: list[tuple[str, str, str]] = []
        seen: set[str] = set()

        # Don't include self
        normalized = _normalize_symbol(symbol)

        # 1. Add strong rules (seed assets)
        for base, linked in STRONG_RULES.items():
            base_norm = _normalize_symbol(base)
            if base_norm == normalized:
                for asset in linked:
                    asset_norm = _normalize_symbol(asset)
                    if asset_norm != normalized and asset_norm not in seen:
                        seen.add(asset_norm)
                        if _is_special_proxy(asset):
                            relation_type = "crypto_proxy"
                            reason = "比特币代理资产，美股交易时段 BTC 代理"
                        elif _is_industry_etf(asset):
                            relation_type = "industry_etf"
                            reason = "行业/主题 ETF"
                        else:
                            relation_type = "strong_business"
                            reason = "强业务关联"
                        candidates.append((asset_norm, relation_type, reason))

        # 2. Add theme-based candidates
        theme_keywords = self._extract_theme_keywords(symbol)
        if theme_keywords:
            for theme, theme_assets in THEME_RULES.items():
                if any(kw in theme.lower() for kw in theme_keywords):
                    for asset in theme_assets:
                        asset_norm = _normalize_symbol(asset)
                        if asset_norm != normalized and asset_norm not in seen:
                            seen.add(asset_norm)
                            candidates.append((asset_norm, "same_theme", f"同主题 {theme}"))

        return candidates

    def _extract_theme_keywords(self, symbol: str) -> list[str]:
        """Extract theme keywords from symbol."""
        text = symbol.upper()
        keywords = []
        if "SEMI" in text or "AMD" in text or "NVDA" in text or "INTC" in text or "QCOM" in text:
            keywords.extend(["semiconductor", "chip", "ai"])
        if "CRYPTO" in text or "COIN" in text or "GBTC" in text or "IBIT" in text:
            keywords.extend(["crypto", "bitcoin"])
        if "EV" in text or "XPEV" in text or "LI." in text or "NIO" in text:
            keywords.extend(["ev", "electric", "china"])
        if "BROKER" in text or "IBKR" in text or "SCHW" in text or "HOOD" in text:
            keywords.extend(["broker", "financial"])
        return keywords

    def _score_candidates(
        self,
        symbol: str,
        candidates: list[tuple[str, str, str]],
        public_context: dict,
    ) -> list[RelatedAssetItem]:
        """Score and rank candidate related assets."""
        scored: list[RelatedAssetItem] = []

        for asset_symbol, relation_type, reason in candidates:
            score = 0

            # Base score from relation type
            if relation_type == "crypto_proxy":
                score += SCORE_STRONG_BUSINESS
            elif relation_type == "strong_business":
                score += SCORE_STRONG_BUSINESS
            elif relation_type == "industry_etf":
                score += SCORE_SAME_INDUSTRY_ETF
            elif relation_type == "same_theme":
                score += SCORE_SAME_THEME

            # Core peer bonus
            if _is_core_peer(asset_symbol):
                score += SCORE_CORE_PEER

            # Check static info for keyword matches
            static_info = public_context.get("static_info", {})
            if static_info:
                industry = str(static_info.get("industry", "")).lower()
                if any(kw in industry for kw in ["semiconductor", "chip", "ai", "crypto", "financial"]):
                    score += SCORE_STATIC_INFO_HIT

            # Determine confidence level
            if score >= SCORE_THRESHOLD_HIGH:
                confidence = "high"
            elif score >= SCORE_THRESHOLD_MEDIUM:
                confidence = "medium"
            else:
                confidence = "low"

            # Filter out low confidence unless we don't have enough assets
            if confidence == "low" and len(scored) >= MAX_RELATED_ASSETS:
                continue

            scored.append(RelatedAssetItem(
                symbol=asset_symbol,
                relation_type=relation_type,
                reason=reason,
                confidence=confidence,
                score=score,
            ))

        # Sort by score descending
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored

    def _select_assets(self, symbol: str, candidates: list[RelatedAssetItem]) -> list[RelatedAssetItem]:
        """Select up to MAX_RELATED_ASSETS respecting composition constraints."""
        selected: list[RelatedAssetItem] = []
        industry_etf_count = 0
        core_peer_count = 0
        special_proxy_count = 0

        # Special case: MSTR must keep crypto proxies (IBIT/GBTC/COIN/BTC)
        is_mstr = symbol.upper().replace(".US", "") in ("MSTR",)

        for item in candidates:
            if len(selected) >= MAX_RELATED_ASSETS:
                break

            is_special = _is_special_proxy(item.symbol)

            # For MSTR, always include crypto proxies first
            if is_mstr and is_special:
                selected.append(item)
                special_proxy_count += 1
                continue

            # Check composition constraints
            if _is_industry_etf(item.symbol):
                if industry_etf_count >= MAX_RELATED_ASSETS:
                    continue
                industry_etf_count += 1
            elif _is_core_peer(item.symbol):
                if core_peer_count >= MAX_CORE_PEERS:
                    continue
                core_peer_count += 1
            elif is_special:
                if special_proxy_count >= MAX_SPECIAL_PROXY:
                    continue
                special_proxy_count += 1

            selected.append(item)

        return selected

    def _fetch_asset_data(
        self,
        item: RelatedAssetItem,
        report_date: str,
    ) -> tuple[dict, list[str]]:
        """Fetch public market data for a related asset."""
        symbol = item.symbol
        limitations: list[str] = []
        data_quality = "high"

        # Calculate date range for candles
        try:
            from datetime import date, timedelta
            end_date = date.fromisoformat(report_date) if report_date else date.today()
            start_date = end_date - timedelta(days=30)
            start_str = start_date.isoformat()
            end_str = end_date.isoformat()
        except Exception:
            start_str = ""
            end_str = ""

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(self._safe_fetch_candles, symbol, start_str, end_str): "candles",
                executor.submit(self._safe_fetch_quote, symbol): "quote",
                executor.submit(self._safe_fetch_calc_indexes, symbol): "calc_indexes",
                executor.submit(self._safe_fetch_news, symbol, 3): "news",
                executor.submit(self._safe_fetch_static_info, symbol): "static_info",
            }

            results: dict[str, Any] = {}
            for future in as_completed(futures):
                label = futures[future]
                try:
                    results[label] = future.result()
                except Exception as exc:
                    results[label] = None
                    limitations.append(f"{label} fetch failed for {symbol}: {exc}")

        candles = results.get("candles") or []
        quote = results.get("quote") or {}
        calc_indexes = results.get("calc_indexes") or {}
        news = results.get("news") or []
        static_info = results.get("static_info") or {}

        # Calculate day change and 14d return
        day_change = _calculate_day_change(candles)
        period_14d_return = _calculate_return_percent(candles)

        if not quote:
            data_quality = "medium"
            limitations.append(f"quote unavailable for {symbol}")
        if not news:
            limitations.append(f"news unavailable for {symbol}")

        # Build technical levels from calc_indexes
        technical_levels = {}
        if calc_indexes:
            technical_levels = {
                "pe_ttm": calc_indexes.get("pe_ttm"),
                "pb": calc_indexes.get("pb"),
                "ps_ttm": calc_indexes.get("ps_ttm"),
                "roe": calc_indexes.get("roe"),
            }

        # Compact static info
        compact_static = {}
        if static_info:
            for key in ["name", "listing_exchange", "industry", "market_cap"]:
                if key in static_info:
                    compact_static[key] = static_info[key]

        return {
            "symbol": item.symbol,
            "relation_type": item.relation_type,
            "reason": item.reason,
            "confidence": item.confidence,
            "score": item.score,
            "day_change_percent": day_change,
            "period_14d_return_percent": period_14d_return,
            "quote": quote,
            "technical_levels": technical_levels,
            "news": news[:3] if news else [],
            "static_info": compact_static,
            "data_quality": data_quality,
            "limitations": limitations,
        }, limitations

    def _safe_fetch_candles(self, symbol: str, start: str, end: str) -> list[dict]:
        try:
            response = self.longbridge_client.get_candles(symbol, start, end, "day", "forward")
            return [item.model_dump() for item in response.items]
        except (LongbridgeUnavailableError, LongbridgeExternalDataError, ValueError):
            return []

    def _safe_fetch_quote(self, symbol: str) -> dict:
        try:
            return self.longbridge_client.get_quote_snapshot(symbol)
        except (LongbridgeUnavailableError, LongbridgeExternalDataError, ValueError):
            return {}

    def _safe_fetch_calc_indexes(self, symbol: str) -> dict:
        try:
            return self.longbridge_client.get_calc_indexes(symbol)
        except (LongbridgeUnavailableError, LongbridgeExternalDataError, ValueError):
            return {}

    def _safe_fetch_news(self, symbol: str, limit: int) -> list[dict]:
        try:
            response = self.longbridge_client.get_news(symbol, limit)
            return [item.model_dump() for item in response.items]
        except (LongbridgeUnavailableError, LongbridgeExternalDataError, ValueError):
            return []

    def _safe_fetch_static_info(self, symbol: str) -> dict:
        try:
            return self.longbridge_client.get_static_info(symbol)
        except (LongbridgeUnavailableError, LongbridgeExternalDataError, ValueError):
            return {}