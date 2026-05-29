"""
Orchestrator for building DailyReviewEvidenceCardPack.

Responsibilities:
- Receive deterministic_context from DailyPositionReviewService
- Select focus symbols using priority logic
- Call sub-agents in parallel to generate symbol evidence cards
- Call macro sub-agent to generate macro card
- Assemble into DailyReviewEvidenceCardPack
- Handle sub-agent failures gracefully with fallback cards
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from typing import Any

from app.agents.daily_review_evidence_cards import (
    DailyReviewEvidenceCardPack,
    DataQualitySummary,
    SubAgentTrace,
    SymbolEvidenceCard,
    build_fallback_macro_card,
    build_fallback_symbol_card,
    compute_card_pack_summary,
)
from app.services.daily_review_macro_evidence_agent import DailyReviewMacroEvidenceAgent
from app.services.daily_review_related_asset_service import DailyReviewRelatedAssetService
from app.services.daily_review_symbol_evidence_agent import DailyReviewSymbolEvidenceAgent
from app.services.llm_service import LLMService
from app.services.longbridge_service import LongbridgeExternalDataClient


DAILY_REVIEW_SYMBOL_CARD_LIMIT = int(os.getenv("DAILY_REVIEW_SYMBOL_CARD_LIMIT", "6"))


# Special linkage symbols that require cross-asset context
SPECIAL_LINKAGE_SYMBOLS = {
    "MSTR.US": ["BTC.X", "GBTC.US", "IBIT.US"],
    "MSTR": ["BTC.X", "GBTC.US", "IBIT.US"],
    "XIACY.US": ["1810.HK", "XPEV.US", "LI.US"],
    "XIACY": ["1810.HK", "XPEV.US", "LI.US"],
    "TSLA.US": ["RIVN.US", "NIO.US", "TM.US"],
    "TSLA": ["RIVN.US", "NIO.US", "TM.US"],
    "AMD.US": ["NVDA.US", "INTC.US", "SMH.US", "QCOM.US", "AVGO.US", "SMCI.US"],
    "AMD": ["NVDA.US", "INTC.US", "SMH.US", "QCOM.US", "AVGO.US", "SMCI.US"],
    "INTC.US": ["AMD.US", "NVDA.US", "SMH.US", "QCOM.US"],
    "INTC": ["AMD.US", "NVDA.US", "SMH.US", "QCOM.US"],
    "QCOM.US": ["AMD.US", "NVDA.US", "SMH.US", "AVGO.US"],
    "QCOM": ["AMD.US", "NVDA.US", "SMH.US", "AVGO.US"],
    "SMCI.US": ["AMD.US", "NVDA.US", "SMH.US", "AVGO.US"],
    "SMCI": ["AMD.US", "NVDA.US", "SMH.US", "AVGO.US"],
    "MSFT.US": ["META.US", "GOOGL.US", "AMZN.US", "QQQ.US"],
    "MSFT": ["META.US", "GOOGL.US", "AMZN.US", "QQQ.US"],
    "META.US": ["MSFT.US", "GOOGL.US", "AMZN.US", "QQQ.US"],
    "META": ["MSFT.US", "GOOGL.US", "AMZN.US", "QQQ.US"],
    "GOOGL.US": ["MSFT.US", "META.US", "AMZN.US", "QQQ.US"],
    "GOOGL": ["MSFT.US", "META.US", "AMZN.US", "QQQ.US"],
    "AMZN.US": ["MSFT.US", "META.US", "GOOGL.US", "QQQ.US"],
    "AMZN": ["MSFT.US", "META.US", "GOOGL.US", "QQQ.US"],
}


def _is_special_linkage_symbol(symbol: str) -> bool:
    normalized = symbol.upper()
    return normalized in SPECIAL_LINKAGE_SYMBOLS or normalized.replace(".US", "") in SPECIAL_LINKAGE_SYMBOLS


def _select_focus_symbols_for_cards(
    positions: list[dict],
    rankings: dict,
    report_date: str,
    limit: int = DAILY_REVIEW_SYMBOL_CARD_LIMIT,
) -> list[dict]:
    """
    Select focus symbols for evidence card generation using priority logic:
    1. PnL absolute value largest contributor/drag
    2. Largest weight
    3. Abnormal daily change percent
    4. Symbols with trades on this date (if available)
    5. Risk exposure related (semiconductor/AI/tech theme)
    6. Special linkage symbols (MSTR, XIACY, TSLA, etc.)

    Default max 6 symbol cards.
    """
    if not positions:
        return []

    selected: list[tuple[float, int, dict]] = []  # (score, original_index, position_item)
    special_seen: set[str] = set()

    for idx, item in enumerate(positions):
        symbol = str(item.get("symbol", "")).upper()
        normalized = str(item.get("normalized_symbol", symbol)).upper()
        score = 0.0

        # 1. PnL absolute value largest
        score += abs(item.get("daily_pnl") or 0.0) / 100.0

        # 2. Largest weight
        score += (item.get("weight") or 0.0) * 100.0

        # 3. Abnormal daily change percent
        change_pct = abs(item.get("daily_change_percent") or 0.0)
        if change_pct > 5.0:
            score += 30.0
        elif change_pct > 3.0:
            score += 15.0

        # 4. Major contributor or drag
        if item.get("is_major_contributor") or item.get("is_major_drag"):
            score += 50.0

        # 5. Special linkage symbols get a permanent boost
        if _is_special_linkage_symbol(symbol) or _is_special_linkage_symbol(normalized):
            score += 40.0
            special_seen.add(normalized)

        selected.append((score, idx, item))

    # Sort by score descending
    selected.sort(reverse=True, key=lambda x: (x[0], -x[1]))

    # Deduplicate by normalized symbol, keeping highest score
    seen: set[str] = set()
    result: list[dict] = []
    for score, idx, item in selected:
        if len(result) >= limit:
            break
        normalized = str(item.get("normalized_symbol", item.get("symbol", ""))).upper()
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(item)

    return result


class DailyReviewEvidenceCardBuilder:
    def __init__(
        self,
        llm_service: LLMService,
        symbol_agent: DailyReviewSymbolEvidenceAgent | None = None,
        macro_agent: DailyReviewMacroEvidenceAgent | None = None,
        related_asset_service: DailyReviewRelatedAssetService | None = None,
        longbridge_client: LongbridgeExternalDataClient | None = None,
    ) -> None:
        self.llm_service = llm_service
        self.symbol_agent = symbol_agent or DailyReviewSymbolEvidenceAgent(llm_service)
        self.macro_agent = macro_agent or DailyReviewMacroEvidenceAgent(llm_service)
        self.related_asset_service = related_asset_service
        self.longbridge_client = longbridge_client

    def build_card_pack(
        self,
        deterministic_context: dict,
    ) -> DailyReviewEvidenceCardPack:
        """DEPRECATED: Use DailyPositionReviewGraphRunner instead."""
        raise RuntimeError("deprecated; use DailyPositionReviewGraphRunner")
        report_date = str(deterministic_context.get("report_date", ""))
        positions = deterministic_context.get("positions", [])
        rankings = deterministic_context.get("rankings", {})
        risk = deterministic_context.get("risk", {})
        overview = deterministic_context.get("overview", {})
        attribution_quality = deterministic_context.get("attribution_quality", {})
        benchmarks = deterministic_context.get("benchmarks", {})
        focus_symbols = deterministic_context.get("focus_symbols", [])
        symbol_public_context = deterministic_context.get("symbol_public_context", {})
        data_quality_ctx = deterministic_context.get("data_quality", {})

        # Select focus symbols for cards
        focus_position_items = _select_focus_symbols_for_cards(
            positions=positions,
            rankings=rankings,
            report_date=report_date,
            limit=DAILY_REVIEW_SYMBOL_CARD_LIMIT,
        )

        # Build account facts (core IBKR facts - always complete)
        account_facts = {
            "report_date": report_date,
            "overview": overview,
            "attribution_quality": attribution_quality,
            "data_quality": data_quality_ctx,
        }

        trace = SubAgentTrace()
        warnings: list[str] = []
        limitations: list[str] = []

        # Generate symbol cards in parallel
        symbol_cards = self._generate_symbol_cards(
            focus_position_items=focus_position_items,
            report_date=report_date,
            symbol_public_context=symbol_public_context,
            benchmark_context=benchmarks,
            trace=trace,
            warnings=warnings,
        )

        # Generate macro card
        macro_card = self._generate_macro_card(
            report_date=report_date,
            benchmark_context=benchmarks,
            focus_symbols=focus_symbols,
            account_return=overview.get("daily_return_percent"),
            symbol_public_context=symbol_public_context,
            trace=trace,
            warnings=warnings,
        )

        # Assess overall data quality
        quality_overall = "high"
        if any(card.evidence_quality == "low" for card in symbol_cards):
            quality_overall = "medium"
        if sum(1 for card in symbol_cards if card.evidence_quality == "low") > len(symbol_cards) // 2:
            quality_overall = "low"

        data_quality = DataQualitySummary(
            overall=quality_overall,
            warnings=warnings,
            limitations=limitations,
        )

        evidence_used = [
            "IBKR account snapshot: deterministic",
            "IBKR position snapshot: deterministic",
            "IBKR rankings: deterministic",
            "IBKR risk analysis: deterministic",
            f"Longbridge public context: {len(symbol_public_context)} symbols",
            f"Sub-agent symbol cards: {len(symbol_cards)} cards generated",
            f"Sub-agent macro card: {'yes' if macro_card else 'no'}",
        ]

        budget_report = {
            "symbol_cards_count": len(symbol_cards),
            "focus_position_items_count": len(focus_position_items),
            "macro_card_present": macro_card is not None,
            "fallback_symbol_cards": sum(1 for card in symbol_cards if card.evidence_quality == "low"),
        }

        pack = DailyReviewEvidenceCardPack(
            report_date=report_date,
            account_facts=account_facts,
            position_facts=positions,
            rankings=rankings,
            risk=risk,
            attribution_quality=attribution_quality,
            symbol_cards=symbol_cards,
            macro_card=macro_card,
            data_quality=data_quality,
            evidence_used=evidence_used,
            subagent_trace=trace,
            budget_report=budget_report,
        )

        return pack

    def _generate_symbol_cards(
        self,
        focus_position_items: list[dict],
        report_date: str,
        symbol_public_context: dict,
        benchmark_context: dict,
        trace: SubAgentTrace,
        warnings: list[str],
    ) -> list[SymbolEvidenceCard]:
        """Generate symbol cards in parallel, with fallback on failure."""
        if not focus_position_items:
            return []

        cards: list[SymbolEvidenceCard] = []
        errors: list[str] = []

        with ThreadPoolExecutor(max_workers=min(len(focus_position_items), 4)) as executor:
            futures = {}
            for item in focus_position_items:
                symbol = str(item.get("symbol", ""))
                normalized = str(item.get("normalized_symbol", symbol))
                public_ctx = symbol_public_context.get(normalized, symbol_public_context.get(symbol, {}))

                # Build related asset context if service is available
                if self.related_asset_service is not None:
                    try:
                        related_asset_context = self.related_asset_service.build_related_asset_context(
                            symbol=symbol,
                            normalized_symbol=normalized,
                            report_date=report_date,
                            public_context=public_ctx,
                            benchmark_context=benchmark_context,
                        )
                        public_ctx = {**public_ctx, "related_asset_context": related_asset_context}
                    except Exception as exc:
                        # If related asset context fails, continue without it
                        pass

                future = executor.submit(
                    self.symbol_agent.generate_symbol_card,
                    report_date=report_date,
                    symbol=symbol,
                    normalized_symbol=normalized,
                    position_item=item,
                    public_context=public_ctx,
                    benchmark_context=benchmark_context,
                )
                futures[future] = (symbol, normalized, item)

            for future in as_completed(futures):
                symbol, normalized, item = futures[future]
                try:
                    card = future.result()
                    cards.append(card)
                    trace.symbol_agent_calls.append({
                        "symbol": symbol,
                        "normalized_symbol": normalized,
                        "status": "success",
                        "quality": card.evidence_quality,
                    })
                except Exception as exc:
                    fallback_card = build_fallback_symbol_card(
                        symbol=symbol,
                        normalized_symbol=normalized,
                        report_date=report_date,
                        position_item=item,
                        reason=str(exc)[:200],
                    )
                    cards.append(fallback_card)
                    errors.append(f"Symbol card failed for {symbol}: {exc}")
                    trace.symbol_agent_calls.append({
                        "symbol": symbol,
                        "normalized_symbol": normalized,
                        "status": "fallback",
                        "error": str(exc)[:200],
                    })
                    trace.fallback_reasons.append(f"symbol:{symbol}:{str(exc)[:100]}")

        for err in errors:
            warnings.append(err)
            trace.errors.append(err)

        return cards

    def _generate_macro_card(
        self,
        report_date: str,
        benchmark_context: dict,
        focus_symbols: list[str],
        account_return: float | None,
        symbol_public_context: dict,
        trace: SubAgentTrace,
        warnings: list[str],
    ):
        """Generate macro card, with fallback on failure."""
        macro_news_context = None
        if self.longbridge_client is not None:
            try:
                macro_news_context = self._fetch_macro_news_context(focus_symbols)
            except Exception as exc:
                warnings.append(f"Macro news context fetch failed: {exc}")
                macro_news_context = None

        try:
            macro_card = self.macro_agent.generate_macro_card(
                report_date=report_date,
                benchmark_context=benchmark_context,
                focus_symbols=focus_symbols,
                account_return=account_return,
                macro_news_context=macro_news_context,
            )
            trace.macro_agent_calls.append({
                "report_date": report_date,
                "status": "success",
            })
            return macro_card
        except Exception as exc:
            fallback_card = build_fallback_macro_card(
                report_date=report_date,
                benchmark_context=benchmark_context,
                reason=str(exc)[:200],
            )
            trace.macro_agent_calls.append({
                "report_date": report_date,
                "status": "fallback",
                "error": str(exc)[:200],
            })
            trace.fallback_reasons.append(f"macro:{str(exc)[:100]}")
            warnings.append(f"Macro card failed: {exc}")
            trace.errors.append(f"Macro card failed: {exc}")
            return fallback_card

    def _fetch_macro_news_context(self, focus_symbols: list[str]) -> dict:
        """
        Fetch macro news context using Longbridge search_macro_news.
        Searches for market, Fed, rate, inflation, CPI, Nasdaq, semiconductor, AI, crypto, tech, China tech.
        """
        if self.longbridge_client is None:
            return {}

        keywords = [
            "market",
            "Fed",
            "rate",
            "inflation",
            "CPI",
            "Nasdaq",
            "semiconductor",
            "AI",
            "crypto",
            "tech",
            "China tech",
        ]

        all_items: list[dict] = []
        seen_ids: set[str] = set()

        for keyword in keywords:
            try:
                response = self.longbridge_client.search_macro_news(keyword=keyword, limit=5)
                for item in response.items:
                    if item.id not in seen_ids:
                        seen_ids.add(item.id)
                        all_items.append(item.model_dump())
            except Exception:
                # If one keyword fails, continue with others
                pass

        # Sort by publish time descending and take top 20
        all_items.sort(key=lambda x: x.get("publish_time", ""), reverse=True)
        return {
            "macro_news": all_items[:20],
            "keywords_searched": keywords,
        }