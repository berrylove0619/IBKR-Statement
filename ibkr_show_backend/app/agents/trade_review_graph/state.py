"""Trade review graph state definition."""

from __future__ import annotations

from typing import Any

from app.agents.graph.base_state import BaseGraphState


class TradeReviewGraphState(BaseGraphState, total=False):
    # Input
    review_type: str
    symbol: str | None
    trade_id: str | None
    start_date: str | None
    end_date: str | None

    # load_trade_facts output
    trade_facts: dict | None
    review_context: dict | None

    # Parallel evidence nodes — per-node fields
    position_evidence: dict | None
    account_evidence: dict | None
    market_evidence: dict | None
    benchmark_evidence: dict | None
    event_evidence: dict | None

    # Merged context
    merged_review_context: dict | None

    # Parallel analysis nodes
    behavior_pattern_analysis: dict | None
    opportunity_cost_analysis: dict | None
    behavior_prompt_metadata: dict | None
    opportunity_prompt_metadata: dict | None
    behavior_structured_output: dict | None
    opportunity_structured_output: dict | None

    # Compose output
    trade_review_output: dict | None
    prompt_metadata: dict | None
    structured_output: dict | None
    raw_llm_response: dict | str | None

    # Persist output
    saved_document: dict | None
