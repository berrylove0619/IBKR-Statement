from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.output_schemas import DailyPositionReviewOutput
from app.agents.structured_output.contracts import DEFAULT_REPAIR_SYSTEM_PROMPT, StructuredOutputContract


class _FlexibleOutput(BaseModel):
    model_config = ConfigDict(extra="allow")


class AccountImpactLLMOutput(_FlexibleOutput):
    position_weight: float | None = None
    daily_pnl: float | None = None
    daily_change_percent: float | None = None
    contribution_ratio: float | None = None
    market_value: float | None = None
    quantity: float | None = None
    average_cost: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_percent: float | None = None


class PriceActionLLMOutput(_FlexibleOutput):
    current_price: float | None = None
    previous_close: float | None = None
    day_change_percent: float | None = None
    relative_to_benchmark: str | None = None
    relative_to_sector: str | None = None


class NewsSummaryLLMOutput(_FlexibleOutput):
    key_news: list[str] = Field(default_factory=list)
    catalyst: str | None = None
    sentiment: str | None = None
    confidence: str | None = None


class ValuationSummaryLLMOutput(_FlexibleOutput):
    market_cap: float | None = None
    pe_ttm: float | None = None
    ps_ttm: float | None = None
    valuation_comment: str | None = None
    data_limitations: list[str] = Field(default_factory=list)


class EarningsSummaryLLMOutput(_FlexibleOutput):
    latest_earnings: str | None = None
    revenue_growth: str | None = None
    profit_growth: str | None = None
    guidance: str | None = None
    data_limitations: list[str] = Field(default_factory=list)


class TechnicalSummaryLLMOutput(_FlexibleOutput):
    trend: str | None = None
    support_levels: list[str] = Field(default_factory=list)
    resistance_levels: list[str] = Field(default_factory=list)
    volume_signal: str | None = None
    data_limitations: list[str] = Field(default_factory=list)


class CrossAssetSummaryLLMOutput(_FlexibleOutput):
    related_assets: list[str] = Field(default_factory=list)
    relation_note: str | None = None
    data_limitations: list[str] = Field(default_factory=list)


class SymbolEvidenceLLMOutput(_FlexibleOutput):
    symbol: str
    normalized_symbol: str
    report_date: str
    account_impact: AccountImpactLLMOutput = Field(default_factory=AccountImpactLLMOutput)
    price_action: PriceActionLLMOutput = Field(default_factory=PriceActionLLMOutput)
    news_summary: NewsSummaryLLMOutput = Field(default_factory=NewsSummaryLLMOutput)
    valuation_summary: ValuationSummaryLLMOutput = Field(default_factory=ValuationSummaryLLMOutput)
    earnings_summary: EarningsSummaryLLMOutput = Field(default_factory=EarningsSummaryLLMOutput)
    technical_summary: TechnicalSummaryLLMOutput = Field(default_factory=TechnicalSummaryLLMOutput)
    cross_asset_summary: CrossAssetSummaryLLMOutput = Field(default_factory=CrossAssetSummaryLLMOutput)
    likely_drivers: list[str] = Field(default_factory=list)
    watch_points: list[str] = Field(default_factory=list)
    evidence_quality: Literal["high", "medium", "low"] = "medium"
    data_limitations: list[str] = Field(default_factory=list)
    source_trace: list[str] = Field(default_factory=list)


class MacroEvidenceLLMOutput(_FlexibleOutput):
    report_date: str
    benchmark_context: dict[str, Any] = Field(default_factory=dict)
    market_regime: Literal["risk_on", "risk_off", "mixed"] = "mixed"
    sector_context: str | None = None
    macro_events: list[str] = Field(default_factory=list)
    rate_fx_context: str | None = None
    risk_sentiment: Literal["risk_on", "risk_off", "neutral"] = "neutral"
    tech_sentiment: Literal["positive", "negative", "neutral"] = "neutral"
    data_limitations: list[str] = Field(default_factory=list)
    source_trace: list[str] = Field(default_factory=list)


SYMBOL_EVIDENCE_SCHEMA_EXAMPLE = {
    "symbol": "AMD",
    "normalized_symbol": "AMD.US",
    "report_date": "2026-05-20",
    "account_impact": {"position_weight": 0.1, "daily_pnl": 120.0, "daily_change_percent": 2.1, "contribution_ratio": 0.3},
    "price_action": {"current_price": 110.0, "previous_close": 107.7, "day_change_percent": 2.1, "relative_to_benchmark": "跑赢 QQQ", "relative_to_sector": "接近 SMH"},
    "news_summary": {"key_news": ["公开新闻显示 AI 芯片需求仍受关注"], "catalyst": "AI 需求预期", "sentiment": "positive", "confidence": "medium"},
    "valuation_summary": {"market_cap": 180000000000, "pe_ttm": 28.5, "ps_ttm": 8.2, "valuation_comment": "估值仍含成长溢价", "data_limitations": []},
    "earnings_summary": {"latest_earnings": "最近财报收入增长", "revenue_growth": "+10% YoY", "profit_growth": None, "guidance": None, "data_limitations": ["未提供完整利润指引"]},
    "technical_summary": {"trend": "bullish", "support_levels": ["105"], "resistance_levels": ["115"], "volume_signal": "成交量放大", "data_limitations": []},
    "cross_asset_summary": {"related_assets": ["SMH.US"], "relation_note": "半导体板块同步走强", "data_limitations": []},
    "likely_drivers": ["板块 beta", "AI 需求预期"],
    "watch_points": ["观察 SMH 是否延续", "观察财报指引"],
    "evidence_quality": "medium",
    "data_limitations": [],
    "source_trace": ["Longbridge news", "Longbridge candles"],
}


MACRO_EVIDENCE_SCHEMA_EXAMPLE = {
    "report_date": "2026-05-20",
    "benchmark_context": {"QQQ": {"return_percent": 1.1}, "SPY": {"return_percent": 0.6}},
    "market_regime": "mixed",
    "sector_context": "科技股相对强于大盘，但风险偏好并不单边。",
    "macro_events": [],
    "rate_fx_context": None,
    "risk_sentiment": "neutral",
    "tech_sentiment": "positive",
    "data_limitations": ["未提供明确利率/汇率事件输入"],
    "source_trace": ["Longbridge candles"],
}


DAILY_POSITION_REVIEW_MAIN_EXAMPLE = {
    "report_date": "2026-05-20",
    "summary": "今日账户小幅上涨，主要由 AMD 和 MSFT 贡献。",
    "account_conclusion": "账户收益来自大仓位贡献，公开新闻只作为辅助解释。",
    "attribution_summary": "主要贡献来自 AMD，主要拖累来自 INTC；具体盈亏和贡献率以 IBKR 确定性数据为准。",
    "major_contributors_analysis": [{"symbol": "AMD.US", "analysis": "仓位贡献为正，公开证据显示半导体板块偏强。"}],
    "major_drags_analysis": [{"symbol": "INTC.US", "analysis": "当日拖累账户表现，公开证据不足以确认单一原因。"}],
    "focus_symbol_analyses": [
        {
            "symbol": "AMD.US",
            "price_action": "跑赢 QQQ 和 SMH。",
            "account_impact": "对账户正贡献较高。",
            "possible_reasons": ["半导体板块偏强"],
            "valuation_note": "估值仍有成长溢价。",
            "cost_position_note": "成本和浮盈亏以 IBKR 数据为准。",
            "watch_points": ["观察 SMH 和 NVDA 是否继续确认方向"],
            "data_limitations": [],
        }
    ],
    "market_context": "宏观信号 mixed，科技相对偏强。",
    "risk_analysis": "继续关注单一标的集中度和现金比例。",
    "tomorrow_watchlist": [{"symbol": "AMD.US", "reason": "大仓位且波动较高", "key_levels": [], "events": [], "conditions": ["观察是否继续跑赢 SMH"]}],
    "operation_observation": "仅作为复盘观察，不构成确定性买卖指令。",
    "data_limitations": [],
    "evidence_used": ["IBKR account snapshot", "SymbolEvidenceCard", "MacroEvidenceCard"],
}


DAILY_REVIEW_REPAIR_SYSTEM_PROMPT = (
    DEFAULT_REPAIR_SYSTEM_PROMPT
    + "\n只能修复 Daily Position Review 的 JSON 格式和 schema；不要重新计算 IBKR 数字，不要编造新闻、宏观事件或账户事实。"
)


def build_symbol_evidence_contract() -> StructuredOutputContract:
    return StructuredOutputContract(
        name="daily_review_symbol_evidence_card",
        agent_name="daily_position_review",
        node_name="symbol_evidence_card",
        output_model=SymbolEvidenceLLMOutput,
        schema_hint=SymbolEvidenceLLMOutput.model_json_schema(),
        examples=[SYMBOL_EVIDENCE_SCHEMA_EXAMPLE],
        max_repair_attempts=2,
        repair_enabled=True,
        fallback_enabled=False,
        repair_system_prompt=DAILY_REVIEW_REPAIR_SYSTEM_PROMPT,
    )


def build_macro_evidence_contract() -> StructuredOutputContract:
    return StructuredOutputContract(
        name="daily_review_macro_evidence_card",
        agent_name="daily_position_review",
        node_name="macro_evidence_card",
        output_model=MacroEvidenceLLMOutput,
        schema_hint=MacroEvidenceLLMOutput.model_json_schema(),
        examples=[MACRO_EVIDENCE_SCHEMA_EXAMPLE],
        max_repair_attempts=2,
        repair_enabled=True,
        fallback_enabled=False,
        repair_system_prompt=DAILY_REVIEW_REPAIR_SYSTEM_PROMPT,
    )


def build_daily_position_review_main_contract(fallback_builder=None) -> StructuredOutputContract:
    return StructuredOutputContract(
        name="daily_position_review_main",
        agent_name="daily_position_review",
        node_name="compose_daily_review",
        output_model=DailyPositionReviewOutput,
        schema_hint=DailyPositionReviewOutput.model_json_schema(),
        examples=[DAILY_POSITION_REVIEW_MAIN_EXAMPLE],
        max_repair_attempts=3,
        repair_enabled=True,
        fallback_enabled=fallback_builder is not None,
        fallback_builder=fallback_builder,
        repair_system_prompt=DAILY_REVIEW_REPAIR_SYSTEM_PROMPT,
    )
