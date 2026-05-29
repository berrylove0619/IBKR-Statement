"""Trade decision graph state definition."""

from __future__ import annotations

from typing import TypedDict

from app.agents.graph.base_state import BaseGraphState
from app.agents.trade_decision_cards import (
    AccountFactSnapshot,
    AccountFitCard,
    EventCatalystCard,
    FundamentalValuationCard,
    MarketTrendCard,
    RiskRewardCard,
    TradeDecisionCardPack,
)


class TradeDecisionGraphState(BaseGraphState, total=False):
    decision_type: str
    symbol: str
    normalized_symbol: str
    user_question: str | None

    account_fact_snapshot: AccountFactSnapshot | dict | None

    account_fit_card: AccountFitCard | None
    market_trend_card: MarketTrendCard | None
    fundamental_valuation_card: FundamentalValuationCard | None
    event_catalyst_card: EventCatalystCard | None
    risk_reward_card: RiskRewardCard | None

    card_pack: TradeDecisionCardPack | None
    decision_output: dict | None
    saved_document: dict | None

    mcp_available: bool | None

    # Per-node public data mode — parallel-safe, no shared single-value write
    market_public_data_mode: str | None
    fundamental_public_data_mode: str | None
    event_public_data_mode: str | None
    market_trend_prompt_metadata: dict | None
    fundamental_valuation_prompt_metadata: dict | None
    event_catalyst_prompt_metadata: dict | None
