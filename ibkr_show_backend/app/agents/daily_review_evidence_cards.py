"""
Structured evidence cards for Daily Position Review sub-agent mode.

These cards are high-density evidence consumed by the main DailyPositionReviewAgent,
NOT directly displayed to the frontend as the final report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AccountImpactFields:
    """Core IBKR account impact fields preserved per symbol - never truncated."""
    position_weight: float | None = None
    daily_pnl: float | None = None
    daily_change_percent: float | None = None
    contribution_ratio: float | None = None
    market_value: float | None = None
    quantity: float | None = None
    average_cost: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_percent: float | None = None


@dataclass
class PriceActionFields:
    current_price: float | None = None
    previous_close: float | None = None
    day_change_percent: float | None = None
    relative_to_benchmark: str | None = None
    relative_to_sector: str | None = None


@dataclass
class NewsSummaryFields:
    key_news: list[str] = field(default_factory=list)
    catalyst: str | None = None
    sentiment: str | None = None  # positive | negative | neutral
    confidence: str | None = None  # high | medium | low


@dataclass
class ValuationSummaryFields:
    market_cap: float | None = None
    pe_ttm: float | None = None
    ps_ttm: float | None = None
    valuation_comment: str | None = None
    data_limitations: list[str] = field(default_factory=list)


@dataclass
class EarningsSummaryFields:
    latest_earnings: str | None = None
    revenue_growth: str | None = None
    profit_growth: str | None = None
    guidance: str | None = None
    data_limitations: list[str] = field(default_factory=list)


@dataclass
class TechnicalSummaryFields:
    trend: str | None = None  # bullish | bearish | neutral
    support_levels: list[str] = field(default_factory=list)
    resistance_levels: list[str] = field(default_factory=list)
    volume_signal: str | None = None
    data_limitations: list[str] = field(default_factory=list)


@dataclass
class CrossAssetSummaryFields:
    related_assets: list[str] = field(default_factory=list)
    relation_note: str | None = None
    data_limitations: list[str] = field(default_factory=list)


@dataclass
class SymbolEvidenceCard:
    """
    Evidence card for a single symbol, summarizing public解释 materials
    and combining with that symbol's IBKR account impact.
    """
    symbol: str
    normalized_symbol: str
    report_date: str

    # IBKR account impact fields - always preserved
    account_impact: AccountImpactFields = field(default_factory=AccountImpactFields)

    # Public market解释 fields - summarized by sub-agent
    price_action: PriceActionFields = field(default_factory=PriceActionFields)
    news_summary: NewsSummaryFields = field(default_factory=NewsSummaryFields)
    valuation_summary: ValuationSummaryFields = field(default_factory=ValuationSummaryFields)
    earnings_summary: EarningsSummaryFields = field(default_factory=EarningsSummaryFields)
    technical_summary: TechnicalSummaryFields = field(default_factory=TechnicalSummaryFields)
    cross_asset_summary: CrossAssetSummaryFields = field(default_factory=CrossAssetSummaryFields)

    # Synthesis
    likely_drivers: list[str] = field(default_factory=list)
    watch_points: list[str] = field(default_factory=list)

    # Quality tracking
    evidence_quality: str = "medium"  # high | medium | low
    data_limitations: list[str] = field(default_factory=list)
    source_trace: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "normalized_symbol": self.normalized_symbol,
            "report_date": self.report_date,
            "account_impact": {
                "position_weight": self.account_impact.position_weight,
                "daily_pnl": self.account_impact.daily_pnl,
                "daily_change_percent": self.account_impact.daily_change_percent,
                "contribution_ratio": self.account_impact.contribution_ratio,
                "market_value": self.account_impact.market_value,
                "quantity": self.account_impact.quantity,
                "average_cost": self.account_impact.average_cost,
                "unrealized_pnl": self.account_impact.unrealized_pnl,
                "unrealized_pnl_percent": self.account_impact.unrealized_pnl_percent,
            },
            "price_action": {
                "current_price": self.price_action.current_price,
                "previous_close": self.price_action.previous_close,
                "day_change_percent": self.price_action.day_change_percent,
                "relative_to_benchmark": self.price_action.relative_to_benchmark,
                "relative_to_sector": self.price_action.relative_to_sector,
            },
            "news_summary": {
                "key_news": self.news_summary.key_news,
                "catalyst": self.news_summary.catalyst,
                "sentiment": self.news_summary.sentiment,
                "confidence": self.news_summary.confidence,
            },
            "valuation_summary": {
                "market_cap": self.valuation_summary.market_cap,
                "pe_ttm": self.valuation_summary.pe_ttm,
                "ps_ttm": self.valuation_summary.ps_ttm,
                "valuation_comment": self.valuation_summary.valuation_comment,
                "data_limitations": self.valuation_summary.data_limitations,
            },
            "earnings_summary": {
                "latest_earnings": self.earnings_summary.latest_earnings,
                "revenue_growth": self.earnings_summary.revenue_growth,
                "profit_growth": self.earnings_summary.profit_growth,
                "guidance": self.earnings_summary.guidance,
                "data_limitations": self.earnings_summary.data_limitations,
            },
            "technical_summary": {
                "trend": self.technical_summary.trend,
                "support_levels": self.technical_summary.support_levels,
                "resistance_levels": self.technical_summary.resistance_levels,
                "volume_signal": self.technical_summary.volume_signal,
                "data_limitations": self.technical_summary.data_limitations,
            },
            "cross_asset_summary": {
                "related_assets": self.cross_asset_summary.related_assets,
                "relation_note": self.cross_asset_summary.relation_note,
                "data_limitations": self.cross_asset_summary.data_limitations,
            },
            "likely_drivers": self.likely_drivers,
            "watch_points": self.watch_points,
            "evidence_quality": self.evidence_quality,
            "data_limitations": self.data_limitations,
            "source_trace": self.source_trace,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SymbolEvidenceCard:
        ai = data.get("account_impact", {})
        pa = data.get("price_action", {})
        ns = data.get("news_summary", {})
        vs = data.get("valuation_summary", {})
        es = data.get("earnings_summary", {})
        ts = data.get("technical_summary", {})
        cas = data.get("cross_asset_summary", {})

        return cls(
            symbol=str(data.get("symbol", "")),
            normalized_symbol=str(data.get("normalized_symbol", "")),
            report_date=str(data.get("report_date", "")),
            account_impact=AccountImpactFields(
                position_weight=ai.get("position_weight"),
                daily_pnl=ai.get("daily_pnl"),
                daily_change_percent=ai.get("daily_change_percent"),
                contribution_ratio=ai.get("contribution_ratio"),
                market_value=ai.get("market_value"),
                quantity=ai.get("quantity"),
                average_cost=ai.get("average_cost"),
                unrealized_pnl=ai.get("unrealized_pnl"),
                unrealized_pnl_percent=ai.get("unrealized_pnl_percent"),
            ),
            price_action=PriceActionFields(
                current_price=pa.get("current_price"),
                previous_close=pa.get("previous_close"),
                day_change_percent=pa.get("day_change_percent"),
                relative_to_benchmark=pa.get("relative_to_benchmark"),
                relative_to_sector=pa.get("relative_to_sector"),
            ),
            news_summary=NewsSummaryFields(
                key_news=ns.get("key_news", []),
                catalyst=ns.get("catalyst"),
                sentiment=ns.get("sentiment"),
                confidence=ns.get("confidence"),
            ),
            valuation_summary=ValuationSummaryFields(
                market_cap=vs.get("market_cap"),
                pe_ttm=vs.get("pe_ttm"),
                ps_ttm=vs.get("ps_ttm"),
                valuation_comment=vs.get("valuation_comment"),
                data_limitations=vs.get("data_limitations", []),
            ),
            earnings_summary=EarningsSummaryFields(
                latest_earnings=es.get("latest_earnings"),
                revenue_growth=es.get("revenue_growth"),
                profit_growth=es.get("profit_growth"),
                guidance=es.get("guidance"),
                data_limitations=es.get("data_limitations", []),
            ),
            technical_summary=TechnicalSummaryFields(
                trend=ts.get("trend"),
                support_levels=ts.get("support_levels", []),
                resistance_levels=ts.get("resistance_levels", []),
                volume_signal=ts.get("volume_signal"),
                data_limitations=ts.get("data_limitations", []),
            ),
            cross_asset_summary=CrossAssetSummaryFields(
                related_assets=cas.get("related_assets", []),
                relation_note=cas.get("relation_note"),
                data_limitations=cas.get("data_limitations", []),
            ),
            likely_drivers=data.get("likely_drivers", []),
            watch_points=data.get("watch_points", []),
            evidence_quality=data.get("evidence_quality", "medium"),
            data_limitations=data.get("data_limitations", []),
            source_trace=data.get("source_trace", []),
        )


@dataclass
class MacroEvidenceCard:
    """
    Evidence card for macro market context.
    Generated once per daily review.
    """
    report_date: str
    benchmark_context: dict = field(default_factory=dict)
    market_regime: str | None = None  # risk_on | risk_off | mixed
    sector_context: str | None = None
    macro_events: list[str] = field(default_factory=list)
    rate_fx_context: str | None = None
    risk_sentiment: str | None = None  # risk_on | risk_off | neutral
    tech_sentiment: str | None = None
    data_limitations: list[str] = field(default_factory=list)
    source_trace: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "report_date": self.report_date,
            "benchmark_context": self.benchmark_context,
            "market_regime": self.market_regime,
            "sector_context": self.sector_context,
            "macro_events": self.macro_events,
            "rate_fx_context": self.rate_fx_context,
            "risk_sentiment": self.risk_sentiment,
            "tech_sentiment": self.tech_sentiment,
            "data_limitations": self.data_limitations,
            "source_trace": self.source_trace,
        }

    @classmethod
    def from_dict(cls, data: dict) -> MacroEvidenceCard:
        return cls(
            report_date=str(data.get("report_date", "")),
            benchmark_context=data.get("benchmark_context", {}),
            market_regime=data.get("market_regime"),
            sector_context=data.get("sector_context"),
            macro_events=data.get("macro_events", []),
            rate_fx_context=data.get("rate_fx_context"),
            risk_sentiment=data.get("risk_sentiment"),
            tech_sentiment=data.get("tech_sentiment"),
            data_limitations=data.get("data_limitations", []),
            source_trace=data.get("source_trace", []),
        )


@dataclass
class DataQualitySummary:
    """Summary of data quality for the entire card pack."""
    overall: str = "medium"  # high | medium | low
    warnings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "warnings": self.warnings,
            "limitations": self.limitations,
        }


@dataclass
class EvidenceCardSummary:
    """Lightweight summary of card pack for email/display."""
    symbol_count: int = 0
    macro_card_present: bool = False
    fallback_card_count: int = 0
    quality: str = "medium"
    key_drivers: list[str] = field(default_factory=list)
    key_watch_points: list[str] = field(default_factory=list)
    limitations_count: int = 0

    def to_dict(self) -> dict:
        return {
            "symbol_count": self.symbol_count,
            "macro_card_present": self.macro_card_present,
            "fallback_card_count": self.fallback_card_count,
            "quality": self.quality,
            "key_drivers": self.key_drivers,
            "key_watch_points": self.key_watch_points,
            "limitations_count": self.limitations_count,
        }


@dataclass
class SubAgentTrace:
    """Trace of sub-agent invocations."""
    symbol_agent_calls: list[dict] = field(default_factory=list)
    macro_agent_calls: list[dict] = field(default_factory=list)
    fallback_reasons: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol_agent_calls": self.symbol_agent_calls,
            "macro_agent_calls": self.macro_agent_calls,
            "fallback_reasons": self.fallback_reasons,
            "errors": self.errors,
        }


@dataclass
class DailyReviewEvidenceCardPack:
    """
    Container for all evidence cards for one daily position review.
    Produced by DailyReviewEvidenceCardBuilder, consumed by main agent.
    """
    report_date: str

    # Core IBKR facts - always complete, never fallback
    account_facts: dict = field(default_factory=dict)
    position_facts: list[dict] = field(default_factory=list)
    rankings: dict = field(default_factory=dict)
    risk: dict = field(default_factory=dict)
    attribution_quality: dict = field(default_factory=dict)

    # Cards
    symbol_cards: list[SymbolEvidenceCard] = field(default_factory=list)
    macro_card: MacroEvidenceCard | None = None

    # Quality tracking
    data_quality: DataQualitySummary = field(default_factory=DataQualitySummary)
    evidence_used: list[str] = field(default_factory=list)
    subagent_trace: SubAgentTrace = field(default_factory=SubAgentTrace)
    budget_report: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "report_date": self.report_date,
            "account_facts": self.account_facts,
            "position_facts": self.position_facts,
            "rankings": self.rankings,
            "risk": self.risk,
            "attribution_quality": self.attribution_quality,
            "symbol_cards": [card.to_dict() for card in self.symbol_cards],
            "macro_card": self.macro_card.to_dict() if self.macro_card else None,
            "data_quality": self.data_quality.to_dict(),
            "evidence_used": self.evidence_used,
            "subagent_trace": self.subagent_trace.to_dict(),
            "budget_report": self.budget_report,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DailyReviewEvidenceCardPack:
        dq = data.get("data_quality", {})
        st = data.get("subagent_trace", {})

        symbol_cards = []
        for card_data in data.get("symbol_cards", []):
            if isinstance(card_data, dict):
                symbol_cards.append(SymbolEvidenceCard.from_dict(card_data))
            elif isinstance(card_data, SymbolEvidenceCard):
                symbol_cards.append(card_data)

        macro_card = None
        if data.get("macro_card"):
            if isinstance(data["macro_card"], dict):
                macro_card = MacroEvidenceCard.from_dict(data["macro_card"])
            elif isinstance(data["macro_card"], MacroEvidenceCard):
                macro_card = data["macro_card"]

        return cls(
            report_date=str(data.get("report_date", "")),
            account_facts=data.get("account_facts", {}),
            position_facts=data.get("position_facts", []),
            rankings=data.get("rankings", {}),
            risk=data.get("risk", {}),
            attribution_quality=data.get("attribution_quality", {}),
            symbol_cards=symbol_cards,
            macro_card=macro_card,
            data_quality=DataQualitySummary(
                overall=dq.get("overall", "medium"),
                warnings=dq.get("warnings", []),
                limitations=dq.get("limitations", []),
            ),
            evidence_used=data.get("evidence_used", []),
            subagent_trace=SubAgentTrace(
                symbol_agent_calls=st.get("symbol_agent_calls", []),
                macro_agent_calls=st.get("macro_agent_calls", []),
                fallback_reasons=st.get("fallback_reasons", []),
                errors=st.get("errors", []),
            ),
            budget_report=data.get("budget_report", {}),
        )


def build_fallback_symbol_card(
    symbol: str,
    normalized_symbol: str,
    report_date: str,
    position_item: dict,
    reason: str,
) -> SymbolEvidenceCard:
    """
    Build a minimal fallback card when sub-agent fails for a symbol.
    Preserves all IBKR account impact fields, marks public data as unavailable.
    """
    return SymbolEvidenceCard(
        symbol=symbol,
        normalized_symbol=normalized_symbol,
        report_date=report_date,
        account_impact=AccountImpactFields(
            position_weight=position_item.get("weight"),
            daily_pnl=position_item.get("daily_pnl"),
            daily_change_percent=position_item.get("daily_change_percent"),
            contribution_ratio=position_item.get("contribution_ratio"),
            market_value=position_item.get("market_value"),
            quantity=position_item.get("quantity"),
            average_cost=position_item.get("average_cost"),
            unrealized_pnl=position_item.get("unrealized_pnl"),
            unrealized_pnl_percent=position_item.get("unrealized_pnl_percent"),
        ),
        price_action=PriceActionFields(),
        news_summary=NewsSummaryFields(),
        valuation_summary=ValuationSummaryFields(
            data_limitations=[f"subagent_failed: {reason}"]
        ),
        earnings_summary=EarningsSummaryFields(
            data_limitations=[f"subagent_failed: {reason}"]
        ),
        technical_summary=TechnicalSummaryFields(
            data_limitations=[f"subagent_failed: {reason}"]
        ),
        cross_asset_summary=CrossAssetSummaryFields(
            data_limitations=[f"subagent_failed: {reason}"]
        ),
        likely_drivers=[],
        watch_points=["sub-agent failed - public解释材料不可用，需在完整每日复盘中手动确认"],
        evidence_quality="low",
        data_limitations=[f"source_missing: public解释材料生成失败，原因: {reason}"],
        source_trace=[f"fallback_card: {reason}"],
    )


def build_fallback_macro_card(
    report_date: str,
    benchmark_context: dict,
    reason: str,
) -> MacroEvidenceCard:
    """Build a minimal fallback card when macro sub-agent fails."""
    return MacroEvidenceCard(
        report_date=report_date,
        benchmark_context=benchmark_context,
        market_regime=None,
        sector_context=None,
        macro_events=[],
        rate_fx_context=None,
        risk_sentiment=None,
        tech_sentiment=None,
        data_limitations=[f"source_missing: macro解释材料生成失败，原因: {reason}"],
        source_trace=[f"fallback_card: {reason}"],
    )


def compute_card_pack_summary(pack: DailyReviewEvidenceCardPack) -> EvidenceCardSummary:
    """Build a lightweight summary of a card pack for email/display."""
    symbol_count = len(pack.symbol_cards)
    fallback_count = sum(1 for card in pack.symbol_cards if card.evidence_quality == "low")
    limitations_count = sum(len(card.data_limitations) for card in pack.symbol_cards)
    if pack.macro_card:
        limitations_count += len(pack.macro_card.data_limitations)

    all_drivers: list[str] = []
    all_watch_points: list[str] = []
    for card in pack.symbol_cards:
        all_drivers.extend(card.likely_drivers[:2])
        all_watch_points.extend(card.watch_points[:2])

    return EvidenceCardSummary(
        symbol_count=symbol_count,
        macro_card_present=pack.macro_card is not None,
        fallback_card_count=fallback_count,
        quality=pack.data_quality.overall,
        key_drivers=all_drivers[:6],
        key_watch_points=all_watch_points[:6],
        limitations_count=limitations_count,
    )