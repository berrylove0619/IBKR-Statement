from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.agents.output_schemas import ScoreItem
from app.agents.structured_output.contracts import StructuredOutputContract


TRADE_REVIEW_REPAIR_SYSTEM_PROMPT = """你是交易复盘结构化 JSON 修复器。
你的任务不是重新分析交易，而是把已有模型输出修复为符合指定 schema 的严格 JSON object。
只能使用原始输出和上下文中已经出现的信息。
不能编造交易事实、账户数据、价格、收益、新闻、评分理由或买卖建议。
如果某字段缺失且无法确认，请填空数组、空对象、null 或在 data_limitations 中说明。
只输出 JSON object，不要 Markdown，不要解释，不要代码块。"""


class BehaviorPatternLLMOutput(BaseModel):
    behavior_patterns: list[str] = Field(default_factory=list)
    behavior_score: float = Field(default=0, ge=0, le=100)
    behavior_summary: str
    recurring_patterns: list[str] = Field(default_factory=list)
    positive_patterns: list[str] = Field(default_factory=list)
    negative_patterns: list[str] = Field(default_factory=list)
    mistake_tags: list[str] = Field(default_factory=list)
    improvement_notes: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"
    data_limitations: list[str] = Field(default_factory=list)

    @field_validator("behavior_summary")
    @classmethod
    def _summary_required(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("behavior_summary must be non-empty")
        return text

    @field_validator(
        "behavior_patterns",
        "recurring_patterns",
        "positive_patterns",
        "negative_patterns",
        "mistake_tags",
        "improvement_notes",
        "data_limitations",
        mode="before",
    )
    @classmethod
    def _list_of_strings(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            return [str(value)]
        return [str(item) for item in value]


class OpportunityCostLLMOutput(BaseModel):
    opportunity_cost_score: float = Field(default=0, ge=0, le=100)
    benchmark_comparison: dict[str, Any] = Field(default_factory=dict)
    opportunity_cost_summary: str
    missed_upside: list[str] = Field(default_factory=list)
    avoided_downside: list[str] = Field(default_factory=list)
    capital_redeployment: list[str] = Field(default_factory=list)
    alternative_actions: list[str] = Field(default_factory=list)
    severity: Literal["low", "medium", "high"] = "medium"
    confidence: Literal["low", "medium", "high"] = "medium"
    data_limitations: list[str] = Field(default_factory=list)

    @field_validator("opportunity_cost_summary")
    @classmethod
    def _summary_required(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("opportunity_cost_summary must be non-empty")
        return text

    @field_validator(
        "missed_upside",
        "avoided_downside",
        "capital_redeployment",
        "alternative_actions",
        "data_limitations",
        mode="before",
    )
    @classmethod
    def _list_of_strings(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            return [str(value)]
        return [str(item) for item in value]


class TradeReviewMainLLMOutput(BaseModel):
    symbol: str | None = None
    review_type: str | None = None
    overall_score: float = Field(ge=0, le=100)
    rating: str
    score_detail: dict[str, ScoreItem]
    summary: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    mistake_tags: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)
    data_limitations: list[str] = Field(default_factory=list)
    evidence_used: list[str] = Field(default_factory=list)

    @field_validator("rating", "summary")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("field must be non-empty")
        return text

    @field_validator(
        "strengths",
        "weaknesses",
        "mistake_tags",
        "improvement_suggestions",
        "data_limitations",
        "evidence_used",
        mode="before",
    )
    @classmethod
    def _main_list_of_strings(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            return [str(value)]
        return [str(item) for item in value]


BEHAVIOR_PATTERN_EXAMPLES: list[dict[str, Any]] = [
    {
        "behavior_patterns": ["分批买入后没有明确退出计划"],
        "behavior_score": 62,
        "behavior_summary": "交易行为整体有计划性，但在加减仓节奏和退出纪律上仍有改进空间。",
        "recurring_patterns": ["上涨趋势中加仓偏谨慎"],
        "positive_patterns": ["没有单笔满仓，保留了风险缓冲"],
        "negative_patterns": ["卖出前缺少相对强弱和替代机会检查"],
        "mistake_tags": ["POSITION_TOO_SMALL"],
        "improvement_notes": ["下次卖出前检查相对 QQQ/SMH 强弱和分批止盈方案"],
        "confidence": "medium",
        "data_limitations": [],
    },
    {
        "behavior_patterns": [],
        "behavior_score": 50,
        "behavior_summary": "交易样本不足，无法确认稳定行为模式。",
        "recurring_patterns": [],
        "positive_patterns": [],
        "negative_patterns": [],
        "mistake_tags": [],
        "improvement_notes": ["积累更多交易样本后再判断是否存在重复行为模式"],
        "confidence": "low",
        "data_limitations": ["交易样本数量不足，无法判断是否为重复模式"],
    },
]


OPPORTUNITY_COST_EXAMPLES: list[dict[str, Any]] = [
    {
        "opportunity_cost_score": 68,
        "benchmark_comparison": {
            "QQQ": "交易后 QQQ 继续上涨，说明大盘科技 beta 仍强",
            "SMH": "半导体板块表现强于个股，存在行业 beta 机会",
        },
        "opportunity_cost_summary": "这笔交易存在中等机会成本，主要来自过早减仓后趋势继续延续，但卖出也释放了部分集中度风险。",
        "missed_upside": ["如果继续持有，可能捕获后续趋势收益"],
        "avoided_downside": ["卖出降低了单一标的回撤对账户的影响"],
        "capital_redeployment": ["需要结合卖出后资金是否投入更高收益标的判断"],
        "alternative_actions": ["可以考虑部分止盈而不是一次性退出"],
        "severity": "medium",
        "confidence": "medium",
        "data_limitations": [],
    },
    {
        "opportunity_cost_score": 50,
        "benchmark_comparison": {},
        "opportunity_cost_summary": "缺少卖出后价格走势或资金再部署数据，机会成本只能做保守判断。",
        "missed_upside": [],
        "avoided_downside": [],
        "capital_redeployment": [],
        "alternative_actions": ["补充卖出后资金去向后再评估机会成本"],
        "severity": "low",
        "confidence": "low",
        "data_limitations": ["缺少卖出后基准对比或资金再部署数据"],
    },
]


TRADE_REVIEW_MAIN_EXAMPLE: dict[str, Any] = {
    "symbol": "AMD.US",
    "review_type": "symbol_level_review",
    "overall_score": 72,
    "rating": "good",
    "score_detail": {
        "entry_quality_score": {"score": 8, "max_score": 15, "reason": "买入时趋势和基本面证据较充分"}
    },
    "summary": "这次交易方向判断较好，但仓位和退出计划仍有优化空间。",
    "strengths": ["买入逻辑有基本面和趋势支撑"],
    "weaknesses": ["上涨趋势中加仓偏谨慎"],
    "mistake_tags": ["POSITION_TOO_SMALL"],
    "improvement_suggestions": ["下次提前设计分批加仓和分批止盈规则"],
    "data_limitations": [],
    "evidence_used": ["IBKR trades", "behavior_pattern_analysis", "opportunity_cost_analysis"],
}


def build_trade_review_behavior_contract() -> StructuredOutputContract:
    return StructuredOutputContract(
        name="trade_review_behavior_pattern",
        agent_name="trade_review",
        node_name="behavior_pattern",
        output_model=BehaviorPatternLLMOutput,
        schema_hint=BehaviorPatternLLMOutput.model_json_schema(),
        examples=BEHAVIOR_PATTERN_EXAMPLES,
        max_repair_attempts=1,
        repair_enabled=True,
        fallback_enabled=False,
        repair_system_prompt=TRADE_REVIEW_REPAIR_SYSTEM_PROMPT,
    )


def build_trade_review_opportunity_contract() -> StructuredOutputContract:
    return StructuredOutputContract(
        name="trade_review_opportunity_cost",
        agent_name="trade_review",
        node_name="opportunity_cost",
        output_model=OpportunityCostLLMOutput,
        schema_hint=OpportunityCostLLMOutput.model_json_schema(),
        examples=OPPORTUNITY_COST_EXAMPLES,
        max_repair_attempts=1,
        repair_enabled=True,
        fallback_enabled=False,
        repair_system_prompt=TRADE_REVIEW_REPAIR_SYSTEM_PROMPT,
    )


def build_trade_review_main_contract(fallback_builder=None) -> StructuredOutputContract:
    return StructuredOutputContract(
        name="trade_review_main",
        agent_name="trade_review",
        node_name="compose_trade_review",
        output_model=TradeReviewMainLLMOutput,
        schema_hint=TradeReviewMainLLMOutput.model_json_schema(),
        examples=[TRADE_REVIEW_MAIN_EXAMPLE],
        max_repair_attempts=1,
        repair_enabled=True,
        fallback_enabled=fallback_builder is not None,
        fallback_builder=fallback_builder,
        repair_system_prompt=TRADE_REVIEW_REPAIR_SYSTEM_PROMPT,
    )
