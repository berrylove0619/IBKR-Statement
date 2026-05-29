"""
Sub-agent for generating SymbolEvidenceCard for a single symbol.

Responsibilities:
- Summarize public解释 materials (news, valuation, earnings, industry, technical, cross-asset)
- Combine with that symbol's IBKR account impact
- Output strictly JSON conforming to SymbolEvidenceCard schema
- Never recalculate IBKR deterministic numbers
- If public data is missing, write to data_limitations, don't fabricate
- Keep output compact: target 1000-2000 Chinese characters

Special linkage rules:
- MSTR: must attempt BTC / crypto risk sentiment
- XIACY: must attempt Xiaomi ADR / China tech / EV context
- AMD/INTC/QCOM/SMCI: must attempt semiconductor / AI / SMH context
- TSLA: must attempt EV, growth risk appetite, rate sensitivity
- MSFT/META: must attempt big tech / AI capex / Nasdaq/QQQ context
"""

from __future__ import annotations

import json

from app.agents.daily_review_evidence_cards import (
    AccountImpactFields,
    CrossAssetSummaryFields,
    EarningsSummaryFields,
    NewsSummaryFields,
    PriceActionFields,
    SymbolEvidenceCard,
    TechnicalSummaryFields,
    ValuationSummaryFields,
)
from app.agents.daily_review_structured_outputs import build_symbol_evidence_contract
from app.agents.prompt_runtime import resolve_runtime_prompt
from app.agents.structured_output.runtime import StructuredOutputRuntime
from app.services.llm_service import LLMService


SYSTEM_PROMPT_SYMBOL_CARD = """你是每日持仓复盘的子 Agent，负责为单个标的生成"证据卡片"（SymbolEvidenceCard）。
你的任务是将 Longbridge 公开数据（新闻、估值、财报、行业、技术面、联动资产）总结成高密度证据卡片，
再结合该标的的 IBKR 账户影响数据，形成结构化解释。

重要约束：
1. 只能引用输入里的 IBKR 数字，不能重新计算或修改这些数字。
2. 公开数据缺失时，必须写入 data_limitations，不能编造原因。
3. 每个标的的输出应尽量紧凑，目标 1000-2000 中文字以内。
4. 不要输出强买强卖指令，只输出观察和解释。
5. 最终必须输出严格 JSON object，不要输出 Markdown，不要代码块，不要额外解释，不要省略字段。
6. source_trace 只能记录真实出现在输入中的来源或工具名；不能写入没有实际调用或没有输入支持的来源。
7. 不允许凭空关联 BTC、AI、降息、财报、评级、监管等原因；只有输入数据支持时才能作为 likely_drivers。
8. 证据质量判断口径：
   - high：IBKR 账户影响字段完整，且公开数据能覆盖价格/新闻或财报/估值/联动资产中的多个维度。
   - medium：IBKR 字段基本可用，但公开证据只有部分维度或结论存在明显不确定性。
   - low：缺少关键公开数据、只能做弱解释，或输入不足以确认主要驱动。

特殊联动规则（必须尽量覆盖）：
- MSTR：必须使用 related_asset_context 中的 IBIT/GBTC/COIN/BTC 来解释 cross_asset_summary。如果没有 BTC 数据，写入 data_limitations，不允许凭空说"可能与 BTC 下跌有关"。
- XIACY：必须使用 related_asset_context 中的 1810.HK / EV peers 来解释 cross_asset_summary。
- AMD / INTC / QCOM / SMCI / AVGO：必须使用 related_asset_context 中的 SMH/NVDA/AVGO/INTC 来判断个股原因 vs 行业 beta。
- TSLA：必须尝试加入 EV 需求、成长股风险偏好、利率敏感性解释。
- MSFT / META / GOOGL / AMZN：必须尝试加入大盘科技、AI capex、Nasdaq/QQQ 背景。

cross_asset_summary 规则：
- 必须优先使用 related_asset_context 中的关联资产来解释 cross_asset_summary
- 如果 related_asset_context 包含相关资产，必须用来解释 cross_asset_summary
- 如果 related_asset_context 为空或没有相关资产，在 data_limitations 中说明"未获取到联动资产数据"
- 不允许凭空说"可能与 BTC 下跌有关"等未经证实的推断

输出 JSON schema（所有字段都必须存在，可以为空的 list/dict/None；不确定字段填 null / []，并写 data_limitations）：
{
  "symbol": "AMD.US",
  "normalized_symbol": "AMD.US",
  "report_date": "2026-05-20",
  "account_impact": {
    "position_weight": 0.1089,
    "daily_pnl": 1100.0,
    "daily_change_percent": 5.0,
    "contribution_ratio": 0.55,
    "market_value": 11000.0,
    "quantity": 100.0,
    "average_cost": 80.0,
    "unrealized_pnl": 3000.0,
    "unrealized_pnl_percent": 37.5
  },
  "price_action": {
    "current_price": 110.0,
    "previous_close": 104.76,
    "day_change_percent": 5.0,
    "relative_to_benchmark": "跑赢 QQQ 2.3%",
    "relative_to_sector": "跑赢 SMH 0.5%"
  },
  "news_summary": {
    "key_news": ["AMD 发布新一代 AI 芯片", "市场对 AI 芯片需求超预期"],
    "catalyst": "AI 芯片需求爆发",
    "sentiment": "positive",
    "confidence": "high"
  },
  "valuation_summary": {
    "market_cap": 180000000000,
    "pe_ttm": 28.5,
    "ps_ttm": 8.2,
    "valuation_comment": "AI 溢价明显但 PE 仍低于 NVDA",
    "data_limitations": []
  },
  "earnings_summary": {
    "latest_earnings": "2026-Q1 超预期",
    "revenue_growth": "+15% YoY",
    "profit_growth": "+20% YoY",
    "guidance": "全年 AI 芯片指引上调",
    "data_limitations": []
  },
  "technical_summary": {
    "trend": "bullish",
    "support_levels": ["20日均线 105", "前低 100"],
    "resistance_levels": ["前高 115", "历史高点 120"],
    "volume_signal": "成交量放大至 20 日均量 1.5 倍",
    "data_limitations": []
  },
  "cross_asset_summary": {
    "related_assets": ["NVDA.US", "SMH.US", "INTC.US"],
    "relation_note": "AMD 与 NVDA 同为 AI 芯片，同涨同跌相关性强",
    "data_limitations": []
  },
  "likely_drivers": ["AI 芯片需求超预期", "PE 估值修复", "技术面向好突破前高"],
  "watch_points": ["如果 NVDA 下跌，AMD 可能跟随", "注意半导体 ETF SMH 整体走势"],
  "evidence_quality": "high",
  "data_limitations": [],
  "source_trace": ["Longbridge news", "Longbridge calc_indexes", "Longbridge candles"]
}"""

MAX_SUBAGENT_REPAIR_ATTEMPTS = 2


def _structured_output_trace_summary(metadata: dict) -> str:
    return (
        "structured_output:"
        f"contract={metadata.get('contract_name')},"
        f"repaired={metadata.get('repaired')},"
        f"repair_attempts={metadata.get('repair_attempts')},"
        f"fallback_used={metadata.get('fallback_used')},"
        f"error_code={metadata.get('error_code')}"
    )


class DailyReviewSymbolEvidenceAgent:
    def __init__(self, llm_service: LLMService, prompt_service=None) -> None:
        self.llm_service = llm_service
        self.prompt_service = prompt_service

    def generate_symbol_card(
        self,
        report_date: str,
        symbol: str,
        normalized_symbol: str,
        position_item: dict,
        public_context: dict,
        benchmark_context: dict,
    ) -> SymbolEvidenceCard:
        """
        Generate a SymbolEvidenceCard for a single symbol.

        Args:
            report_date: The report date string
            symbol: Raw symbol string (e.g. "AMD")
            normalized_symbol: Normalized symbol (e.g. "AMD.US")
            position_item: IBKR position item dict with account impact fields
            public_context: Public market context from Longbridge for this symbol
            benchmark_context: Benchmark context for relative performance
        """
        prompt = self._build_prompt(
            report_date=report_date,
            symbol=symbol,
            normalized_symbol=normalized_symbol,
            position_item=position_item,
            public_context=public_context,
            benchmark_context=benchmark_context,
        )

        system_prompt, prompt_metadata = resolve_runtime_prompt(
            self.prompt_service,
            "daily_symbol_evidence_card",
            SYSTEM_PROMPT_SYMBOL_CARD,
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        if hasattr(self.llm_service, "chat_with_metadata"):
            result = self.llm_service.chat_with_metadata(
                messages=messages,
                temperature=0.0,
                max_tokens=None,
                response_format={"type": "json_object"},
                call_type="sub_agent",
                agent_name="daily_position_review",
                node_name="symbol_evidence_card",
                prompt_metadata=prompt_metadata,
            )
            response = result.content or ""
        else:
            response = self.llm_service.chat(
                messages=messages,
                temperature=0.0,
                max_tokens=None,
                response_format={"type": "json_object"},
            )

        structured = StructuredOutputRuntime(self.llm_service).parse_validate_repair(
            response,
            build_symbol_evidence_contract(),
            context={
                "report_date": report_date,
                "symbol": symbol,
                "normalized_symbol": normalized_symbol,
                "position_item": position_item,
                "public_context": public_context,
                "benchmark_context": benchmark_context,
            },
        )
        if not structured.ok or structured.payload is None:
            code = structured.error_code or "STRUCTURED_OUTPUT_FAILED"
            message = structured.error_message or "Daily symbol evidence card structured output failed"
            raise ValueError(f"{code}: {message}")

        parsed = structured.payload
        card = self._to_symbol_card(
            parsed=parsed,
            symbol=symbol,
            normalized_symbol=normalized_symbol,
            report_date=report_date,
            position_item=position_item,
        )
        card.source_trace = list(card.source_trace or []) + [f"prompt_metadata:{json.dumps(prompt_metadata, ensure_ascii=False)}"]
        card.source_trace.append(_structured_output_trace_summary(structured.metadata))
        return card

    def _build_prompt(
        self,
        report_date: str,
        symbol: str,
        normalized_symbol: str,
        position_item: dict,
        public_context: dict,
        benchmark_context: dict,
    ) -> str:
        return (
            f"请为 {normalized_symbol} 生成每日复盘证据卡片。\n\n"
            f"报告日期: {report_date}\n"
            f"标的: {symbol} ({normalized_symbol})\n\n"
            f"=== IBKR 账户影响数据（只读不重算）===\n"
            f"{json.dumps(position_item, ensure_ascii=False, default=str)}\n\n"
            f"=== Longbridge 公开数据（用于总结解释）===\n"
            f"{json.dumps(public_context, ensure_ascii=False, default=str)}\n\n"
            f"=== 基准对比上下文 ===\n"
            f"{json.dumps(benchmark_context, ensure_ascii=False, default=str)}\n\n"
            f"请输出严格 JSON 证据卡片，目标是 1000-2000 中文字。\n"
            f"如果公开数据不足某个字段要求，填写空值并在 data_limitations 中说明缺失原因。\n"
            f"不要输出 Markdown，不要代码块，不要额外解释，不要省略字段，只输出 JSON object。"
        )

    def _to_symbol_card(
        self,
        parsed: dict,
        symbol: str,
        normalized_symbol: str,
        report_date: str,
        position_item: dict,
    ) -> SymbolEvidenceCard:
        try:
            ai = parsed.get("account_impact", {})
            pa = parsed.get("price_action", {})
            ns = parsed.get("news_summary", {})
            vs = parsed.get("valuation_summary", {})
            es = parsed.get("earnings_summary", {})
            ts = parsed.get("technical_summary", {})
            cas = parsed.get("cross_asset_summary", {})

            return SymbolEvidenceCard(
                symbol=str(symbol),
                normalized_symbol=str(normalized_symbol),
                report_date=str(report_date),
                account_impact=AccountImpactFields(
                    position_weight=ai.get("position_weight") if ai.get("position_weight") is not None else position_item.get("weight"),
                    daily_pnl=ai.get("daily_pnl") if ai.get("daily_pnl") is not None else position_item.get("daily_pnl"),
                    daily_change_percent=ai.get("daily_change_percent") if ai.get("daily_change_percent") is not None else position_item.get("daily_change_percent"),
                    contribution_ratio=ai.get("contribution_ratio") if ai.get("contribution_ratio") is not None else position_item.get("contribution_ratio"),
                    market_value=ai.get("market_value") if ai.get("market_value") is not None else position_item.get("market_value"),
                    quantity=ai.get("quantity") if ai.get("quantity") is not None else position_item.get("quantity"),
                    average_cost=ai.get("average_cost") if ai.get("average_cost") is not None else position_item.get("average_cost"),
                    unrealized_pnl=ai.get("unrealized_pnl") if ai.get("unrealized_pnl") is not None else position_item.get("unrealized_pnl"),
                    unrealized_pnl_percent=ai.get("unrealized_pnl_percent") if ai.get("unrealized_pnl_percent") is not None else position_item.get("unrealized_pnl_percent"),
                ),
                price_action=PriceActionFields(
                    current_price=pa.get("current_price"),
                    previous_close=pa.get("previous_close"),
                    day_change_percent=pa.get("day_change_percent"),
                    relative_to_benchmark=pa.get("relative_to_benchmark"),
                    relative_to_sector=pa.get("relative_to_sector"),
                ),
                news_summary=NewsSummaryFields(
                    key_news=ns.get("key_news", []) if isinstance(ns.get("key_news"), list) else [],
                    catalyst=ns.get("catalyst"),
                    sentiment=ns.get("sentiment"),
                    confidence=ns.get("confidence"),
                ),
                valuation_summary=ValuationSummaryFields(
                    market_cap=vs.get("market_cap"),
                    pe_ttm=vs.get("pe_ttm"),
                    ps_ttm=vs.get("ps_ttm"),
                    valuation_comment=vs.get("valuation_comment"),
                    data_limitations=vs.get("data_limitations", []) if isinstance(vs.get("data_limitations"), list) else [],
                ),
                earnings_summary=EarningsSummaryFields(
                    latest_earnings=es.get("latest_earnings"),
                    revenue_growth=es.get("revenue_growth"),
                    profit_growth=es.get("profit_growth"),
                    guidance=es.get("guidance"),
                    data_limitations=es.get("data_limitations", []) if isinstance(es.get("data_limitations"), list) else [],
                ),
                technical_summary=TechnicalSummaryFields(
                    trend=ts.get("trend"),
                    support_levels=ts.get("support_levels", []) if isinstance(ts.get("support_levels"), list) else [],
                    resistance_levels=ts.get("resistance_levels", []) if isinstance(ts.get("resistance_levels"), list) else [],
                    volume_signal=ts.get("volume_signal"),
                    data_limitations=ts.get("data_limitations", []) if isinstance(ts.get("data_limitations"), list) else [],
                ),
                cross_asset_summary=CrossAssetSummaryFields(
                    related_assets=cas.get("related_assets", []) if isinstance(cas.get("related_assets"), list) else [],
                    relation_note=cas.get("relation_note"),
                    data_limitations=cas.get("data_limitations", []) if isinstance(cas.get("data_limitations"), list) else [],
                ),
                likely_drivers=parsed.get("likely_drivers", []) if isinstance(parsed.get("likely_drivers"), list) else [],
                watch_points=parsed.get("watch_points", []) if isinstance(parsed.get("watch_points"), list) else [],
                evidence_quality=parsed.get("evidence_quality", "medium") if parsed.get("evidence_quality") in ("high", "medium", "low") else "medium",
                data_limitations=parsed.get("data_limitations", []) if isinstance(parsed.get("data_limitations"), list) else [],
                source_trace=parsed.get("source_trace", []) if isinstance(parsed.get("source_trace"), list) else [],
            )
        except Exception as exc:
            raise ValueError(f"Failed to parse sub-agent response into SymbolEvidenceCard: {exc}") from exc
