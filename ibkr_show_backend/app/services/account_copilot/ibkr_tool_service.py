from __future__ import annotations

from typing import Any

from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings
from app.services.account_service import AccountService
from app.services.chart_service import ChartService
from app.services.daily_position_review_service import DailyPositionReviewService
from app.services.risk_assessment_account_facts import CASH_EQUIVALENT_SYMBOLS, RiskAssessmentAccountFactsBuilder
from app.services.trade_decision_metrics import to_float
from app.services.trade_review_evidence import build_stable_trade_id, normalize_ibkr_symbol

DATA_SOURCE = "IBKR_ES"


def _symbol_variants(symbol: str) -> list[str]:
    base = normalize_ibkr_symbol(symbol)
    return list(dict.fromkeys([base, f"{base}.US", f"US.{base}"]))


def _normalized_symbol(symbol: str | None) -> str:
    if not symbol:
        return ""
    base = normalize_ibkr_symbol(str(symbol))
    return f"{base}.US" if base and "." not in base else base


def _is_cash_equivalent(symbol: str | None) -> bool:
    return normalize_ibkr_symbol(str(symbol or "")).upper() in CASH_EQUIVALENT_SYMBOLS


def _safe_model_dump(value: Any) -> dict:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return dict(value) if isinstance(value, dict) else {}


class AccountCopilotIBKRToolService:
    def __init__(
        self,
        es_client: ElasticsearchClient,
        settings: Settings,
        account_service: AccountService,
        chart_service: ChartService,
        daily_position_review_service: DailyPositionReviewService,
        risk_assessment_account_facts_builder: RiskAssessmentAccountFactsBuilder,
    ) -> None:
        self.es_client = es_client
        self.settings = settings
        self.account_service = account_service
        self.chart_service = chart_service
        self.daily_position_review_service = daily_position_review_service
        self.risk_assessment_account_facts_builder = risk_assessment_account_facts_builder

    def get_account_overview(self) -> dict:
        return self._call("ibkr_get_account_overview", {}, self._get_account_overview)

    def get_current_positions(self, limit: int = 50, include_cash_equivalents: bool = True) -> dict:
        arguments = {
            "limit": self._clamp_int(limit, 50, 1, 200),
            "include_cash_equivalents": bool(include_cash_equivalents),
        }
        return self._call("ibkr_get_current_positions", arguments, self._get_current_positions)

    def get_symbol_position(self, symbol: str) -> dict:
        arguments = {"symbol": symbol}
        return self._call("ibkr_get_symbol_position", arguments, self._get_symbol_position)

    def get_symbol_trades(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
    ) -> dict:
        arguments = {
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "limit": self._clamp_int(limit, 100, 1, 500),
        }
        return self._call("ibkr_get_symbol_trades", arguments, self._get_symbol_trades)

    def get_position_history(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 365,
    ) -> dict:
        arguments = {
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "limit": self._clamp_int(limit, 365, 1, 2000),
        }
        return self._call("ibkr_get_position_history", arguments, self._get_position_history)

    def get_equity_curve(self, start_date: str | None = None, end_date: str | None = None) -> dict:
        arguments = {"start_date": start_date, "end_date": end_date}
        return self._call("ibkr_get_equity_curve", arguments, self._get_equity_curve)

    def get_daily_attribution(self, report_date: str | None = None) -> dict:
        arguments = {"report_date": report_date}
        return self._call("ibkr_get_daily_attribution", arguments, self._get_daily_attribution)

    def get_risk_snapshot(self) -> dict:
        return self._call("ibkr_get_risk_snapshot", {}, self._get_risk_snapshot)

    def get_cash_flow_summary(self, start_date: str | None = None, end_date: str | None = None) -> dict:
        arguments = {"start_date": start_date, "end_date": end_date}
        return self._call("ibkr_get_cash_flow_summary", arguments, self._get_cash_flow_summary)

    def _call(self, tool: str, arguments: dict, handler) -> dict:
        try:
            return self._envelope(tool=tool, arguments=arguments, data=handler(arguments))
        except ESIndexNotFoundError as exc:
            return self._error(tool, arguments, "INDEX_NOT_FOUND", str(exc), ["IBKR ES index is missing."])
        except ValueError as exc:
            return self._error(tool, arguments, "INVALID_ARGUMENT", str(exc), [str(exc)])
        except Exception as exc:
            return self._error(tool, arguments, "TOOL_ERROR", str(exc), ["IBKR account tool execution failed."])

    def _get_account_overview(self, arguments: dict) -> dict:
        overview = self.account_service.get_overview()
        if overview is None:
            return {}
        data = _safe_model_dump(overview)
        deltas = {
            "total_equity": data.pop("total_equity_delta", None),
            "fifo_total_realized_pnl": data.pop("fifo_total_realized_pnl_delta", None),
            "fifo_total_unrealized_pnl": data.pop("fifo_total_unrealized_pnl_delta", None),
            "fifo_total_pnl": data.pop("fifo_total_pnl_delta", None),
        }
        allowed = [
            "report_date", "currency", "total_equity", "cash", "stock_value",
            "options_value", "funds_value", "crypto_value", "fifo_total_realized_pnl",
            "fifo_total_unrealized_pnl", "fifo_total_pnl", "ytd_twr",
            "interest_accruals", "dividend_accruals", "margin_financing_charge_accruals",
        ]
        return {**{key: data.get(key) for key in allowed}, "deltas": deltas}

    def _get_current_positions(self, arguments: dict) -> dict:
        latest = self._latest_position_report_date()
        if latest is None:
            return {"report_date": None, "items": []}
        response = self.es_client.search(
            index=self.settings.es_position_index,
            body={
                "query": {"bool": {"filter": [{"term": {"report_date": latest}}]}},
                "sort": [{"position_value": {"order": "desc", "missing": "_last"}}],
                "size": arguments["limit"],
                "_source": self._position_source_fields(),
            },
        )
        items = []
        for hit in response.get("hits", {}).get("hits", []):
            item = self._normalize_position(hit.get("_source", {}))
            if not arguments["include_cash_equivalents"] and _is_cash_equivalent(item.get("symbol")):
                continue
            items.append(item)
        return {"report_date": latest, "items": items}

    def _get_symbol_position(self, arguments: dict) -> dict:
        symbol = self._require_symbol(arguments.get("symbol"))
        latest = self._latest_position_report_date()
        if latest is None:
            return {"symbol": symbol, "normalized_symbol": _normalized_symbol(symbol), "is_holding": False, "position": None, "report_date": None}
        response = self.es_client.search(
            index=self.settings.es_position_index,
            body={
                "query": {"bool": {"filter": [{"term": {"report_date": latest}}, {"terms": {"symbol": _symbol_variants(symbol)}}]}},
                "sort": [{"position_value": {"order": "desc", "missing": "_last"}}],
                "size": 1,
                "_source": self._position_source_fields(),
            },
        )
        hits = response.get("hits", {}).get("hits", [])
        position = self._normalize_position(hits[0].get("_source", {})) if hits else None
        is_holding = bool(position and abs(to_float(position.get("quantity")) or 0.0) > 0)
        return {
            "symbol": symbol,
            "normalized_symbol": _normalized_symbol(symbol),
            "is_holding": is_holding,
            "position": position,
            "report_date": latest,
        }

    def _get_symbol_trades(self, arguments: dict) -> dict:
        symbol = self._require_symbol(arguments.get("symbol"))
        filters = [{"terms": {"symbol": _symbol_variants(symbol)}}]
        date_range = self._date_range_filter("trade_date", arguments.get("start_date"), arguments.get("end_date"))
        if date_range:
            filters.append(date_range)
        response = self.es_client.search(
            index=self.settings.es_trade_index,
            body={
                "query": {"bool": {"filter": filters}},
                "sort": [{"trade_date": {"order": "asc", "missing": "_last"}}, {"date_time": {"order": "asc", "missing": "_last"}}],
                "size": arguments["limit"],
                "_source": [
                    "trade_id", "transaction_id", "trade_date", "date_time", "buy_sell", "quantity",
                    "trade_price", "proceeds", "ib_commission", "currency", "fifo_pnl_realized", "symbol",
                ],
                "track_total_hits": True,
            },
        )
        items = [self._normalize_trade(hit.get("_source", {}), hit.get("_id")) for hit in response.get("hits", {}).get("hits", [])]
        return {"symbol": symbol, "items": items, "summary": self._trade_summary(items)}

    def _get_position_history(self, arguments: dict) -> dict:
        symbol = self._require_symbol(arguments.get("symbol"))
        filters = [{"terms": {"symbol": _symbol_variants(symbol)}}]
        date_range = self._date_range_filter("report_date", arguments.get("start_date"), arguments.get("end_date"))
        if date_range:
            filters.append(date_range)
        response = self.es_client.search(
            index=self.settings.es_position_index,
            body={
                "query": {"bool": {"filter": filters}},
                "sort": [{"report_date": {"order": "asc", "missing": "_last"}}],
                "size": arguments["limit"],
                "_source": self._position_source_fields(),
            },
        )
        items = [self._position_history_item(hit.get("_source", {})) for hit in response.get("hits", {}).get("hits", [])]
        return {"symbol": symbol, "items": items, "summary": self._position_history_summary(items)}

    def _get_equity_curve(self, arguments: dict) -> dict:
        response = self.chart_service.get_equity_curve(arguments.get("start_date"), arguments.get("end_date"))
        items = [_safe_model_dump(item) for item in response.items]
        return {"items": items, "summary": self._equity_curve_summary(items)}

    def _get_daily_attribution(self, arguments: dict) -> dict:
        context = self.daily_position_review_service.build_review_context(
            arguments.get("report_date"),
            include_public_context=False,
            include_benchmarks=False,
        )
        return {
            "report_date": context.get("report_date"),
            "overview": context.get("overview") or {},
            "rankings": context.get("rankings") or {},
            "risk": context.get("risk") or {},
            "attribution_quality": context.get("attribution_quality") or {},
            "positions": context.get("positions") or [],
        }

    def _get_risk_snapshot(self, arguments: dict) -> dict:
        data = self.risk_assessment_account_facts_builder.build().to_dict()
        return {
            key: data.get(key)
            for key in [
                "net_liquidation", "cash", "deployable_liquidity", "position_count",
                "largest_position_pct", "top_3_position_pct", "top_5_position_pct",
                "cash_pct", "margin_usage_pct", "unrealized_pnl", "unrealized_pnl_pct",
                "top_positions", "positions",
            ]
        }

    def _get_cash_flow_summary(self, arguments: dict) -> dict:
        filters = []
        date_range = self._date_range_filter("date_time", arguments.get("start_date"), arguments.get("end_date"))
        if date_range:
            filters.append(date_range)
        response = self.es_client.search(
            index=self.settings.es_cash_flow_index,
            body={
                "query": {"bool": {"filter": filters or [{"match_all": {}}]}},
                "sort": [{"date_time": {"order": "desc", "missing": "_last"}}],
                "size": 20,
                "_source": [
                    "currency", "symbol", "description", "date_time", "settle_date", "amount",
                    "amount_in_base", "flow_direction", "flow_type", "dividend_type", "report_date",
                ],
                "aggs": {
                    "deposit_total": {
                        "filter": {"term": {"flow_direction": "deposit"}},
                        "aggs": {"amount": {"sum": {"field": "amount"}}},
                    },
                    "withdrawal_total": {
                        "filter": {"term": {"flow_direction": "withdrawal"}},
                        "aggs": {"amount": {"sum": {"field": "amount"}}},
                    },
                    "by_flow_type": {
                        "terms": {"field": "flow_type", "size": 50},
                        "aggs": {"total_amount": {"sum": {"field": "amount"}}},
                    },
                },
                "track_total_hits": True,
            },
        )
        items = [self._sanitize_cash_flow(hit.get("_source", {})) for hit in response.get("hits", {}).get("hits", [])]
        return {
            "start_date": arguments.get("start_date"),
            "end_date": arguments.get("end_date"),
            "summary": self._cash_flow_summary(response.get("aggregations", {}), items),
            "items_sample": items[:20],
        }

    def _envelope(self, *, tool: str, arguments: dict, data: dict, data_limitations: list[str] | None = None) -> dict:
        return {
            "ok": True,
            "tool": tool,
            "arguments": arguments,
            "data": data,
            "data_source": DATA_SOURCE,
            "data_limitations": data_limitations or [],
            "metadata": {"read_only": True},
        }

    def _error(self, tool: str, arguments: dict, error_code: str, message: str, data_limitations: list[str]) -> dict:
        return {
            "ok": False,
            "tool": tool,
            "arguments": arguments,
            "data": {},
            "data_source": DATA_SOURCE,
            "data_limitations": data_limitations,
            "metadata": {"read_only": True, "error_code": error_code, "message": message},
        }

    def _latest_position_report_date(self) -> str | None:
        response = self.es_client.search(
            index=self.settings.es_position_index,
            body={"size": 1, "sort": [{"report_date": {"order": "desc"}}], "_source": ["report_date"]},
        )
        hits = response.get("hits", {}).get("hits", [])
        return hits[0].get("_source", {}).get("report_date") if hits else None

    def _position_source_fields(self) -> list[str]:
        return [
            "report_date", "symbol", "description", "asset_class", "quantity", "mark_price",
            "position_value", "percent_of_nav", "average_cost_price", "cost_basis_money",
            "total_realized_pnl", "total_unrealized_pnl", "unrealized_pnl_percent",
        ]

    def _normalize_position(self, source: dict) -> dict:
        symbol = source.get("symbol")
        return {
            "symbol": symbol,
            "normalized_symbol": _normalized_symbol(symbol),
            "quantity": to_float(source.get("quantity")),
            "mark_price": to_float(source.get("mark_price")),
            "position_value": to_float(source.get("position_value")),
            "percent_of_nav": to_float(source.get("percent_of_nav")),
            "average_cost_price": to_float(source.get("average_cost_price")),
            "cost_basis_money": to_float(source.get("cost_basis_money")),
            "total_unrealized_pnl": to_float(source.get("total_unrealized_pnl")),
            "unrealized_pnl_percent": to_float(source.get("unrealized_pnl_percent")),
            "total_realized_pnl": to_float(source.get("total_realized_pnl")),
            "asset_class": source.get("asset_class"),
            "description": source.get("description"),
        }

    def _position_history_item(self, source: dict) -> dict:
        item = self._normalize_position(source)
        return {
            "report_date": source.get("report_date"),
            "quantity": item.get("quantity"),
            "mark_price": item.get("mark_price"),
            "position_value": item.get("position_value"),
            "percent_of_nav": item.get("percent_of_nav"),
            "average_cost_price": item.get("average_cost_price"),
            "cost_basis_money": item.get("cost_basis_money"),
            "total_unrealized_pnl": item.get("total_unrealized_pnl"),
            "unrealized_pnl_percent": item.get("unrealized_pnl_percent"),
        }

    def _normalize_trade(self, source: dict, hit_id: str | None) -> dict:
        source = {**source, "_id": hit_id}
        return {
            "trade_id": build_stable_trade_id(source),
            "trade_date": source.get("trade_date"),
            "date_time": source.get("date_time"),
            "side": source.get("buy_sell"),
            "quantity": to_float(source.get("quantity")),
            "trade_price": to_float(source.get("trade_price")),
            "proceeds": to_float(source.get("proceeds")),
            "ib_commission": to_float(source.get("ib_commission")),
            "currency": source.get("currency"),
            "fifo_pnl_realized": to_float(source.get("fifo_pnl_realized")),
        }

    def _trade_summary(self, items: list[dict]) -> dict:
        return {
            "trade_count": len(items),
            "buy_count": sum(1 for item in items if str(item.get("side") or "").upper() == "BUY"),
            "sell_count": sum(1 for item in items if str(item.get("side") or "").upper() == "SELL"),
            "total_commission": round(sum(to_float(item.get("ib_commission")) or 0.0 for item in items), 4),
            "total_realized_pnl": round(sum(to_float(item.get("fifo_pnl_realized")) or 0.0 for item in items), 4),
        }

    def _position_history_summary(self, items: list[dict]) -> dict:
        if not items:
            return {"first_report_date": None, "last_report_date": None, "max_position_value": 0.0, "max_weight": 0.0, "latest_weight": None}
        values = [abs(to_float(item.get("position_value")) or 0.0) for item in items]
        weights = [abs(to_float(item.get("percent_of_nav")) or 0.0) for item in items]
        return {
            "first_report_date": items[0].get("report_date"),
            "last_report_date": items[-1].get("report_date"),
            "max_position_value": max(values) if values else 0.0,
            "max_weight": max(weights) if weights else 0.0,
            "latest_weight": items[-1].get("percent_of_nav"),
        }

    def _equity_curve_summary(self, items: list[dict]) -> dict:
        if not items:
            return {"start_date": None, "end_date": None, "start_equity": None, "end_equity": None, "total_pnl": None, "max_drawdown": None, "point_count": 0}
        equities = [to_float(item.get("total_equity")) for item in items]
        equities = [item for item in equities if item is not None]
        return {
            "start_date": items[0].get("report_date"),
            "end_date": items[-1].get("report_date"),
            "start_equity": items[0].get("total_equity"),
            "end_equity": items[-1].get("total_equity"),
            "total_pnl": items[-1].get("total_pnl"),
            "max_drawdown": self._max_drawdown(equities),
            "point_count": len(items),
        }

    def _cash_flow_summary(self, aggregations: dict, items: list[dict]) -> dict:
        if aggregations:
            return self._cash_flow_summary_from_aggs(aggregations)
        return self._cash_flow_summary_from_items(items)

    def _cash_flow_summary_from_aggs(self, aggregations: dict) -> dict:
        summary = self._empty_cash_flow_summary()
        summary["total_deposits"] = float(aggregations.get("deposit_total", {}).get("amount", {}).get("value") or 0.0)
        summary["total_withdrawals"] = float(aggregations.get("withdrawal_total", {}).get("amount", {}).get("value") or 0.0)
        for bucket in aggregations.get("by_flow_type", {}).get("buckets", []):
            amount = float(bucket.get("total_amount", {}).get("value") or 0.0)
            flow_type = str(bucket.get("key") or "").lower()
            self._add_cash_flow_type_amount(summary, flow_type, amount)
        summary["net_deposit_withdrawal"] = summary["total_deposits"] + summary["total_withdrawals"]
        return {key: round(value, 4) for key, value in summary.items()}

    def _cash_flow_summary_from_items(self, items: list[dict]) -> dict:
        summary = self._empty_cash_flow_summary()
        for item in items:
            amount = to_float(item.get("amount")) or 0.0
            flow_type = str(item.get("flow_type") or "").lower()
            direction = str(item.get("flow_direction") or "").lower()
            if "deposits/withdrawals" in flow_type or direction in {"deposit", "withdrawal"}:
                if direction == "withdrawal" or amount < 0:
                    summary["total_withdrawals"] += amount
                else:
                    summary["total_deposits"] += amount
            else:
                self._add_cash_flow_type_amount(summary, flow_type, amount)
        summary["net_deposit_withdrawal"] = summary["total_deposits"] + summary["total_withdrawals"]
        return {key: round(value, 4) for key, value in summary.items()}

    def _empty_cash_flow_summary(self) -> dict[str, float]:
        summary = {
            "total_deposits": 0.0,
            "total_withdrawals": 0.0,
            "net_deposit_withdrawal": 0.0,
            "total_dividends": 0.0,
            "total_interest": 0.0,
            "total_commissions": 0.0,
            "total_fees": 0.0,
            "total_other": 0.0,
        }
        return summary

    def _add_cash_flow_type_amount(self, summary: dict, flow_type: str, amount: float) -> None:
        if "dividend" in flow_type or "payment in lieu" in flow_type:
            summary["total_dividends"] += amount
        elif "interest" in flow_type:
            summary["total_interest"] += amount
        elif "commission" in flow_type:
            summary["total_commissions"] += amount
        elif "fee" in flow_type or "tax" in flow_type or "withhold" in flow_type:
            summary["total_fees"] += amount
        elif "deposits/withdrawals" not in flow_type:
            summary["total_other"] += amount

    def _sanitize_cash_flow(self, source: dict) -> dict:
        return {
            "date_time": source.get("date_time"),
            "report_date": source.get("report_date"),
            "currency": source.get("currency"),
            "symbol": source.get("symbol"),
            "description": source.get("description"),
            "amount": to_float(source.get("amount")),
            "amount_in_base": to_float(source.get("amount_in_base")),
            "flow_direction": source.get("flow_direction"),
            "flow_type": source.get("flow_type"),
            "dividend_type": source.get("dividend_type"),
            "settle_date": source.get("settle_date"),
        }

    def _date_range_filter(self, field: str, start: str | None, end: str | None) -> dict | None:
        range_filter = {}
        if start:
            range_filter["gte"] = start
        if end:
            range_filter["lte"] = end
        return {"range": {field: range_filter}} if range_filter else None

    def _require_symbol(self, symbol: str | None) -> str:
        if not symbol or not str(symbol).strip():
            raise ValueError("symbol is required")
        return str(symbol).strip().upper()

    def _clamp_int(self, value: int | None, default: int, minimum: int, maximum: int) -> int:
        try:
            number = int(value if value is not None else default)
        except (TypeError, ValueError):
            number = default
        return max(minimum, min(maximum, number))

    def _max_drawdown(self, equities: list[float]) -> float | None:
        if not equities:
            return None
        peak = equities[0]
        max_dd = 0.0
        for equity in equities:
            peak = max(peak, equity)
            if peak:
                max_dd = min(max_dd, (equity - peak) / peak)
        return round(max_dd, 6)
