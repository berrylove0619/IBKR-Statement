"""Pydantic schemas for risk assessment API."""

from pydantic import BaseModel, Field


class RiskAssessmentAnalyzeRequest(BaseModel):
    question: str | None = None
    force_refresh: bool = False


class RiskAssessmentResult(BaseModel):
    id: str
    assessment_type: str = "portfolio_risk"
    overall_risk_score: float
    risk_level: str
    risk_summary: str
    score_detail: dict = Field(default_factory=dict)
    key_risks: list[str] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)
    concentration_warnings: list[str] = Field(default_factory=list)
    event_warnings: list[str] = Field(default_factory=list)
    stress_test_summary: dict = Field(default_factory=dict)
    data_limitations: list[str] = Field(default_factory=list)
    evidence_used: list[str] = Field(default_factory=list)
    confidence: str = "low"
    card_pack: dict = Field(default_factory=dict)
    run_trace: list[dict] = Field(default_factory=list)
    run_trace_summary: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
    fallback_used: bool = False
    fallback_reason: str | None = None
    created_at: str
    updated_at: str


class RiskAssessmentListResponse(BaseModel):
    items: list[RiskAssessmentResult]


class RiskAssessmentHealthResponse(BaseModel):
    enabled: bool
    llm_configured: bool
    mcp_enabled: bool = False
    mcp_available: bool = False
    mcp_auth_status: str = "unavailable"
    mcp_last_error: str = ""
    sdk_fallback_available: bool = False
    longbridge_sdk_configured: bool = False
    public_data_mode: str = "unavailable"
    account_data_source: str = "IBKR_ONLY"
    public_market_data_source: str = "unavailable"
    agent_mode: str = "risk_assessment_langgraph_v1"
    graph_version: str = "risk_assessment_graph_v1"
    message: str
