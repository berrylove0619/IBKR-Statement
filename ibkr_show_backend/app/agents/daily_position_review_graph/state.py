"""Daily Position Review graph state definition."""

from __future__ import annotations

from app.agents.graph.base_state import BaseGraphState


class DailyPositionReviewGraphState(BaseGraphState, total=False):
    report_date: str
    force_refresh: bool
    auto_email: bool

    deterministic_context: dict | None
    compact_positions: list[dict]
    focus_position_items: list[dict]
    focus_symbols: list[str]

    symbol_cards: list
    macro_card: object | None
    portfolio_attribution_card: dict | None
    risk_watch_card: dict | None

    card_pack: object | None
    card_pack_summary: dict | None
    evidence_pack: dict | None

    review_output: dict | None
    raw_llm_response: str | None
    model_provider_snapshot: dict | None
    prompt_metadata: dict | None
    saved_document: dict | None

    symbol_cards_public_data_mode: str | None
    macro_public_data_mode: str | None
