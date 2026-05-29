from pydantic import BaseModel, Field

from app.schemas.trade_decision import AgentRunTraceItem


class DailyPositionReviewHealthResponse(BaseModel):
    enabled: bool
    llm_configured: bool
    longbridge_configured: bool
    account_data_source: str
    public_market_data_source: str
    message: str
    agent_mode: str = "daily_position_review_langgraph_v1"
    graph_version: str = "daily_position_review_graph_v1"


class DailyPositionReviewGenerateRequest(BaseModel):
    force_refresh: bool = False


class DailyPositionReviewDateListResponse(BaseModel):
    items: list[str]


class DailyPositionReviewPositionItem(BaseModel):
    symbol: str
    normalized_symbol: str
    name: str | None = None
    asset_class: str | None = None
    sub_category: str | None = None
    quantity: float | None = None
    mark_price: float | None = None
    market_value: float | None = None
    weight: float | None = None
    daily_change_percent: float | None = None
    daily_pnl: float | None = None
    contribution_ratio: float | None = None
    average_cost: float | None = None
    cost_basis: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_percent: float | None = None
    is_major_contributor: bool = False
    is_major_drag: bool = False
    data_source: str = "IBKR"


class DailyPositionReviewOverviewResponse(BaseModel):
    report_date: str
    currency: str | None = None
    total_equity: float | None = None
    daily_pnl: float | None = None
    daily_pnl_source: str | None = None
    daily_return_percent: float | None = None
    total_position_value: float | None = None
    cash: float | None = None
    cash_ratio: float | None = None
    position_count: int = 0
    top_contributors: list[DailyPositionReviewPositionItem] = Field(default_factory=list)
    top_drags: list[DailyPositionReviewPositionItem] = Field(default_factory=list)
    summary: str
    ibkr_pnl_breakdown: dict = Field(default_factory=dict)


class DailyPositionReviewPositionsResponse(BaseModel):
    report_date: str
    items: list[DailyPositionReviewPositionItem]


class DailyPositionReviewRankingsResponse(BaseModel):
    report_date: str
    profit_contributors: list[DailyPositionReviewPositionItem] = Field(default_factory=list)
    loss_drags: list[DailyPositionReviewPositionItem] = Field(default_factory=list)
    top_gainers: list[DailyPositionReviewPositionItem] = Field(default_factory=list)
    top_losers: list[DailyPositionReviewPositionItem] = Field(default_factory=list)
    top_weights: list[DailyPositionReviewPositionItem] = Field(default_factory=list)
    top_unrealized_gains: list[DailyPositionReviewPositionItem] = Field(default_factory=list)
    top_unrealized_losses: list[DailyPositionReviewPositionItem] = Field(default_factory=list)


class DailyPositionReviewRiskResponse(BaseModel):
    report_date: str
    max_position: dict | None = None
    max_single_position_weight: float | None = None
    top3_weight: float | None = None
    top5_weight: float | None = None
    theme_buckets: list[dict] = Field(default_factory=list)
    semiconductor_ai_tech_weight: float | None = None
    cash_ratio: float | None = None
    max_position_down_5pct_account_impact_percent: float | None = None
    risk_flags: list[str] = Field(default_factory=list)
    account_posture: str | None = None


class DailyPositionReviewContextResponse(BaseModel):
    report_date: str
    data_sources: dict
    overview: dict
    positions: list[DailyPositionReviewPositionItem]
    rankings: dict
    risk: dict
    benchmarks: dict
    focus_symbols: list[str]
    attribution_quality: dict
    data_quality: dict


class DailyPositionReviewResult(BaseModel):
    id: str
    report_date: str
    review_type: str
    summary: str
    account_conclusion: str
    attribution_summary: str
    major_contributors_analysis: list[dict]
    major_drags_analysis: list[dict]
    focus_symbol_analyses: list[dict]
    market_context: str
    risk_analysis: str
    tomorrow_watchlist: list[dict]
    operation_observation: str
    data_limitations: list[str]
    evidence_used: list[str]
    data_source_summary: dict
    deterministic_context: dict = Field(default_factory=dict)
    run_trace: list[AgentRunTraceItem] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    evidence_summary: dict = Field(default_factory=dict)
    run_trace_summary: dict = Field(default_factory=dict)
    subagent_card_pack: dict = Field(default_factory=dict)
    subagent_trace: dict = Field(default_factory=dict)
    evidence_card_summary: dict = Field(default_factory=dict)
    graph_node_traces: list[dict] = Field(default_factory=list)
    graph_version: str | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
    status: str | None = None
    created_at: str
    updated_at: str


class DailyPositionReviewListResponse(BaseModel):
    items: list[DailyPositionReviewResult]
