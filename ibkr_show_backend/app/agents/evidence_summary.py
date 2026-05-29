"""
Evidence Summary 构建器。

将完整的 evidence_pack 转换为前端可安全展示的摘要。
- 不返回完整 evidence_pack
- 不返回 raw_llm_response
- 不暴露敏感字段（token、api key、password、cookie、authorization 等）
"""

from typing import Any
import re

SENSITIVE_KEYS = {
    "token",
    "api_key",
    "secret",
    "password",
    "smtp",
    "cookie",
    "authorization",
    "auth",
    "credential",
    "private_key",
    "access_token",
    "refresh_token",
    "bearer",
}

SENSITIVE_PATTERNS = [
    (re.compile(r'\btoken\s*[=:]\s*["\']?([^\s,"\'}]+)["\']?', re.IGNORECASE), 'token=[REDACTED]'),
    (re.compile(r'\bapi_key\s*[=:]\s*["\']?([^\s,"\'}]+)["\']?', re.IGNORECASE), 'api_key=[REDACTED]'),
    (re.compile(r'\bpassword\s*[=:]\s*["\']?([^\s,"\'}]+)["\']?'), 'password=[REDACTED]'),
    # authorization + Bearer must come before plain authorization to avoid token leakage
    (re.compile(r'\bauthorization\s*[=:]\s*["\']?Bearer\s+([^,\s"\'}]+)["\']?', re.IGNORECASE), 'authorization=[REDACTED]'),
    (re.compile(r'\bauthorization\s*[=:]\s*["\']?([^\s,"\'}]+)["\']?', re.IGNORECASE), 'authorization=[REDACTED]'),
    (re.compile(r'\bBearer\s+([^\s,"\'}]+)', re.IGNORECASE), 'Bearer [REDACTED]'),
    (re.compile(r'\bsmtp_password\s*[=:]\s*["\']?([^\s,"\'}]+)["\']?'), 'smtp_password=[REDACTED]'),
    (re.compile(r'\baccess_token\s*[=:]\s*["\']?([^\s,"\'}]+)["\']?', re.IGNORECASE), 'access_token=[REDACTED]'),
    (re.compile(r'\brefresh_token\s*[=:]\s*["\']?([^\s,"\'}]+)["\']?', re.IGNORECASE), 'refresh_token=[REDACTED]'),
    (re.compile(r'\bflex_token\s*[=:]\s*["\']?([^\s,"\'}]+)["\']?'), 'flex_token=[REDACTED]'),
]


def _sanitize_text(value: str) -> str:
    if not isinstance(value, str):
        return value
    result = value
    for pattern, replacement in SENSITIVE_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: "[REDACTED]" if _is_sensitive_key(k) else _sanitize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    return value

SECTION_SUMMARIES: dict[str, str] = {
    "account_context": "账户净值、现金、可动用流动性、前五大持仓",
    "position_context": "当前持仓、仓位权重、成本和浮盈亏",
    "trade_history_context": "历史交易记录、最近交易和交易统计",
    "review_context": "历史复盘、错误标签、个人交易模式",
    "market_context": "价格趋势、Benchmark、技术位置",
    "company_context": "公司基本信息、财报摘要",
    "valuation_context": "估值、Quote、市值、PE/PB 等",
    "external_events": "新闻、公告、事件",
    "risk_context": "集中度、现金比例、主题暴露、仓位风险",
    "daily_position_context": "每日账户涨跌、贡献拖累、风险排行",
}


def _is_sensitive_key(key: str) -> bool:
    key_lower = str(key).lower()
    return any(s in key_lower for s in SENSITIVE_KEYS)


def _section_status(section_name: str, section_data: Any, budget_report: dict | None) -> str:
    if section_data is None or section_data == {} or section_data == []:
        return "missing"
    if budget_report and budget_report.get("truncated"):
        return "partial"
    limitations = _get_limitations(section_data)
    if limitations:
        return "partial"
    return "available"


def _get_limitations(value: Any) -> list[str]:
    if isinstance(value, dict):
        return value.get("data_limitations") or []
    return []


def _build_section_summary(section_name: str, section_data: Any, budget_report: dict | None) -> dict:
    status = _section_status(section_name, section_data, budget_report)
    limitations = _get_limitations(section_data)
    dropped = budget_report.get("dropped_items") if budget_report else {}
    item_count = _count_items(section_data)

    return {
        "section": section_name,
        "source": _guess_source(section_data),
        "status": status,
        "summary": SECTION_SUMMARIES.get(section_name, section_name),
        "item_count": item_count,
        "freshness": _guess_freshness(section_data),
        "budget_truncated": budget_report.get("truncated", False) if budget_report else False,
        "dropped_items": dropped if dropped else {},
        "limitations": limitations,
    }


def _count_items(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in ("positions", "recent_trades", "top_positions", "news", "periods"):
            if key in value and isinstance(value[key], list):
                return len(value[key])
        return len(value)
    return 0


def _guess_source(value: Any) -> str:
    if isinstance(value, dict):
        src = value.get("source", "")
        if src:
            return src
        if "IBKR" in str(value):
            return "IBKR"
        if "Longbridge" in str(value):
            return "Longbridge"
    return "unknown"


def _guess_freshness(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("report_date", "date", "updated_at", "as_of"):
            if key in value:
                return str(value[key])
    return None


def _build_tools_used(run_trace: list[dict] | None) -> list[dict]:
    if not run_trace:
        return []
    tools = []
    for event in run_trace:
        if event.get("event") not in ("tool_start", "tool_finish"):
            continue
        if event.get("event") == "tool_finish":
            obs = event.get("observation") or {}
            tools.append({
                "name": event.get("tool", ""),
                "ok": event.get("ok", False),
                "summary": event.get("summary", ""),
                "original_size": obs.get("original_size"),
                "final_size": obs.get("final_size"),
                "truncated": obs.get("truncated", False),
            })
    return tools


def _collect_missing_data(evidence_pack: dict) -> list[str]:
    missing = []
    required_sections = [
        "account_context",
        "position_context",
        "company_context",
        "valuation_context",
        "market_context",
    ]
    for section in required_sections:
        if section not in evidence_pack or not evidence_pack[section]:
            missing.append(f"{section} is missing or empty")
    return missing


def _collect_data_limitations(evidence_pack: dict) -> list[str]:
    limitations = []
    for section_name, section_data in evidence_pack.items():
        if isinstance(section_data, dict) and section_data.get("data_limitations"):
            limitations.extend(section_data["data_limitations"])
    return limitations


def _build_budget_summary(evidence_pack: dict, run_trace: list[dict] | None) -> dict:
    total_original = 0
    total_final = 0
    truncated_sections = []
    all_dropped = {}

    for section_name, section_data in evidence_pack.items():
        if not isinstance(section_data, dict):
            continue
        report = section_data.get("budget_report")
        if report:
            total_original += report.get("original_size", 0)
            total_final += report.get("final_size", 0)
            if report.get("truncated"):
                truncated_sections.append(section_name)
            for k, v in report.get("dropped_items", {}).items():
                all_dropped[f"{section_name}.{k}"] = v

    return {
        "total_original_size": total_original,
        "total_final_size": total_final,
        "truncated_sections": truncated_sections,
        "dropped_items": all_dropped,
    }


def build_evidence_summary(
    evidence_pack: dict,
    run_trace: list[dict] | None = None,
) -> dict:
    """
    将完整的 evidence_pack 转换为前端可安全展示的摘要。

    Args:
        evidence_pack: 完整证据包（来自 Agent 生成的 document.evidence_pack）
        run_trace: Agent 运行轨迹（可选）

    Returns:
        安全、可读的证据摘要字典，不包含 raw evidence_pack 或 raw_llm_response
    """
    data_sources = evidence_pack.get("data_sources", {})
    evidence_sections = []

    section_order = [
        "account_context",
        "position_context",
        "trade_history_context",
        "review_context",
        "market_context",
        "company_context",
        "valuation_context",
        "external_events",
        "risk_context",
        "daily_position_context",
    ]

    for section_name in section_order:
        section_data = evidence_pack.get(section_name)
        budget_report = None
        if isinstance(section_data, dict):
            budget_report = section_data.get("budget_report")
        section_summary = _build_section_summary(section_name, section_data, budget_report)
        evidence_sections.append(section_summary)

    # add any extra sections not in the ordered list
    for section_name, section_data in evidence_pack.items():
        if isinstance(section_name, str) and section_name not in section_order and isinstance(section_data, dict):
            budget_report = section_data.get("budget_report") if isinstance(section_data, dict) else None
            section_summary = _build_section_summary(section_name, section_data, budget_report)
            evidence_sections.append(section_summary)

    missing_data = _collect_missing_data(evidence_pack)
    data_limitations = _collect_data_limitations(evidence_pack)
    tools_used = _build_tools_used(run_trace)
    budget_summary = _build_budget_summary(evidence_pack, run_trace)

    summary = {
        "data_sources": data_sources,
        "evidence_sections": evidence_sections,
        "tools_used": tools_used,
        "missing_data": missing_data,
        "data_limitations": data_limitations,
        "budget_summary": budget_summary,
        "llm_input_policy": {
            "account_data_policy": data_sources.get("account_data", "IBKR_ONLY"),
            "public_data_policy": data_sources.get("public_market_data", "LONGBRIDGE_PUBLIC_ONLY"),
            "raw_sensitive_data_exposed": False,
        },
    }
    return _sanitize_value(summary)