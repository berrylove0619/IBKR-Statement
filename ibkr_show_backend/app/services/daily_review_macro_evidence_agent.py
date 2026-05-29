"""
Sub-agent for generating MacroEvidenceCard for daily position review.

Responsibilities:
- Generate macro market evidence card for one report date
- Input: report_date, benchmark context, focus symbols, account return, public macro/news context
- Output: MacroEvidenceCard with market background, QQQ/SPY/SMH/DIA relative performance,
  tech/semiconductor/risk sentiment, possible macro factors affecting account
- If data is missing, write to data_limitations
"""

from __future__ import annotations

import json

from app.agents.daily_review_evidence_cards import MacroEvidenceCard
from app.agents.daily_review_structured_outputs import build_macro_evidence_contract
from app.agents.prompt_runtime import resolve_runtime_prompt
from app.agents.structured_output.runtime import StructuredOutputRuntime
from app.services.llm_service import LLMService


SYSTEM_PROMPT_MACRO_CARD = """你是每日持仓复盘的子 Agent，负责生成"宏观证据卡片"（MacroEvidenceCard）。
你的任务是基于输入中的市场基准数据、公开宏观/新闻上下文，总结当日市场整体背景、板块表现、风险偏好、利率/汇率背景和科技情绪。

重要约束：
1. 只能引用输入数据，不能自行编造宏观数据。
2. 不要编造 Fed、CPI、利率、汇率、就业、监管等宏观事件；macro_events 只能放输入中能支持的事件。
3. 如果公开宏观数据缺失，必须写入 data_limitations，不能编造原因。
4. market_regime 不确定或信号冲突时使用 mixed，不要强行 risk_on / risk_off。
5. risk_sentiment 必须基于基准表现、波动、风险资产相对表现或输入新闻；tech_sentiment 必须基于科技指数、半导体、重点科技股或输入新闻。
6. 不要把宏观背景包装成买卖指令，只输出观察和解释。
7. 最终必须输出严格 JSON object，不要输出 Markdown，不要代码块，不要额外解释，不要省略字段。
8. 输出应尽量简洁，目标 500-1000 中文字。

输出 JSON schema（所有字段都必须存在，可以为空；不确定字段填 null / []，并写 data_limitations）：
{
  "report_date": "2026-05-20",
  "benchmark_context": {
    "QQQ": {"return_percent": 1.5, "account_excess_return_percent": -0.5},
    "SPY": {"return_percent": 0.8}
  },
  "market_regime": "risk_on",
  "sector_context": "科技领涨",
  "macro_events": ["Fed 维持利率不变", "CPI 超预期"],
  "rate_fx_context": "美债收益率小幅上行，美元指数走强",
  "risk_sentiment": "risk_on",
  "tech_sentiment": "positive",
  "data_limitations": [],
  "source_trace": ["Longbridge candles", "Longbridge news"]
}"""

MAX_SUBAGENT_REPAIR_ATTEMPTS = 2


class DailyReviewMacroEvidenceAgent:
    def __init__(self, llm_service: LLMService, prompt_service=None) -> None:
        self.llm_service = llm_service
        self.prompt_service = prompt_service

    def generate_macro_card(
        self,
        report_date: str,
        benchmark_context: dict,
        focus_symbols: list[str],
        account_return: float | None,
        macro_news_context: dict | None = None,
    ) -> MacroEvidenceCard:
        """
        Generate a MacroEvidenceCard for a report date.

        Args:
            report_date: The report date string
            benchmark_context: Benchmark return context (QQQ, SPY, SMH, DIA)
            focus_symbols: List of focus symbols in the portfolio
            account_return: Account daily return percent
            macro_news_context: Optional public macro/news context from Longbridge
        """
        prompt = self._build_prompt(
            report_date=report_date,
            benchmark_context=benchmark_context,
            focus_symbols=focus_symbols,
            account_return=account_return,
            macro_news_context=macro_news_context,
        )

        system_prompt, prompt_metadata = resolve_runtime_prompt(
            self.prompt_service,
            "daily_macro_evidence_card",
            SYSTEM_PROMPT_MACRO_CARD,
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
                node_name="macro_evidence_card",
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
            build_macro_evidence_contract(),
            context={
                "report_date": report_date,
                "benchmark_context": benchmark_context,
                "focus_symbols": focus_symbols,
                "account_return": account_return,
                "macro_news_context": macro_news_context,
            },
        )
        if not structured.ok or structured.payload is None:
            code = structured.error_code or "STRUCTURED_OUTPUT_FAILED"
            message = structured.error_message or "Daily macro evidence card structured output failed"
            raise ValueError(f"{code}: {message}")

        parsed = structured.payload
        card = self._to_macro_card(parsed=parsed, report_date=report_date, benchmark_context=benchmark_context)
        card.source_trace = list(card.source_trace or []) + [f"prompt_metadata:{json.dumps(prompt_metadata, ensure_ascii=False)}"]
        card.source_trace.append(_structured_output_trace_summary(structured.metadata))
        return card

    def _build_prompt(
        self,
        report_date: str,
        benchmark_context: dict,
        focus_symbols: list[str],
        account_return: float | None,
        macro_news_context: dict | None,
    ) -> str:
        focus_list = ", ".join(focus_symbols) if focus_symbols else "无"
        account_ret_str = f"{account_return:.2f}%" if account_return is not None else "不可用"

        macro_ctx_str = json.dumps(macro_news_context, ensure_ascii=False, default=str) if macro_news_context else "无可用宏观/新闻数据"

        return (
            f"请为 {report_date} 生成宏观证据卡片。\n\n"
            f"报告日期: {report_date}\n"
            f"账户当日收益率: {account_ret_str}\n"
            f"重点持仓标的: {focus_list}\n\n"
            f"=== 基准行情数据 ===\n"
            f"{json.dumps(benchmark_context, ensure_ascii=False, default=str)}\n\n"
            f"=== 公开宏观/新闻上下文 ===\n"
            f"{macro_ctx_str}\n\n"
            f"请输出严格 JSON 宏观证据卡片，目标 500-1000 中文字。\n"
            f"market_regime 可选值: risk_on | risk_off | mixed\n"
            f"risk_sentiment 可选值: risk_on | risk_off | neutral\n"
            f"tech_sentiment 可选值: positive | negative | neutral\n"
            f"如果数据不足某个字段要求，填写空值并在 data_limitations 中说明缺失原因。\n"
            f"不要输出 Markdown，不要代码块，不要额外解释，不要省略字段，只输出 JSON object。"
        )

    def _to_macro_card(
        self,
        parsed: dict,
        report_date: str,
        benchmark_context: dict,
    ) -> MacroEvidenceCard:
        try:
            return MacroEvidenceCard(
                report_date=str(report_date),
                benchmark_context=parsed.get("benchmark_context", benchmark_context or {}),
                market_regime=parsed.get("market_regime"),
                sector_context=parsed.get("sector_context"),
                macro_events=parsed.get("macro_events", []) if isinstance(parsed.get("macro_events"), list) else [],
                rate_fx_context=parsed.get("rate_fx_context"),
                risk_sentiment=parsed.get("risk_sentiment"),
                tech_sentiment=parsed.get("tech_sentiment"),
                data_limitations=parsed.get("data_limitations", []) if isinstance(parsed.get("data_limitations"), list) else [],
                source_trace=parsed.get("source_trace", []) if isinstance(parsed.get("source_trace"), list) else [],
            )
        except Exception as exc:
            raise ValueError(f"Failed to parse sub-agent response into MacroEvidenceCard: {exc}") from exc


def _structured_output_trace_summary(metadata: dict) -> str:
    return (
        "structured_output:"
        f"contract={metadata.get('contract_name')},"
        f"repaired={metadata.get('repaired')},"
        f"repair_attempts={metadata.get('repair_attempts')},"
        f"fallback_used={metadata.get('fallback_used')},"
        f"error_code={metadata.get('error_code')}"
    )
