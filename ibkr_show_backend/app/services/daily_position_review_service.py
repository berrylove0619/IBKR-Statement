from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
import threading
from typing import Any

from app.clients.es_client import ElasticsearchClient
from app.core.config import Settings
from app.services.longbridge_service import LongbridgeExternalDataClient, LongbridgeExternalDataError, LongbridgeUnavailableError, normalize_longbridge_symbol
from app.utils.dates import parse_date

DEFAULT_REVIEW_BENCHMARKS = ["SPY.US", "QQQ.US", "DIA.US", "SMH.US"]
DEFAULT_FOCUS_LIMIT = 6


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def round_number(value: float | None, digits: int = 4) -> float | None:
    return round(float(value), digits) if value is not None else None


def nav_percent_to_ratio(value: Any) -> float | None:
    number = to_float(value)
    if number is None:
        return None
    return round_number(number / 100.0, 6)


def _empty_benchmarks(report_date: str) -> dict:
    return {
        "start": report_date,
        "end": report_date,
        "items": [],
        "best_benchmark": None,
        "beta_alpha_note": "未请求公开市场基准数据（首屏轻量上下文）。",
    }


class DailyPositionReviewService:
    def __init__(
        self,
        es_client: ElasticsearchClient,
        settings: Settings,
        longbridge_client: LongbridgeExternalDataClient,
    ) -> None:
        self.es_client = es_client
        self.settings = settings
        self.longbridge_client = longbridge_client
        self._data_quality_lock = threading.Lock()

    def list_report_dates(self, limit: int = 60) -> list[str]:
        response = self.es_client.search(
            index=self.settings.es_account_index,
            body={
                "size": max(1, min(limit, 500)),
                "sort": [{"report_date": {"order": "desc"}}],
                "_source": ["report_date"],
            },
        )
        return [str(hit.get("_source", {}).get("report_date")) for hit in response.get("hits", {}).get("hits", []) if hit.get("_source", {}).get("report_date")]

    def build_review_context(
        self,
        report_date: str | None = None,
        *,
        include_public_context: bool = False,
        include_benchmarks: bool = False,
    ) -> dict:
        effective_date = report_date or self._latest_report_date()
        if not effective_date:
            raise ValueError("No IBKR account report date is available")

        data_quality: dict[str, list[str]] = {"missing_fields": [], "warnings": []}
        account = self._fetch_account_snapshot(effective_date)
        if account is None:
            raise ValueError(f"IBKR account snapshot not found for {effective_date}")
        previous_account = self._fetch_previous_account_snapshot(effective_date)
        positions = self._fetch_positions(effective_date)
        if not positions:
            data_quality["warnings"].append("No IBKR position snapshots found for report date")

        position_items = self._build_position_contributions(positions, account, data_quality)
        rankings = self._build_rankings(position_items)
        overview = self._build_overview(account, previous_account, position_items, rankings, data_quality)
        risk = self._build_risk_analysis(account, position_items)
        focus_symbols = self._select_focus_symbols(position_items)
        start = self._market_start_date(effective_date)

        public_context: dict[str, dict] = {}
        if include_public_context:
            def fetch_contexts() -> dict[str, dict]:
                if not focus_symbols:
                    return {}
                with ThreadPoolExecutor(max_workers=len(focus_symbols)) as executor:
                    futures = {
                        executor.submit(self._build_symbol_public_context, symbol, effective_date, data_quality): symbol
                        for symbol in focus_symbols
                    }
                    result = {}
                    for future in as_completed(futures):
                        symbol = futures[future]
                        try:
                            result[symbol] = future.result()
                        except Exception as exc:
                            with self._data_quality_lock:
                                data_quality["warnings"].append(f"Symbol context {symbol} failed: {exc}")
                            result[symbol] = {}
                    return result

            def fetch_benchmarks_fn() -> dict:
                return self._build_benchmark_context(start, effective_date, overview.get("daily_return_percent"), data_quality)

            if include_benchmarks:
                public_context, benchmarks = self._run_parallel(
                    fetch_contexts,
                    fetch_benchmarks_fn,
                )
            else:
                public_context = fetch_contexts()
                benchmarks = _empty_benchmarks(effective_date)
        else:
            benchmarks = self._build_benchmark_context(start, effective_date, overview.get("daily_return_percent"), data_quality) if include_benchmarks else _empty_benchmarks(effective_date)

        unexplained_pnl = self._calculate_unexplained_pnl(overview.get("daily_pnl"), position_items)

        return {
            "report_date": effective_date,
            "data_sources": {
                "account_data": "IBKR_ONLY",
                "position_data": "IBKR_ONLY",
                "trade_data": "IBKR_ONLY",
                "public_market_data": "LONGBRIDGE_PUBLIC_ONLY",
            },
            "overview": overview,
            "positions": position_items,
            "rankings": rankings,
            "risk": risk,
            "benchmarks": benchmarks,
            "focus_symbols": focus_symbols,
            "symbol_public_context": public_context,
            "attribution_quality": {
                "explained_position_daily_pnl": round_number(sum(item.get("daily_pnl") or 0.0 for item in position_items), 2),
                "account_daily_pnl": overview.get("daily_pnl"),
                "unexplained_pnl": unexplained_pnl,
                "note": "差额可能来自现金、分红、利息、手续费、FX、盘中交易或非股票资产。",
            },
            "data_quality": data_quality,
        }

    def get_overview(self, report_date: str) -> dict:
        context = self.build_review_context(report_date)
        return context["overview"]

    def get_positions(self, report_date: str) -> list[dict]:
        context = self.build_review_context(report_date)
        return context["positions"]

    def get_rankings(self, report_date: str) -> dict:
        context = self.build_review_context(report_date)
        return context["rankings"]

    def get_risk(self, report_date: str) -> dict:
        context = self.build_review_context(report_date)
        return context["risk"]

    def _latest_report_date(self) -> str | None:
        dates = self.list_report_dates(limit=1)
        return dates[0] if dates else None

    def _fetch_account_snapshot(self, report_date: str) -> dict | None:
        response = self.es_client.search(
            index=self.settings.es_account_index,
            body={
                "query": {"bool": {"filter": [{"term": {"report_date": report_date}}]}},
                "size": 1,
                "_source": [
                    "account_id",
                    "report_date",
                    "currency",
                    "total_equity",
                    "cash",
                    "stock_value",
                    "options_value",
                    "funds_value",
                    "crypto_value",
                    "cnav_mtm",
                    "cnav_twr",
                    "cnav_realized",
                    "cnav_change_in_unrealized",
                    "cnav_dividends",
                    "cnav_interest",
                    "cnav_commissions",
                    "cnav_broker_fees",
                    "cnav_net_fx_trading",
                ],
            },
        )
        hits = response.get("hits", {}).get("hits", [])
        return hits[0].get("_source", {}) if hits else None

    def _fetch_previous_account_snapshot(self, report_date: str) -> dict | None:
        response = self.es_client.search(
            index=self.settings.es_account_index,
            body={
                "query": {"bool": {"filter": [{"range": {"report_date": {"lt": report_date}}}]}},
                "sort": [{"report_date": {"order": "desc"}}],
                "size": 1,
                "_source": ["report_date", "total_equity", "cash"],
            },
        )
        hits = response.get("hits", {}).get("hits", [])
        return hits[0].get("_source", {}) if hits else None

    def _fetch_positions(self, report_date: str) -> list[dict]:
        response = self.es_client.search(
            index=self.settings.es_position_index,
            body={
                "query": {"bool": {"filter": [{"term": {"report_date": report_date}}]}},
                "sort": [{"position_value": {"order": "desc", "missing": "_last"}}],
                "size": 1000,
                "_source": [
                    "account_id",
                    "report_date",
                    "symbol",
                    "description",
                    "asset_class",
                    "sub_category",
                    "quantity",
                    "mark_price",
                    "position_value",
                    "percent_of_nav",
                    "average_cost_price",
                    "cost_basis_money",
                    "total_unrealized_pnl",
                    "unrealized_pnl_percent",
                    "total_realized_pnl",
                    "previous_day_change_percent",
                ],
            },
        )
        return [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]

    def _build_position_contributions(self, positions: list[dict], account: dict, data_quality: dict) -> list[dict]:
        daily_pnl = to_float(account.get("cnav_mtm"))
        total_equity = to_float(account.get("total_equity"))
        items = []
        for position in positions:
            symbol = str(position.get("symbol") or "").strip().upper()
            if not symbol:
                data_quality["warnings"].append("Position row without symbol skipped")
                continue
            quantity = to_float(position.get("quantity"))
            mark_price = to_float(position.get("mark_price"))
            position_value = to_float(position.get("position_value"))
            change_percent = to_float(position.get("previous_day_change_percent"))
            position_daily_pnl = self._calculate_position_daily_pnl(quantity, mark_price, position_value, change_percent)
            contribution_ratio = position_daily_pnl / daily_pnl if position_daily_pnl is not None and daily_pnl not in (None, 0.0) else None
            weight = nav_percent_to_ratio(position.get("percent_of_nav"))
            if weight is None and total_equity not in (None, 0.0) and position_value is not None:
                weight = position_value / abs(total_equity)
            item = {
                "symbol": symbol,
                "normalized_symbol": normalize_longbridge_symbol(symbol),
                "name": position.get("description"),
                "asset_class": position.get("asset_class"),
                "sub_category": position.get("sub_category"),
                "quantity": round_number(quantity, 6),
                "mark_price": round_number(mark_price, 4),
                "market_value": round_number(position_value, 2),
                "weight": round_number(weight, 6),
                "daily_change_percent": round_number(change_percent, 4),
                "daily_pnl": round_number(position_daily_pnl, 2),
                "contribution_ratio": round_number(contribution_ratio, 6),
                "average_cost": round_number(to_float(position.get("average_cost_price")), 4),
                "cost_basis": round_number(to_float(position.get("cost_basis_money")), 2),
                "unrealized_pnl": round_number(to_float(position.get("total_unrealized_pnl")), 2),
                "unrealized_pnl_percent": round_number(to_float(position.get("unrealized_pnl_percent")), 4),
                "is_major_contributor": False,
                "is_major_drag": False,
                "data_source": "IBKR",
            }
            items.append(item)

        items.sort(key=lambda item: abs(item.get("daily_pnl") or 0.0), reverse=True)
        contributors = [item["symbol"] for item in sorted(items, key=lambda item: item.get("daily_pnl") or 0.0, reverse=True)[:5] if (item.get("daily_pnl") or 0.0) > 0]
        drags = [item["symbol"] for item in sorted(items, key=lambda item: item.get("daily_pnl") or 0.0)[:5] if (item.get("daily_pnl") or 0.0) < 0]
        for item in items:
            item["is_major_contributor"] = item["symbol"] in contributors
            item["is_major_drag"] = item["symbol"] in drags
        return sorted(items, key=lambda item: item.get("market_value") or 0.0, reverse=True)

    def _calculate_position_daily_pnl(
        self,
        quantity: float | None,
        mark_price: float | None,
        position_value: float | None,
        change_percent: float | None,
    ) -> float | None:
        if change_percent is None:
            return None
        daily_return = change_percent / 100.0
        if daily_return <= -0.999999:
            return None
        if quantity is not None and mark_price is not None:
            previous_price = mark_price / (1.0 + daily_return)
            return quantity * (mark_price - previous_price)
        if position_value is not None:
            previous_value = position_value / (1.0 + daily_return)
            return position_value - previous_value
        return None

    def _build_overview(self, account: dict, previous_account: dict | None, positions: list[dict], rankings: dict, data_quality: dict) -> dict:
        total_equity = to_float(account.get("total_equity"))
        daily_pnl = to_float(account.get("cnav_mtm"))
        daily_pnl_source = "IBKR_CNAV_MTM"
        if daily_pnl is None and previous_account and total_equity is not None and previous_account.get("total_equity") is not None:
            daily_pnl = total_equity - float(previous_account["total_equity"])
            daily_pnl_source = "INFERRED_FROM_EQUITY_DELTA"
            data_quality["warnings"].append("Daily account PnL inferred from total_equity delta because cnav_mtm is missing")
        daily_return = to_float(account.get("cnav_twr"))
        if daily_return is None and daily_pnl is not None and previous_account and previous_account.get("total_equity") not in (None, 0, 0.0):
            daily_return = daily_pnl / abs(float(previous_account["total_equity"])) * 100.0
        cash = to_float(account.get("cash"))
        stock_value = to_float(account.get("stock_value"))
        total_position_value = sum(abs(item.get("market_value") or 0.0) for item in positions)
        top_contributors = rankings["profit_contributors"][:3]
        top_drags = rankings["loss_drags"][:3]
        summary = self._one_line_summary(daily_pnl, daily_return, top_contributors, top_drags)
        return {
            "report_date": account.get("report_date"),
            "currency": account.get("currency"),
            "total_equity": round_number(total_equity, 2),
            "daily_pnl": round_number(daily_pnl, 2),
            "daily_pnl_source": daily_pnl_source,
            "daily_return_percent": round_number(daily_return, 4),
            "total_position_value": round_number(stock_value if stock_value is not None else total_position_value, 2),
            "cash": round_number(cash, 2),
            "cash_ratio": round_number(cash / total_equity if cash is not None and total_equity not in (None, 0.0) else None, 6),
            "position_count": len(positions),
            "top_contributors": top_contributors,
            "top_drags": top_drags,
            "summary": summary,
            "ibkr_pnl_breakdown": {
                "realized": round_number(to_float(account.get("cnav_realized")), 2),
                "change_in_unrealized": round_number(to_float(account.get("cnav_change_in_unrealized")), 2),
                "dividends": round_number(to_float(account.get("cnav_dividends")), 2),
                "interest": round_number(to_float(account.get("cnav_interest")), 2),
                "commissions": round_number(to_float(account.get("cnav_commissions")), 2),
                "broker_fees": round_number(to_float(account.get("cnav_broker_fees")), 2),
                "net_fx_trading": round_number(to_float(account.get("cnav_net_fx_trading")), 2),
            },
        }

    def _one_line_summary(self, daily_pnl: float | None, daily_return: float | None, contributors: list[dict], drags: list[dict]) -> str:
        direction = "上涨" if (daily_pnl or 0.0) > 0 else "下跌" if (daily_pnl or 0.0) < 0 else "持平"
        lead = contributors[0]["symbol"] if contributors else None
        drag = drags[0]["symbol"] if drags else None
        pct = f"{daily_return:.2f}%" if daily_return is not None else "收益率缺失"
        if lead and drag:
            return f"账户今日{direction} {pct}，主要贡献来自 {lead}，主要拖累来自 {drag}。"
        if lead:
            return f"账户今日{direction} {pct}，主要贡献来自 {lead}。"
        if drag:
            return f"账户今日{direction} {pct}，主要拖累来自 {drag}。"
        return f"账户今日{direction} {pct}，暂无可归因的主要持仓。"

    def _build_rankings(self, positions: list[dict]) -> dict:
        return {
            "profit_contributors": [item for item in sorted(positions, key=lambda item: item.get("daily_pnl") or 0.0, reverse=True) if (item.get("daily_pnl") or 0.0) > 0][:10],
            "loss_drags": [item for item in sorted(positions, key=lambda item: item.get("daily_pnl") or 0.0) if (item.get("daily_pnl") or 0.0) < 0][:10],
            "top_gainers": [item for item in sorted(positions, key=lambda item: item.get("daily_change_percent") if item.get("daily_change_percent") is not None else -9999, reverse=True)][:10],
            "top_losers": [item for item in sorted(positions, key=lambda item: item.get("daily_change_percent") if item.get("daily_change_percent") is not None else 9999)][:10],
            "top_weights": [item for item in sorted(positions, key=lambda item: item.get("weight") or 0.0, reverse=True)][:10],
            "top_unrealized_gains": [item for item in sorted(positions, key=lambda item: item.get("unrealized_pnl") or 0.0, reverse=True) if (item.get("unrealized_pnl") or 0.0) > 0][:10],
            "top_unrealized_losses": [item for item in sorted(positions, key=lambda item: item.get("unrealized_pnl") or 0.0) if (item.get("unrealized_pnl") or 0.0) < 0][:10],
        }

    def _build_risk_analysis(self, account: dict, positions: list[dict]) -> dict:
        sorted_by_weight = sorted(positions, key=lambda item: item.get("weight") or 0.0, reverse=True)
        max_position = sorted_by_weight[0] if sorted_by_weight else None
        top3_weight = sum(item.get("weight") or 0.0 for item in sorted_by_weight[:3])
        top5_weight = sum(item.get("weight") or 0.0 for item in sorted_by_weight[:5])
        cash_ratio = None
        cash = to_float(account.get("cash"))
        equity = to_float(account.get("total_equity"))
        if cash is not None and equity not in (None, 0.0):
            cash_ratio = cash / equity
        industry_buckets = self._classify_theme_buckets(positions)
        semiconductor_ai_tech_weight = sum(
            bucket["weight"]
            for bucket in industry_buckets
            if bucket["theme"] in {"半导体", "AI/科技平台"}
        )
        max_down_5_impact = -5.0 * (max_position.get("weight") or 0.0) if max_position else None
        risk_flags = []
        if max_position and (max_position.get("weight") or 0.0) >= 0.25:
            risk_flags.append("单一股票权重超过 25%，存在集中度风险")
        if top3_weight >= 0.55:
            risk_flags.append("前三大持仓权重超过 55%，账户波动主要受少数股票驱动")
        if semiconductor_ai_tech_weight >= 0.5:
            risk_flags.append("半导体/AI/科技主题权重较高，需关注主题回撤")
        if cash_ratio is not None and cash_ratio < 0.05:
            risk_flags.append("现金比例偏低，防守和加仓弹性有限")
        posture = "进攻" if (cash_ratio or 0.0) < 0.15 or top3_weight > 0.45 else "均衡" if (cash_ratio or 0.0) < 0.35 else "防守"
        return {
            "max_position": max_position,
            "max_single_position_weight": round_number(max_position.get("weight"), 6) if max_position else None,
            "top3_weight": round_number(top3_weight, 6),
            "top5_weight": round_number(top5_weight, 6),
            "theme_buckets": industry_buckets,
            "semiconductor_ai_tech_weight": round_number(semiconductor_ai_tech_weight, 6),
            "cash_ratio": round_number(cash_ratio, 6),
            "max_position_down_5pct_account_impact_percent": round_number(max_down_5_impact, 4),
            "risk_flags": risk_flags,
            "account_posture": posture,
        }

    def _classify_theme_buckets(self, positions: list[dict]) -> list[dict]:
        buckets: dict[str, dict] = {}
        for item in positions:
            theme = self._classify_theme(item)
            bucket = buckets.setdefault(theme, {"theme": theme, "weight": 0.0, "market_value": 0.0, "symbols": []})
            bucket["weight"] += item.get("weight") or 0.0
            bucket["market_value"] += abs(item.get("market_value") or 0.0)
            bucket["symbols"].append(item["symbol"])
        return [
            {**bucket, "weight": round_number(bucket["weight"], 6), "market_value": round_number(bucket["market_value"], 2)}
            for bucket in sorted(buckets.values(), key=lambda item: item["weight"], reverse=True)
        ]

    def _classify_theme(self, item: dict) -> str:
        text = f"{item.get('symbol') or ''} {item.get('name') or ''}".upper()
        if any(token in text for token in ("AMD", "NVDA", "ARM", "INTC", "QUALCOMM", "TSM", "AVGO", "SMH", "SEMI")):
            return "半导体"
        if any(token in text for token in ("MSFT", "META", "GOOGL", "GOOGLE", "AMZN", "SOFTWARE", "AI")):
            return "AI/科技平台"
        if any(token in text for token in ("TREASURY", "BOND", "SGOV", "BIL")):
            return "固定收益/现金替代"
        if "TESLA" in text or "TSLA" in text:
            return "新能源车"
        return "其他"

    def _select_focus_symbols(self, positions: list[dict], limit: int = DEFAULT_FOCUS_LIMIT) -> list[str]:
        scored = []
        for item in positions:
            score = 0.0
            score += abs(item.get("daily_pnl") or 0.0) / 100.0
            score += abs(item.get("daily_change_percent") or 0.0) * 2.0
            score += (item.get("weight") or 0.0) * 100.0
            if item.get("is_major_contributor") or item.get("is_major_drag"):
                score += 50.0
            scored.append((score, item["normalized_symbol"]))
        scored.sort(reverse=True)
        return list(dict.fromkeys(symbol for _, symbol in scored[:limit]))

    def _build_benchmark_context(self, start: str, end: str, account_return_percent: float | None, data_quality: dict) -> dict:
        items = []
        with ThreadPoolExecutor(max_workers=len(DEFAULT_REVIEW_BENCHMARKS)) as executor:
            futures = {
                executor.submit(self._fetch_candles, symbol, start, end, data_quality): symbol
                for symbol in DEFAULT_REVIEW_BENCHMARKS
            }
            results = {}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    results[symbol] = future.result()
                except Exception as exc:
                    with self._data_quality_lock:
                        data_quality["warnings"].append(f"Benchmark {symbol} failed: {exc}")
                    results[symbol] = []
        for symbol in DEFAULT_REVIEW_BENCHMARKS:
            candles = results.get(symbol, [])
            return_percent = self._period_return_percent(candles)
            single_day_return = self._single_day_return_percent(candles)
            items.append(
                {
                    "symbol": symbol,
                    "single_day_return_percent": round_number(single_day_return, 4),
                    "period_14d_return_percent": round_number(return_percent, 4),
                    "account_excess_return_percent": round_number(account_return_percent - single_day_return, 4)
                    if account_return_percent is not None and single_day_return is not None
                    else None,
                    "source": "Longbridge public market data",
                }
            )
        best = max((item for item in items if item.get("return_percent") is not None), key=lambda item: item["return_percent"], default=None)
        return {
            "start": start,
            "end": end,
            "items": items,
            "best_benchmark": best,
            "beta_alpha_note": "第一版用当日相对指数表现做粗略 alpha/beta 判断，未做回归归因。",
        }

    def _build_symbol_public_context(self, symbol: str, report_date: str, data_quality: dict) -> dict:
        start = self._market_start_date(report_date, days=90)

        def fetch_all() -> dict:
            results: dict[str, Any] = {}
            errors: list[str] = []

            def safe_call(label: str, fn, *args):
                try:
                    return label, fn(*args)
                except Exception as exc:
                    with self._data_quality_lock:
                        data_quality["warnings"].append(f"Longbridge public {label} unavailable for {symbol}: {exc}")
                    return label, None

            with ThreadPoolExecutor(max_workers=7) as executor:
                futures = [
                    executor.submit(safe_call, "candles", self._fetch_candles, symbol, start, report_date, data_quality),
                    executor.submit(safe_call, "quote snapshot", self.longbridge_client.get_quote_snapshot, symbol),
                    executor.submit(safe_call, "static info", self.longbridge_client.get_static_info, symbol),
                    executor.submit(safe_call, "calc indexes", self.longbridge_client.get_calc_indexes, symbol),
                    executor.submit(safe_call, "news", self.longbridge_client.get_news, symbol, 8),
                    executor.submit(safe_call, "filings", self.longbridge_client.get_filings, symbol, 5),
                    executor.submit(safe_call, "topics", self.longbridge_client.get_topics, symbol, 5),
                ]
                for future in as_completed(futures):
                    label, value = future.result()
                    results[label] = value

            return results

        raw = fetch_all()
        candles = raw.get("candles") or []
        quote = raw.get("quote snapshot")
        static_info = raw.get("static info")
        calc_indexes = raw.get("calc indexes")
        news = self._public_item_list(raw.get("news"))
        filings = self._public_item_list(raw.get("filings"))
        topics = self._public_item_list(raw.get("topics"))

        closes = [item["close"] for item in candles if item.get("close") is not None]
        volumes = [item["volume"] for item in candles if item.get("volume") is not None]
        latest_volume = volumes[-1] if volumes else None
        avg_20_volume = sum(volumes[-20:]) / min(len(volumes), 20) if volumes else None
        return {
            "source": "Longbridge public data",
            "symbol": symbol,
            "quote": self._compact_public_item(quote or {}, 24),
            "static_info": self._compact_public_item(static_info or {}, 24),
            "calc_indexes": self._compact_public_item(calc_indexes or {}, 28),
            "technical_levels": {
                "latest_close": round_number(closes[-1], 4) if closes else None,
                "ma20": round_number(sum(closes[-20:]) / min(len(closes), 20), 4) if closes else None,
                "ma60": round_number(sum(closes[-60:]) / min(len(closes), 60), 4) if closes else None,
                "high_20d": round_number(max(closes[-20:]), 4) if closes else None,
                "low_20d": round_number(min(closes[-20:]), 4) if closes else None,
                "volume_ratio_20d": round_number(latest_volume / avg_20_volume, 4) if latest_volume is not None and avg_20_volume not in (None, 0.0) else None,
            },
            "news": [self._compact_public_item(item, 8) for item in news],
            "filings": [self._compact_public_item(item, 8) for item in filings],
            "topics": [self._compact_public_item(item, 8) for item in topics],
        }

    def _fetch_candles(self, symbol: str, start: str, end: str, data_quality: dict) -> list[dict]:
        try:
            response = self.longbridge_client.get_candles(symbol=symbol, start=start, end=end, period="day", adjust_type="forward")
            return [item.model_dump() for item in response.items]
        except (LongbridgeUnavailableError, LongbridgeExternalDataError, ValueError) as exc:
            with self._data_quality_lock:
                data_quality["warnings"].append(f"Longbridge public candles unavailable for {symbol}: {exc}")
            return []

    def _fetch_public_field(self, label: str, fetcher, symbol: str, data_quality: dict, *args):
        try:
            return fetcher(symbol, *args)
        except (AttributeError, LongbridgeUnavailableError, LongbridgeExternalDataError, ValueError) as exc:
            with self._data_quality_lock:
                data_quality["warnings"].append(f"Longbridge public {label} unavailable for {symbol}: {exc}")
            return None

    def _fetch_news(self, symbol: str, data_quality: dict, limit: int) -> list[dict]:
        try:
            response = self.longbridge_client.get_news(symbol=symbol, limit=limit)
            return [item.model_dump() for item in response.items]
        except (LongbridgeUnavailableError, LongbridgeExternalDataError, ValueError) as exc:
            with self._data_quality_lock:
                data_quality["warnings"].append(f"Longbridge public news unavailable for {symbol}: {exc}")
            return []

    def _period_return_percent(self, candles: list[dict]) -> float | None:
        if len(candles) < 2:
            return None
        first = to_float(candles[0].get("close"))
        last = to_float(candles[-1].get("close"))
        if first in (None, 0.0) or last is None:
            return None
        return (last - first) / abs(first) * 100.0

    def _single_day_return_percent(self, candles: list[dict]) -> float | None:
        """Calculate single day return from the last two candles."""
        if len(candles) < 2:
            return None
        closes = [c.get("close") for c in candles if c.get("close") is not None]
        if len(closes) < 2:
            return None
        prev = float(closes[-2])
        last = float(closes[-1])
        if prev == 0:
            return None
        return (last - prev) / abs(prev) * 100.0

    def _market_start_date(self, report_date: str, days: int = 14) -> str:
        parsed = parse_date(report_date) or date.today()
        return (parsed - timedelta(days=days)).isoformat()

    def _calculate_unexplained_pnl(self, daily_pnl: float | None, positions: list[dict]) -> float | None:
        if daily_pnl is None:
            return None
        explained = sum(item.get("daily_pnl") or 0.0 for item in positions)
        return round_number(daily_pnl - explained, 2)

    def _public_item_list(self, value: Any) -> list[dict]:
        if value is None:
            return []
        items_attr = getattr(value, "items", None)
        if items_attr is not None and not callable(items_attr):
            raw_items = items_attr
        elif isinstance(value, dict) and isinstance(value.get("items"), list):
            raw_items = value["items"]
        elif isinstance(value, list):
            raw_items = value
        else:
            raw_items = []
        result = []
        for item in raw_items:
            if hasattr(item, "model_dump"):
                item = item.model_dump()
            if isinstance(item, dict):
                result.append(item)
        return result

    def _compact_public_item(self, item: Any, max_items: int) -> dict:
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        if not isinstance(item, dict):
            return {}
        compact: dict[str, Any] = {}
        for key, value in item.items():
            if len(compact) >= max_items:
                break
            if value in (None, "", [], {}):
                continue
            if isinstance(value, (str, int, float, bool)):
                compact[str(key)] = value
        return compact

    @staticmethod
    def _run_parallel(*funcs: callable) -> tuple:
        with ThreadPoolExecutor(max_workers=len(funcs)) as executor:
            futures = [executor.submit(fn) for fn in funcs]
            return tuple(future.result() for future in futures)
