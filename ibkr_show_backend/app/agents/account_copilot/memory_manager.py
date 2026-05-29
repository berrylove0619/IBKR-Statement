from __future__ import annotations

import re

TOPIC_KEYWORDS = {
    "risk": {"risk", "风险", "回撤", "集中", "concentration"},
    "trade_review": {"review", "复盘", "卖飞", "交易表现"},
    "trade_decision": {"建仓", "加仓", "减仓", "持有", "entry", "holding", "decision"},
    "daily_review": {"daily", "每日", "今天", "归因"},
    "position_sizing": {"仓位", "position", "sizing", "weight"},
    "cash_flow": {"cash", "现金", "dividend", "股息", "interest"},
    "pnl": {"pnl", "盈亏", "收益"},
    "valuation": {"估值", "valuation", "pe", "pb"},
    "news": {"news", "新闻", "催化"},
}

SYMBOL_RE = re.compile(r"\b[A-Z]{1,6}(?:\.(?:US|HK|SH|SZ|SG))?\b")


def extract_symbols(text: str) -> list[str]:
    ignored = {"IBKR", "LLM", "MCP", "API", "JSON", "USD", "HKD", "CNY"}
    symbols = []
    for match in SYMBOL_RE.findall(text.upper()):
        base = match.split(".")[0]
        if base not in ignored and match not in symbols:
            symbols.append(match)
    return symbols


def extract_topics(text: str) -> list[str]:
    lower = text.lower()
    topics = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(keyword.lower() in lower for keyword in keywords):
            topics.append(topic)
    return topics


def estimate_context_chars(messages: list[dict]) -> int:
    return sum(len(str(item.get("content") or "")) for item in messages)
