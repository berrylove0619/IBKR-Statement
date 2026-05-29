from typing import Any

from pydantic import BaseModel, Field


class TradeReviewGenerateSymbolRequest(BaseModel):
    start_date: str | None = None
    end_date: str | None = None
    force_refresh: bool = False


class TradeReviewGenerateTradeRequest(BaseModel):
    force_refresh: bool = False


class AgentRunTraceItem(BaseModel):
    event: str
    node_name: str | None = None
    tool: str | None = None
    tool_call_id: str | None = None
    round: int | None = None
    arguments: dict[str, Any] | None = None
    steps: list[str] | None = None
    ok: bool | None = None
    summary: str | None = None
    latency_ms: int | None = None
    created_at_ms: int | None = None
    elapsed_ms: int | None = None
    tools_called: list[str] | None = None
    rounds_used: int | None = None
    fallback_used: bool | None = None
    fallback_reason: str | None = None
    structured_output: dict[str, Any] | None = None
    runtime_trace: list[dict[str, Any]] | None = None


class TradeReviewScoreItem(BaseModel):
    score: float | None = None
    max_score: float
    reason: str = ""
    applicable: bool = True


class TradeReviewResult(BaseModel):
    id: str
    review_type: str
    symbol: str
    trade_ids: list[str] = Field(default_factory=list)
    start_date: str | None = None
    end_date: str | None = None
    overall_score: float
    rating: str
    score_detail: dict[str, TradeReviewScoreItem]
    summary: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    mistake_tags: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)
    data_limitations: list[str] = Field(default_factory=list)
    evidence_used: list[str] = Field(default_factory=list)
    run_trace: list[AgentRunTraceItem] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    evidence_summary: dict = Field(default_factory=dict)
    run_trace_summary: dict = Field(default_factory=dict)
    created_at: str
    updated_at: str


class TradeReviewDetailResult(TradeReviewResult):
    evidence_pack: dict[str, Any] | None = None


class TradeReviewHealthResponse(BaseModel):
    enabled: bool
    llm_configured: bool
    longbridge_configured: bool
    message: str
    account_data_source: str = "IBKR_ONLY"
    trade_data_source: str = "IBKR_ONLY"
    position_data_source: str = "IBKR_ONLY"
    public_market_data_source: str = "LONGBRIDGE_MCP_OR_SDK_PUBLIC_ONLY"
    agent_mode: str = "trade_review_langgraph_v1"
    graph_version: str = "trade_review_graph_v1"


class TradeReviewListResponse(BaseModel):
    items: list[TradeReviewResult]


class TradeReviewMistakeSummaryItem(BaseModel):
    tag: str
    count: int
    symbols: list[str]
    latest_review_id: str


class TradeReviewMistakeSummaryResponse(BaseModel):
    items: list[TradeReviewMistakeSummaryItem]


class TradeReviewErrorResponse(BaseModel):
    error_code: str
    message: str
