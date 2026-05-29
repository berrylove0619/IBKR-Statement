from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings

DAILY_POSITION_REVIEW_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "dynamic": False,
        "properties": {
            "id": {"type": "keyword"},
            "report_date": {"type": "date"},
            "review_type": {"type": "keyword"},
            "summary": {"type": "text"},
            "account_conclusion": {"type": "text"},
            "attribution_summary": {"type": "text"},
            "major_contributors_analysis": {"type": "object", "enabled": False},
            "major_drags_analysis": {"type": "object", "enabled": False},
            "focus_symbol_analyses": {"type": "object", "enabled": False},
            "market_context": {"type": "text"},
            "risk_analysis": {"type": "text"},
            "tomorrow_watchlist": {"type": "object", "enabled": False},
            "operation_observation": {"type": "text"},
            "data_limitations": {"type": "text"},
            "evidence_used": {"type": "text"},
            "data_source_summary": {"type": "object", "enabled": False},
            "display_context": {"type": "object", "enabled": False},
            "status": {"type": "keyword"},
            "agent_mode": {"type": "keyword"},
            "fallback_used": {"type": "boolean"},
            "fallback_reason": {"type": "text"},
            "graph_version": {"type": "keyword"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DailyPositionReviewRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    def save_review(self, document: dict) -> dict:
        self.es_client.create_index_if_missing(self.settings.es_daily_position_review_index, DAILY_POSITION_REVIEW_INDEX_BODY)
        now = utc_now_iso()
        review_id = document.get("id") or str(document["report_date"])
        existing = self.get_review(review_id)
        stored = {
            **_compact_review_for_storage(document),
            "id": review_id,
            "review_type": document.get("review_type") or "daily_position_review",
            "created_at": document.get("created_at") or (existing or {}).get("created_at") or now,
            "updated_at": now,
        }
        self.es_client.index_document(index=self.settings.es_daily_position_review_index, id=review_id, document=stored)
        return stored

    def get_review(self, review_id: str) -> dict | None:
        try:
            response = self.es_client.get(index=self.settings.es_daily_position_review_index, id=review_id)
        except ESIndexNotFoundError:
            return None
        return response.get("_source") if response else None

    def get_review_by_date(self, report_date: str) -> dict | None:
        return self.get_review(report_date)

    def list_reviews(self, limit: int = 30) -> list[dict]:
        try:
            response = self.es_client.search(
                index=self.settings.es_daily_position_review_index,
                body={
                    "query": {"match_all": {}},
                    "sort": [{"report_date": {"order": "desc"}}],
                    "size": limit,
                    "_source": True,
                },
            )
        except ESIndexNotFoundError:
            return []
        return [hit["_source"] for hit in response.get("hits", {}).get("hits", [])]


def _compact_review_for_storage(document: dict) -> dict:
    """Keep only display-safe daily review fields in Elasticsearch.

    Daily review detail/audit payloads can contain symbol-specific news, card
    packs, tool traces, and context dictionaries with hundreds of unique keys.
    Those do not belong in ES because they expand dynamic mappings until the
    index hits index.mapping.total_fields.limit.
    """

    stored = {
        "report_date": str(document.get("report_date") or document.get("id") or ""),
        "summary": _text(document.get("summary")),
        "account_conclusion": _text(document.get("account_conclusion")),
        "attribution_summary": _text(document.get("attribution_summary")),
        "major_contributors_analysis": _compact_analysis_items(document.get("major_contributors_analysis")),
        "major_drags_analysis": _compact_analysis_items(document.get("major_drags_analysis")),
        "focus_symbol_analyses": _compact_analysis_items(document.get("focus_symbol_analyses")),
        "market_context": _text(document.get("market_context")),
        "risk_analysis": _text(document.get("risk_analysis")),
        "tomorrow_watchlist": _compact_watchlist(document.get("tomorrow_watchlist")),
        "operation_observation": _text(document.get("operation_observation")),
        "data_limitations": _string_list(document.get("data_limitations")),
        "evidence_used": _string_list(document.get("evidence_used")),
        "data_source_summary": _compact_data_sources(document.get("data_source_summary")),
        "display_context": _compact_display_context(document.get("deterministic_context")),
        "metadata": _compact_metadata(document.get("metadata")),
        "run_trace": _compact_run_trace(document.get("run_trace")),
        "subagent_card_pack": _compact_subagent_card_pack(document.get("subagent_card_pack")),
        "subagent_trace": _compact_subagent_trace(document.get("subagent_trace")),
        "evidence_card_summary": document.get("evidence_card_summary") if isinstance(document.get("evidence_card_summary"), dict) else None,
        "status": document.get("status"),
        "agent_mode": document.get("agent_mode") or (document.get("metadata") or {}).get("agent_mode"),
        "fallback_used": bool(document.get("fallback_used", False)),
        "fallback_reason": document.get("fallback_reason"),
        "graph_version": document.get("graph_version") or (document.get("metadata") or {}).get("graph_version"),
    }
    return {key: value for key, value in stored.items() if value not in (None, "", [], {})}


def _compact_metadata(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, Any] = {}
    for key in (
        "prompt_metadata",
        "structured_output",
        "agent_run_id",
    ):
        if key in value:
            result[key] = _compact_context_value(value[key])
    return result or None


def _compact_run_trace(value: Any) -> list[dict] | None:
    if not isinstance(value, list):
        return None
    result: list[dict] = []
    for item in value[:40]:
        if not isinstance(item, dict):
            continue
        compacted = {
            "event": item.get("event"),
            "node_name": item.get("node_name"),
            "status": item.get("status"),
            "elapsed_ms": item.get("elapsed_ms"),
            "tools_called": item.get("tools_called"),
            "tool_call_count": item.get("tool_call_count"),
            "fallback_used": item.get("fallback_used"),
            "fallback_reason": item.get("fallback_reason"),
            "structured_output": item.get("structured_output"),
        }
        runtime_trace = item.get("runtime_trace")
        if isinstance(runtime_trace, list):
            compacted["runtime_trace"] = [
                {
                    "event": event.get("event"),
                    "contract_name": event.get("contract_name"),
                    "ok": event.get("ok"),
                    "repaired": event.get("repaired"),
                    "repair_attempts": event.get("repair_attempts"),
                    "fallback_used": event.get("fallback_used"),
                    "error_code": event.get("error_code"),
                    "schema_validation_passed": event.get("schema_validation_passed"),
                }
                for event in runtime_trace
                if isinstance(event, dict) and (event.get("event") == "structured_output_result" or event.get("contract_name"))
            ][:10]
        if compacted.get("structured_output") or compacted.get("runtime_trace"):
            result.append({key: val for key, val in compacted.items() if val not in (None, "", [], {})})
    return result or None


def _compact_subagent_card_pack(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    symbol_cards = []
    for card in value.get("symbol_cards") or []:
        if not isinstance(card, dict):
            continue
        source_trace = _string_list(card.get("source_trace"))
        if any("structured_output:" in item for item in source_trace):
            symbol_cards.append(
                {
                    "symbol": card.get("symbol"),
                    "normalized_symbol": card.get("normalized_symbol"),
                    "report_date": card.get("report_date"),
                    "evidence_quality": card.get("evidence_quality"),
                    "data_limitations": _string_list(card.get("data_limitations")),
                    "source_trace": source_trace,
                }
            )
    macro_card = value.get("macro_card") if isinstance(value.get("macro_card"), dict) else None
    macro_source_trace = _string_list(macro_card.get("source_trace")) if macro_card else []
    result = {
        "report_date": value.get("report_date"),
        "symbol_cards": symbol_cards,
        "macro_card": {
            "report_date": macro_card.get("report_date"),
            "market_regime": macro_card.get("market_regime"),
            "risk_sentiment": macro_card.get("risk_sentiment"),
            "tech_sentiment": macro_card.get("tech_sentiment"),
            "data_limitations": _string_list(macro_card.get("data_limitations")),
            "source_trace": macro_source_trace,
        } if macro_card and any("structured_output:" in item for item in macro_source_trace) else None,
    }
    return {key: val for key, val in result.items() if val not in (None, "", [], {})} or None


def _compact_subagent_trace(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    return {
        key: _compact_context_value(value.get(key))
        for key in ("symbol_agent_calls", "macro_agent_calls", "fallback_reasons", "errors")
        if value.get(key) not in (None, "", [], {})
    } or None


def _compact_display_context(value: Any) -> dict | None:
    """Preserve a lightweight deterministic context for frontend first-screen.

    Keeps overview, rankings, risk, focus_symbols, attribution_quality, and
    data_quality but NOT symbol_public_context which would blow up ES mappings.
    """
    if not isinstance(value, dict):
        return None
    if not value.get("overview") and not value.get("rankings"):
        return None
    result: dict[str, Any] = {}
    for key in (
        "report_date", "data_sources", "overview", "rankings", "risk",
        "focus_symbols", "attribution_quality", "data_quality",
    ):
        val = value.get(key)
        if val is not None:
            result[key] = _compact_context_value(val)
    return result


def _compact_context_value(value: Any) -> Any:
    """Recursively compact context values to avoid ES field explosion."""
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, dict):
        compacted = {}
        for k, v in value.items():
            if len(compacted) >= 60:
                break
            if v not in (None, "", [], {}):
                compacted[str(k)] = _compact_context_value(v)
        return compacted
    if isinstance(value, list):
        return [_compact_context_value(item) for item in value[:30]]
    return str(value)[:1000]


def _compact_analysis_items(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [_compact_analysis_item(item) for item in value[:20] if isinstance(item, dict)]


def _compact_analysis_item(item: dict) -> dict:
    known = {
        "symbol": _text(item.get("symbol") or item.get("ticker")),
        "title": _text(item.get("title") or item.get("name")),
        "summary": _text(item.get("summary") or item.get("explanation") or item.get("analysis")),
        "reason": _text(item.get("reason")),
        "impact": _text(item.get("impact") or item.get("pnl_impact")),
    }
    extras = {
        key: value
        for key, value in item.items()
        if key not in {"symbol", "ticker", "title", "name", "summary", "explanation", "analysis", "reason", "impact", "pnl_impact"}
        and value not in (None, "", [], {})
    }
    if extras:
        known["details"] = _json_summary(extras)
    return {key: value for key, value in known.items() if value}


def _compact_watchlist(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:20]:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "symbol": _text(item.get("symbol") or item.get("ticker") or item.get("name")),
                "reason": _text(item.get("reason") or item.get("summary")),
                "conditions": _text(item.get("conditions") or item.get("condition") or item.get("trigger")),
            }
        )
    return result


def _compact_data_sources(value: Any) -> dict:
    source = value if isinstance(value, dict) else {}
    allowed = ["account_data", "position_data", "trade_data", "public_market_data", "review_data"]
    return {key: _text(source.get(key)) for key in allowed if source.get(key)}


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return [_text(value)]
    return [_text(item) for item in value[:80] if _text(item)]


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:2000]
    if isinstance(value, (int, float, bool)):
        return str(value)
    return _json_summary(value)


def _json_summary(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)[:2000]
    except TypeError:
        return str(value)[:2000]
