from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.clients.es_client import ElasticsearchClient
from app.core.config import Settings
from app.services.daily_position_review_service import DailyPositionReviewService


SENSITIVE_KEYWORDS = frozenset([
    "token", "password", "secret", "api_key", "apikey", "auth",
    "flex_token", "smtp_password", "llm_api_key", "session",
])


def _is_sensitive_key(key: str) -> bool:
    key_lower = key.lower()
    return any(kw in key_lower for kw in SENSITIVE_KEYWORDS)


def _strip_sensitive(data: Any) -> Any:
    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            if not _is_sensitive_key(k):
                result[k] = _strip_sensitive(v)
        return result
    elif isinstance(data, list):
        return [_strip_sensitive(item) for item in data]
    return data


def _round_float(value: Any, digits: int = 4) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _safe_get(d: dict, *keys, default=None) -> Any:
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, default)
        else:
            return default
    return d


@dataclass
class EmailAttachment:
    filename: str
    content: str
    maintype: str
    subtype: str


class DailyAccountSnapshotService:
    TRADES_LIMIT = 50
    CASH_FLOWS_LIMIT = 50

    def __init__(
        self,
        es_client: ElasticsearchClient,
        settings: Settings,
        daily_review_service: DailyPositionReviewService,
    ) -> None:
        self.es_client = es_client
        self.settings = settings
        self.daily_review_service = daily_review_service

    def build_snapshot(self, report_date: str | None = None) -> dict:
        effective_date = report_date or self._latest_report_date()
        if not effective_date:
            raise ValueError("No IBKR account report date is available")

        context = self.daily_review_service.build_review_context(effective_date)

        overview = context.get("overview", {})
        positions = context.get("positions", [])
        rankings = context.get("rankings", {})
        risk = context.get("risk", {})
        data_quality = context.get("data_quality", {})

        account = self._build_account(overview, effective_date)
        top_positions = self._build_top_positions(positions)
        top_contributors = (rankings.get("profit_contributors") or [])[:10]
        top_drags = (rankings.get("loss_drags") or [])[:10]

        trades_result = self._fetch_trades_today(effective_date)
        trades = trades_result["items"]
        trade_summary = self._fetch_trade_summary(effective_date)
        trades_truncated = trades_result["truncated"]
        trades_total_count = trades_result["total_count"]
        trades_included_count = trades_result["included_count"]

        cash_flows_result = self._fetch_cash_flows_today(effective_date)
        cash_flows = cash_flows_result["items"]
        cash_flow_summary = self._fetch_cash_flow_summary(effective_date)
        cf_truncated = cash_flows_result["truncated"]
        cf_total_count = cash_flows_result["total_count"]
        cf_included_count = cash_flows_result["included_count"]

        return {
            "schema_version": "daily_account_snapshot_v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "report_date": effective_date,
            "data_scope": "single_report_date_only",
            "data_source_summary": {
                "account_data": "IBKR_ONLY",
                "position_data": "IBKR_ONLY",
                "trade_data": "IBKR_ONLY",
                "cash_flow_data": "IBKR_ONLY",
            },
            "account": account,
            "risk": _strip_sensitive(risk) if isinstance(risk, dict) else risk,
            "positions": _strip_sensitive(positions),
            "top_positions": _strip_sensitive(top_positions),
            "top_contributors": _strip_sensitive(top_contributors),
            "top_drags": _strip_sensitive(top_drags),
            "trade_summary": trade_summary,
            "trades_today": _strip_sensitive(trades),
            "trades_truncated": trades_truncated,
            "trades_total_count": trades_total_count,
            "trades_included_count": trades_included_count,
            "cash_flow_summary": cash_flow_summary,
            "cash_flows_today": _strip_sensitive(cash_flows),
            "cash_flows_truncated": cf_truncated,
            "cash_flows_total_count": cf_total_count,
            "cash_flows_included_count": cf_included_count,
            "data_quality": _strip_sensitive(data_quality) if isinstance(data_quality, dict) else data_quality,
        }

    def _latest_report_date(self) -> str | None:
        dates = self.daily_review_service.list_report_dates(limit=1)
        return dates[0] if dates else None

    def _build_account(self, overview: dict, report_date: str) -> dict:
        return {
            "report_date": report_date,
            "currency": overview.get("currency"),
            "total_equity": _round_float(overview.get("total_equity"), 2),
            "cash": _round_float(overview.get("cash"), 2),
            "stock_value": _round_float(overview.get("stock_value") or overview.get("total_position_value"), 2),
            "daily_pnl": _round_float(overview.get("daily_pnl"), 2),
            "daily_return_percent": _round_float(overview.get("daily_return_percent"), 4),
            "cash_ratio": _round_float(overview.get("cash_ratio"), 6),
        }

    def _build_top_positions(self, positions: list[dict]) -> list[dict]:
        sorted_by_weight = sorted(positions, key=lambda p: p.get("weight") or 0.0, reverse=True)
        return sorted_by_weight[:10]

    def _fetch_trades_today(self, report_date: str) -> dict:
        response = self.es_client.search(
            index=self.settings.es_trade_index,
            body={
                "query": {"bool": {"filter": [{"term": {"trade_date": report_date}}]}},
                "sort": [{"date_time": {"order": "desc"}}],
                "size": self.TRADES_LIMIT,
                "_source": [
                    "trade_date", "date_time", "symbol", "asset_class", "buy_sell",
                    "quantity", "trade_price", "proceeds", "ib_commission",
                    "net_cash", "fifo_pnl_realized", "currency",
                    "transaction_id", "trade_id",
                ],
                "track_total_hits": True,
            },
        )
        hits = response.get("hits", {})
        total = hits.get("total", {}).get("value", 0)
        items = [hit["_source"] for hit in hits.get("hits", [])]

        truncated = total > self.TRADES_LIMIT
        included_count = min(total, self.TRADES_LIMIT)

        return {
            "items": items,
            "truncated": truncated,
            "total_count": total,
            "included_count": included_count,
        }

    def _fetch_trade_summary(self, report_date: str) -> dict:
        response = self.es_client.search(
            index=self.settings.es_trade_index,
            body={
                "query": {"bool": {"filter": [{"term": {"trade_date": report_date}}]}},
                "size": 0,
                "aggs": {
                    "buy_count": {"filter": {"term": {"buy_sell": "BUY"}}},
                    "sell_count": {"filter": {"term": {"buy_sell": "SELL"}}},
                    "total_commission": {"sum": {"field": "ib_commission"}},
                    "total_realized_pnl": {"sum": {"field": "fifo_pnl_realized"}},
                    "total_proceeds": {"sum": {"field": "proceeds"}},
                    "symbols_count": {"cardinality": {"field": "symbol"}},
                },
                "track_total_hits": True,
            },
        )
        hits = response.get("hits", {})
        aggs = response.get("aggregations", {})
        trade_count = hits.get("total", {}).get("value", 0)

        return {
            "trade_count": trade_count,
            "buy_count": aggs.get("buy_count", {}).get("doc_count", 0),
            "sell_count": aggs.get("sell_count", {}).get("doc_count", 0),
            "total_commission": round(float(aggs.get("total_commission", {}).get("value") or 0.0), 4),
            "total_realized_pnl": round(float(aggs.get("total_realized_pnl", {}).get("value") or 0.0), 4),
            "total_proceeds": round(float(aggs.get("total_proceeds", {}).get("value") or 0.0), 4),
            "symbols_count": int(aggs.get("symbols_count", {}).get("value") or 0),
        }

    def _fetch_cash_flows_today(self, report_date: str) -> dict:
        start = f"{report_date}T00:00:00"
        end = f"{report_date}T23:59:59"

        response = self.es_client.search(
            index=self.settings.es_cash_flow_index,
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {
                                "bool": {
                                    "should": [
                                        {"term": {"report_date": report_date}},
                                        {
                                            "bool": {
                                                "filter": [
                                                    {"range": {"date_time": {"gte": start, "lte": end}}}
                                                ]
                                            }
                                        }
                                    ],
                                    "minimum_should_match": 1,
                                }
                            }
                        ]
                    }
                },
                "sort": [{"date_time": {"order": "desc"}}],
                "size": self.CASH_FLOWS_LIMIT,
                "_source": [
                    "date_time", "report_date", "currency", "symbol",
                    "description", "amount", "amount_in_base",
                    "flow_direction", "flow_type", "dividend_type",
                    "transaction_id", "settle_date",
                ],
                "track_total_hits": True,
            },
        )
        hits = response.get("hits", {})
        total = hits.get("total", {}).get("value", 0)
        items = [hit["_source"] for hit in hits.get("hits", [])]

        truncated = total > self.CASH_FLOWS_LIMIT
        included_count = min(total, self.CASH_FLOWS_LIMIT)

        return {
            "items": items,
            "truncated": truncated,
            "total_count": total,
            "included_count": included_count,
        }

    def _fetch_cash_flow_summary(self, report_date: str) -> dict:
        start = f"{report_date}T00:00:00"
        end = f"{report_date}T23:59:59"

        response = self.es_client.search(
            index=self.settings.es_cash_flow_index,
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {
                                "bool": {
                                    "should": [
                                        {"term": {"report_date": report_date}},
                                        {
                                            "bool": {
                                                "filter": [
                                                    {"range": {"date_time": {"gte": start, "lte": end}}}
                                                ]
                                            }
                                        }
                                    ],
                                    "minimum_should_match": 1,
                                }
                            }
                        ]
                    }
                },
                "size": 0,
                "aggs": {
                    "by_currency": {
                        "terms": {"field": "currency", "size": 20},
                        "aggs": {
                            "by_flow_type": {
                                "terms": {"field": "flow_type", "size": 20},
                                "aggs": {
                                    "total_amount": {"sum": {"field": "amount"}},
                                }
                            },
                            "deposit_total": {
                                "filter": {"term": {"flow_direction": "deposit"}},
                                "aggs": {"amount": {"sum": {"field": "amount"}}}
                            },
                            "withdrawal_total": {
                                "filter": {"term": {"flow_direction": "withdrawal"}},
                                "aggs": {"amount": {"sum": {"field": "amount"}}}
                            },
                        }
                    },
                    "total_amount": {"sum": {"field": "amount"}},
                },
                "track_total_hits": True,
            },
        )
        hits = response.get("hits", {})
        aggs = response.get("aggregations", {})
        record_count = hits.get("total", {}).get("value", 0)

        by_currency: dict[str, dict] = {}
        raw_flow_type_summary: dict[str, float] = {}

        for curr_bucket in aggs.get("by_currency", {}).get("buckets", []):
            currency = str(curr_bucket.get("key", "USD"))
            if currency not in by_currency:
                by_currency[currency] = {
                    "deposit": 0.0,
                    "withdrawal": 0.0,
                    "dividend": 0.0,
                    "withholding_tax": 0.0,
                    "interest": 0.0,
                    "fee": 0.0,
                    "other": 0.0,
                }

            deposit_total = float(curr_bucket.get("deposit_total", {}).get("amount", {}).get("value") or 0.0)
            withdrawal_total = float(curr_bucket.get("withdrawal_total", {}).get("amount", {}).get("value") or 0.0)

            by_currency[currency]["deposit"] = round(deposit_total, 4)
            by_currency[currency]["withdrawal"] = round(withdrawal_total, 4)

            for ft_bucket in curr_bucket.get("by_flow_type", {}).get("buckets", []):
                flow_type = str(ft_bucket.get("key", ""))
                amount = float(ft_bucket.get("total_amount", {}).get("value") or 0.0)

                raw_flow_type_summary[flow_type] = round(raw_flow_type_summary.get(flow_type, 0.0) + amount, 4)

                ft_lower = flow_type.lower()
                if "dividend" in ft_lower or "payment in lieu" in ft_lower:
                    by_currency[currency]["dividend"] = round(by_currency[currency]["dividend"] + amount, 4)
                elif "withhold" in ft_lower or "tax" in ft_lower:
                    by_currency[currency]["withholding_tax"] = round(by_currency[currency]["withholding_tax"] + amount, 4)
                elif "interest" in ft_lower:
                    by_currency[currency]["interest"] = round(by_currency[currency]["interest"] + amount, 4)
                elif "fee" in ft_lower or "commission" in ft_lower:
                    by_currency[currency]["fee"] = round(by_currency[currency]["fee"] + amount, 4)
                else:
                    by_currency[currency]["other"] = round(by_currency[currency]["other"] + amount, 4)

        total_deposit = round(sum(b.get("deposit", 0.0) for b in by_currency.values()), 4)
        total_withdrawal = round(sum(b.get("withdrawal", 0.0) for b in by_currency.values()), 4)
        total_dividend = round(sum(b.get("dividend", 0.0) for b in by_currency.values()), 4)
        total_withholding_tax = round(sum(b.get("withholding_tax", 0.0) for b in by_currency.values()), 4)
        total_interest = round(sum(b.get("interest", 0.0) for b in by_currency.values()), 4)
        total_fee = round(sum(b.get("fee", 0.0) for b in by_currency.values()), 4)

        mixed_currency = len(by_currency) > 1

        return {
            "record_count": record_count,
            "total_deposit": total_deposit,
            "total_withdrawal": total_withdrawal,
            "total_dividend": total_dividend,
            "total_withholding_tax": total_withholding_tax,
            "total_interest": total_interest,
            "total_fee": total_fee,
            "by_currency": by_currency,
            "raw_flow_type_summary": raw_flow_type_summary,
            "mixed_currency": mixed_currency,
        }