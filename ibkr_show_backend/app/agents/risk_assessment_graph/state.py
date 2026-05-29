"""Risk assessment graph state definition."""

from __future__ import annotations

from app.agents.graph.base_state import BaseGraphState
from app.agents.risk_assessment_graph.cards import (
    AccountRiskSnapshot,
    ConcentrationRiskCard,
    CorrelationRiskCard,
    EarningsCalendarRiskCard,
    RiskAssessmentCardPack,
    SectorThemeExposureCard,
    StressTestCard,
)


class RiskAssessmentGraphState(BaseGraphState, total=False):
    assessment_type: str
    user_question: str | None

    account_risk_snapshot: AccountRiskSnapshot | dict | None

    concentration_card: ConcentrationRiskCard | None
    sector_theme_card: SectorThemeExposureCard | None
    correlation_card: CorrelationRiskCard | None
    earnings_calendar_card: EarningsCalendarRiskCard | None
    stress_test_card: StressTestCard | None

    card_pack: RiskAssessmentCardPack | None
    risk_report: dict | None
    saved_document: dict | None

    # Per-node public data mode — parallel-safe
    sector_public_data_mode: str | None
    correlation_public_data_mode: str | None
    earnings_public_data_mode: str | None
