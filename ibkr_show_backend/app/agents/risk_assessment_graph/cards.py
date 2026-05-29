"""Risk Assessment cards - dataclasses for account-level risk evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RiskLevel:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


@dataclass
class PositionEntry:
    symbol: str
    normalized_symbol: str
    quantity: float = 0.0
    avg_cost: float | None = None
    current_price: float | None = None
    market_value: float = 0.0
    position_pct: float = 0.0
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "normalized_symbol": self.normalized_symbol,
            "quantity": self.quantity,
            "avg_cost": self.avg_cost,
            "current_price": self.current_price,
            "market_value": self.market_value,
            "position_pct": self.position_pct,
            "unrealized_pnl": self.unrealized_pnl,
            "unrealized_pnl_pct": self.unrealized_pnl_pct,
        }


@dataclass
class AccountRiskSnapshot:
    """Account-level risk snapshot from IBKR only. Never calls MCP/Longbridge."""
    net_liquidation: float | None = None
    cash: float | None = None
    deployable_liquidity: float | None = None
    margin_info: dict | None = None
    positions: list[PositionEntry] = field(default_factory=list)
    total_position_value: float = 0.0
    top_positions: list[dict] = field(default_factory=list)
    position_count: int = 0
    largest_position_pct: float = 0.0
    top_3_position_pct: float = 0.0
    top_5_position_pct: float = 0.0
    cash_pct: float = 0.0
    margin_usage_pct: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    data_quality: dict = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "net_liquidation": self.net_liquidation,
            "cash": self.cash,
            "deployable_liquidity": self.deployable_liquidity,
            "margin_info": self.margin_info,
            "positions": [p.to_dict() for p in self.positions],
            "total_position_value": self.total_position_value,
            "top_positions": self.top_positions,
            "position_count": self.position_count,
            "largest_position_pct": self.largest_position_pct,
            "top_3_position_pct": self.top_3_position_pct,
            "top_5_position_pct": self.top_5_position_pct,
            "cash_pct": self.cash_pct,
            "margin_usage_pct": self.margin_usage_pct,
            "unrealized_pnl": self.unrealized_pnl,
            "unrealized_pnl_pct": self.unrealized_pnl_pct,
            "data_quality": self.data_quality,
            "created_at": self.created_at or _now_iso(),
        }


@dataclass
class ConcentrationRiskCard:
    card_type: str = "concentration_risk"
    summary: str = ""
    score: float = 0  # risk score: 0=low risk, 100=extreme risk
    max_score: float = 25
    risk_level: str = RiskLevel.LOW
    largest_position_pct: float = 0.0
    top_3_position_pct: float = 0.0
    top_5_position_pct: float = 0.0
    concentration_findings: list[str] = field(default_factory=list)
    key_risks: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    data_limitations: list[str] = field(default_factory=list)
    evidence_quality: str = "high"
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "card_type": self.card_type,
            "summary": self.summary,
            "score": self.score,
            "max_score": self.max_score,
            "risk_level": self.risk_level,
            "largest_position_pct": self.largest_position_pct,
            "top_3_position_pct": self.top_3_position_pct,
            "top_5_position_pct": self.top_5_position_pct,
            "concentration_findings": self.concentration_findings,
            "key_risks": self.key_risks,
            "suggested_actions": self.suggested_actions,
            "data_limitations": self.data_limitations,
            "evidence_quality": self.evidence_quality,
            "created_at": self.created_at or _now_iso(),
        }


@dataclass
class SectorThemeExposureCard:
    card_type: str = "sector_theme_exposure"
    summary: str = ""
    score: float = 0
    max_score: float = 20
    risk_level: str = RiskLevel.LOW
    sector_exposures: dict = field(default_factory=dict)
    theme_exposures: dict = field(default_factory=dict)
    ai_exposure_pct: float = 0.0
    semiconductor_exposure_pct: float = 0.0
    china_exposure_pct: float = 0.0
    mega_cap_tech_exposure_pct: float = 0.0
    unknown_exposure_pct: float = 0.0
    key_risks: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    source_tools: list[str] = field(default_factory=list)
    data_limitations: list[str] = field(default_factory=list)
    evidence_quality: str = "low"
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "card_type": self.card_type,
            "summary": self.summary,
            "score": self.score,
            "max_score": self.max_score,
            "risk_level": self.risk_level,
            "sector_exposures": self.sector_exposures,
            "theme_exposures": self.theme_exposures,
            "ai_exposure_pct": self.ai_exposure_pct,
            "semiconductor_exposure_pct": self.semiconductor_exposure_pct,
            "china_exposure_pct": self.china_exposure_pct,
            "mega_cap_tech_exposure_pct": self.mega_cap_tech_exposure_pct,
            "unknown_exposure_pct": self.unknown_exposure_pct,
            "key_risks": self.key_risks,
            "suggested_actions": self.suggested_actions,
            "source_tools": self.source_tools,
            "data_limitations": self.data_limitations,
            "evidence_quality": self.evidence_quality,
            "created_at": self.created_at or _now_iso(),
        }


@dataclass
class CorrelationRiskCard:
    card_type: str = "correlation_risk"
    summary: str = ""
    score: float = 0
    max_score: float = 20
    risk_level: str = RiskLevel.LOW
    high_correlation_groups: list[dict] = field(default_factory=list)
    estimated_portfolio_correlation: float = 0.0
    correlation_notes: str = ""
    key_risks: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    source_tools: list[str] = field(default_factory=list)
    data_limitations: list[str] = field(default_factory=list)
    evidence_quality: str = "low"
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "card_type": self.card_type,
            "summary": self.summary,
            "score": self.score,
            "max_score": self.max_score,
            "risk_level": self.risk_level,
            "high_correlation_groups": self.high_correlation_groups,
            "estimated_portfolio_correlation": self.estimated_portfolio_correlation,
            "correlation_notes": self.correlation_notes,
            "key_risks": self.key_risks,
            "suggested_actions": self.suggested_actions,
            "source_tools": self.source_tools,
            "data_limitations": self.data_limitations,
            "evidence_quality": self.evidence_quality,
            "created_at": self.created_at or _now_iso(),
        }


@dataclass
class EarningsCalendarRiskCard:
    card_type: str = "earnings_calendar_risk"
    summary: str = ""
    score: float = 0
    max_score: float = 15
    risk_level: str = RiskLevel.LOW
    upcoming_earnings: list[dict] = field(default_factory=list)
    near_term_event_exposure_pct: float = 0.0
    high_event_risk_symbols: list[str] = field(default_factory=list)
    key_risks: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    source_tools: list[str] = field(default_factory=list)
    data_limitations: list[str] = field(default_factory=list)
    evidence_quality: str = "low"
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "card_type": self.card_type,
            "summary": self.summary,
            "score": self.score,
            "max_score": self.max_score,
            "risk_level": self.risk_level,
            "upcoming_earnings": self.upcoming_earnings,
            "near_term_event_exposure_pct": self.near_term_event_exposure_pct,
            "high_event_risk_symbols": self.high_event_risk_symbols,
            "key_risks": self.key_risks,
            "suggested_actions": self.suggested_actions,
            "source_tools": self.source_tools,
            "data_limitations": self.data_limitations,
            "evidence_quality": self.evidence_quality,
            "created_at": self.created_at or _now_iso(),
        }


@dataclass
class StressTestCard:
    card_type: str = "stress_test"
    summary: str = ""
    score: float = 0
    max_score: float = 20
    risk_level: str = RiskLevel.LOW
    scenarios: list[dict] = field(default_factory=list)
    worst_case_drawdown_pct: float = 0.0
    worst_case_loss_amount: float = 0.0
    liquidity_after_stress: float = 0.0
    margin_risk_after_stress: str = "none"
    key_risks: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    data_limitations: list[str] = field(default_factory=list)
    evidence_quality: str = "high"
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "card_type": self.card_type,
            "summary": self.summary,
            "score": self.score,
            "max_score": self.max_score,
            "risk_level": self.risk_level,
            "scenarios": self.scenarios,
            "worst_case_drawdown_pct": self.worst_case_drawdown_pct,
            "worst_case_loss_amount": self.worst_case_loss_amount,
            "liquidity_after_stress": self.liquidity_after_stress,
            "margin_risk_after_stress": self.margin_risk_after_stress,
            "key_risks": self.key_risks,
            "suggested_actions": self.suggested_actions,
            "data_limitations": self.data_limitations,
            "evidence_quality": self.evidence_quality,
            "created_at": self.created_at or _now_iso(),
        }


@dataclass
class RiskAssessmentCardPack:
    account_risk_snapshot: AccountRiskSnapshot | None = None
    concentration_card: ConcentrationRiskCard | None = None
    sector_theme_card: SectorThemeExposureCard | None = None
    correlation_card: CorrelationRiskCard | None = None
    earnings_calendar_card: EarningsCalendarRiskCard | None = None
    stress_test_card: StressTestCard | None = None
    data_quality_summary: str = "medium"
    node_traces: list[dict] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "account_risk_snapshot": self.account_risk_snapshot.to_dict() if self.account_risk_snapshot else None,
            "concentration_card": self.concentration_card.to_dict() if self.concentration_card else None,
            "sector_theme_card": self.sector_theme_card.to_dict() if self.sector_theme_card else None,
            "correlation_card": self.correlation_card.to_dict() if self.correlation_card else None,
            "earnings_calendar_card": self.earnings_calendar_card.to_dict() if self.earnings_calendar_card else None,
            "stress_test_card": self.stress_test_card.to_dict() if self.stress_test_card else None,
            "data_quality_summary": self.data_quality_summary,
            "created_at": self.created_at or _now_iso(),
        }


# --- Fallback card builders ---

def build_fallback_concentration_card(reason: str) -> ConcentrationRiskCard:
    return ConcentrationRiskCard(
        summary=f"仓位集中度评估不可用：{reason[:100]}",
        score=12,  # medium risk when unknown
        risk_level=RiskLevel.MEDIUM,
        evidence_quality="low",
        data_limitations=[f"node_failed: {reason[:200]}"],
        created_at=_now_iso(),
    )


def build_fallback_sector_theme_card(reason: str) -> SectorThemeExposureCard:
    return SectorThemeExposureCard(
        summary=f"行业主题暴露评估不可用：{reason[:100]}",
        score=10,
        risk_level=RiskLevel.MEDIUM,
        evidence_quality="low",
        data_limitations=[f"node_failed: {reason[:200]}"],
        created_at=_now_iso(),
    )


def build_fallback_correlation_card(reason: str) -> CorrelationRiskCard:
    return CorrelationRiskCard(
        summary=f"相关性风险评估不可用：{reason[:100]}",
        score=10,
        risk_level=RiskLevel.MEDIUM,
        evidence_quality="low",
        data_limitations=[f"node_failed: {reason[:200]}"],
        created_at=_now_iso(),
    )


def build_fallback_earnings_calendar_card(reason: str) -> EarningsCalendarRiskCard:
    return EarningsCalendarRiskCard(
        summary=f"财报日历风险评估不可用：{reason[:100]}",
        score=7,
        risk_level=RiskLevel.MEDIUM,
        evidence_quality="low",
        data_limitations=[f"node_failed: {reason[:200]}"],
        created_at=_now_iso(),
    )


def build_fallback_stress_test_card(reason: str) -> StressTestCard:
    return StressTestCard(
        summary=f"压力测试评估不可用：{reason[:100]}",
        score=10,
        risk_level=RiskLevel.MEDIUM,
        evidence_quality="low",
        data_limitations=[f"node_failed: {reason[:200]}"],
        created_at=_now_iso(),
    )


# --- Theme classification rules ---

THEME_SEMICONDUCTOR = {
    "AMD", "NVDA", "INTC", "TSM", "ASML", "AVGO", "MU", "SMCI", "QCOM", "MRVL",
    "AMAT", "LRCX", "KLAC", "ON", "TXN", "MCHP", "WOLF", "ARM",
}

THEME_AI = {
    "NVDA", "MSFT", "GOOGL", "AMZN", "META", "ORCL", "CRM", "PLTR", "SNOW",
    "AI", "SYM", "PATH", "MDB", "NET", "DDOG", "PANW", "CRWD", "ZS",
}

THEME_CHINA = {
    "BABA", "JD", "PDD", "BIDU", "XIACY", "TCEHY", "NIO", "LI", "XPEV",
    "BILI", "IQ", "MNSO", "FUTU", "TIGR", "EDU", "TAL", "YMM", "ZTO",
    "KC", "DADA", "QFIN", "LX", "FINV",
}

MEGA_CAP_TECH = {
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
}

CASH_EQUIVALENT_SYMBOLS = {"SGOV", "STRC", "BIL", "SHV", "USFR", "TFLO", "BOXX"}


def classify_symbol_theme(symbol: str) -> dict[str, bool]:
    """Classify a symbol into themes using rules. No MCP needed."""
    base = str(symbol or "").upper().split(".", 1)[0]
    return {
        "semiconductor": base in THEME_SEMICONDUCTOR,
        "ai": base in THEME_AI,
        "china": base in THEME_CHINA,
        "mega_cap_tech": base in MEGA_CAP_TECH,
        "cash_equivalent": base in CASH_EQUIVALENT_SYMBOLS,
    }
