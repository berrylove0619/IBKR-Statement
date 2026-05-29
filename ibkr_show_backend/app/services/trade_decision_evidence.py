from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
import threading
from typing import Any

from app.agents.evidence_schema import build_trade_decision_evidence_pack
from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings
from app.services.longbridge_service import LongbridgeExternalDataClient, LongbridgeExternalDataError, LongbridgeUnavailableError, normalize_longbridge_symbol
from app.services.trade_decision_metrics import TradeDecisionMetricsCalculator, to_float
from app.services.trade_review_evidence import DEFAULT_BENCHMARKS, TARGET_ANNUAL_RETURN, build_stable_trade_id, normalize_ibkr_symbol
from app.utils.dates import parse_date

CASH_EQUIVALENT_SYMBOLS = {"SGOV", "STRC", "BIL", "SHV", "USFR", "TFLO", "BOXX"}


class TradeDecisionEvidenceBuilder:
    def __init__(
        self,
        es_client: ElasticsearchClient,
        settings: Settings,
        longbridge_client: LongbridgeExternalDataClient,
        metrics_calculator: TradeDecisionMetricsCalculator | None = None,
    ) -> None:
        self.es_client = es_client
        self.settings = settings
        self.longbridge_client = longbridge_client
        self.metrics = metrics_calculator or TradeDecisionMetricsCalculator()
        self._data_quality_lock = threading.Lock()

    def build_holding_decision_evidence(self, symbol: str, question: str | None = None) -> dict:
        longbridge_symbol = normalize_longbridge_symbol(symbol)
        ibkr_symbol = normalize_ibkr_symbol(symbol)
        data_quality = {"missing_fields": [], "warnings": []}
        position = self._fetch_current_position(ibkr_symbol)
        if not position:
            data_quality["warnings"].append("No current IBKR position found for holding decision")
        trades = self._fetch_symbol_trades(ibkr_symbol, limit=50)
        account_context = self._build_account_context()
        position_context = self._build_position_context(position)
        trade_history_context = self._build_trade_history_context(trades)
        review_context = self._build_review_context(longbridge_symbol)
        public_context = self._build_public_context(longbridge_symbol, data_quality)

        return build_trade_decision_evidence_pack({
            "decision_type": "holding_decision",
            "objective": self._objective(),
            "symbol": longbridge_symbol,
            "user_question": question,
            "data_sources": self._data_sources(),
            "account_context": account_context,
            "position_context": position_context,
            "trade_history_context": trade_history_context,
            "review_context": review_context,
            "company_context": public_context["company_context"],
            "valuation_context": public_context["valuation_context"],
            "market_context": public_context["market_context"],
            "external_events": public_context["external_events"],
            "data_quality": data_quality,
        })

    def build_entry_decision_evidence(self, symbol: str, question: str | None = None) -> dict:
        longbridge_symbol = normalize_longbridge_symbol(symbol)
        ibkr_symbol = normalize_ibkr_symbol(symbol)
        data_quality = {"missing_fields": [], "warnings": []}
        position = self._fetch_current_position(ibkr_symbol)
        trades = self._fetch_symbol_trades(ibkr_symbol, limit=20)
        account_context = self._build_account_context()
        review_context = self._build_review_context(longbridge_symbol)
        public_context = self._build_public_context(longbridge_symbol, data_quality)

        return build_trade_decision_evidence_pack({
            "decision_type": "entry_decision",
            "objective": self._objective(),
            "symbol": longbridge_symbol,
            "user_question": question,
            "data_sources": self._data_sources(),
            "account_context": account_context,
            "position_context": self._build_position_context(position),
            "trade_history_context": self._build_trade_history_context(trades),
            "review_context": review_context,
            "company_context": public_context["company_context"],
            "valuation_context": public_context["valuation_context"],
            "market_context": public_context["market_context"],
            "external_events": public_context["external_events"],
            "data_quality": data_quality,
        })

    def list_current_holdings(self) -> list[dict]:
        latest = self._latest_account_date()
        if not latest:
            return []
        response = self.es_client.search(
            index=self.settings.es_position_index,
            body={
                "query": {"bool": {"filter": [{"term": {"report_date": latest}}]}},
                "sort": [{"position_value": {"order": "desc", "missing": "_last"}}],
                "size": 500,
                "_source": [
                    "symbol",
                    "quantity",
                    "mark_price",
                    "position_value",
                    "percent_of_nav",
                    "average_cost_price",
                    "cost_basis_money",
                    "total_unrealized_pnl",
                    "unrealized_pnl_percent",
                ],
            },
        )
        holdings = []
        for hit in response.get("hits", {}).get("hits", []):
            source = hit.get("_source", {})
            symbol = source.get("symbol")
            if not symbol:
                continue
            position_pct = self._nav_percent_to_ratio(source.get("percent_of_nav"))
            latest_review = self._latest_symbol_review(normalize_longbridge_symbol(symbol))
            latest_decision = self._latest_symbol_decision(normalize_longbridge_symbol(symbol))
            holdings.append(
                {
                    "symbol": symbol,
                    "normalized_symbol": normalize_longbridge_symbol(symbol),
                    "quantity": to_float(source.get("quantity")),
                    "avg_cost": to_float(source.get("average_cost_price")),
                    "current_price": to_float(source.get("mark_price")),
                    "market_value": to_float(source.get("position_value")),
                    "position_pct": position_pct,
                    "unrealized_pnl": to_float(source.get("total_unrealized_pnl")),
                    "unrealized_pnl_pct": self._ratio_from_percent_or_cost(source),
                    "latest_review_score": latest_review.get("overall_score") if latest_review else None,
                    "latest_decision": latest_decision.get("action") if latest_decision else None,
                    "data_source": "IBKR",
                }
            )
        return holdings

    def tool_get_account_summary(self) -> dict:
        return self._build_account_context()

    def tool_get_position(self, symbol: str) -> dict:
        return self._build_position_context(self._fetch_current_position(normalize_ibkr_symbol(symbol)))

    def tool_get_trade_history(self, symbol: str, limit: int = 20) -> dict:
        normalized_limit = max(1, min(int(limit), 50))
        return self._build_trade_history_context(self._fetch_symbol_trades(normalize_ibkr_symbol(symbol), limit=normalized_limit))

    def tool_get_review_context(self, symbol: str) -> dict:
        return self._build_review_context(normalize_longbridge_symbol(symbol))

    def tool_get_market_context(self, symbol: str) -> dict:
        data_quality = {"missing_fields": [], "warnings": []}
        end = date.today().isoformat()
        start = (date.today() - timedelta(days=260)).isoformat()
        normalized = normalize_longbridge_symbol(symbol)
        all_symbols = [normalized] + list(DEFAULT_BENCHMARKS)
        results: dict[str, list[dict]] = {}
        with ThreadPoolExecutor(max_workers=len(all_symbols)) as executor:
            futures = {executor.submit(self._fetch_candles, s, start, end, data_quality): s for s in all_symbols}
            for future in as_completed(futures):
                sym = futures[future]
                try:
                    results[sym] = future.result()
                except Exception:
                    results[sym] = []
        candles = results.get(normalized, [])
        benchmarks = {b: results.get(b, []) for b in DEFAULT_BENCHMARKS}
        context = self.metrics.calculate_market_context(candles, benchmarks)
        return {**context, "data_quality": data_quality}

    def tool_get_company_public_context(self, symbol: str) -> dict:
        data_quality = {"missing_fields": [], "warnings": []}
        normalized = normalize_longbridge_symbol(symbol)

        def fetch_static_info() -> dict:
            return self._fetch_longbridge_public_field("static info", self.longbridge_client.get_static_info, normalized, data_quality) or {}

        def fetch_financial_context() -> dict:
            return self._build_financial_context(normalized, data_quality)

        static_info, financial_context = self._run_parallel(fetch_static_info, fetch_financial_context)
        return {
            "source": "Longbridge public static info and financial reports",
            "static_info": static_info,
            "financial_context": financial_context,
            "data_quality": data_quality,
        }

    def tool_get_valuation_context(self, symbol: str) -> dict:
        data_quality = {"missing_fields": [], "warnings": []}
        normalized = normalize_longbridge_symbol(symbol)

        def fetch_public_fields() -> dict:
            results = {}
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = [
                    executor.submit(self._fetch_longbridge_public_field, "quote snapshot", self.longbridge_client.get_quote_snapshot, normalized, data_quality),
                    executor.submit(self._fetch_longbridge_public_field, "static info", self.longbridge_client.get_static_info, normalized, data_quality),
                    executor.submit(self._fetch_longbridge_public_field, "calc indexes", self.longbridge_client.get_calc_indexes, normalized, data_quality),
                ]
                labels = ["quote", "static_info", "calc_indexes"]
                for label, future in zip(labels, futures):
                    try:
                        results[label] = future.result()
                    except Exception:
                        results[label] = None
            return results

        def fetch_snapshot() -> dict:
            return self._build_market_snapshot(normalized, data_quality)

        public_fields, market_snapshot = self._run_parallel(fetch_public_fields, fetch_snapshot)
        quote = public_fields.get("quote")
        static_info = public_fields.get("static_info")
        calc_indexes = public_fields.get("calc_indexes")
        return {
            "source": "Longbridge public calc indexes",
            "quote": quote or {},
            "calc_indexes": calc_indexes or {},
            "market_snapshot": market_snapshot,
            "valuation_metrics": self._extract_valuation_metrics(static_info or {}, calc_indexes or {}),
            "data_quality": data_quality,
        }

    def tool_get_external_events(self, symbol: str, limit: int = 10) -> dict:
        data_quality = {"missing_fields": [], "warnings": []}
        normalized = normalize_longbridge_symbol(symbol)
        normalized_limit = max(1, min(int(limit), 20))
        news = self._fetch_news(normalized, data_quality)[:normalized_limit]
        filings = self._fetch_longbridge_public_field("filings", self.longbridge_client.get_filings, normalized, data_quality, normalized_limit)
        topics = self._fetch_longbridge_public_field("topics", self.longbridge_client.get_topics, normalized, data_quality, normalized_limit)
        return {
            "source": "Longbridge public data",
            "news": news,
            "filings": filings or [],
            "topics": topics or [],
            "data_quality": data_quality,
        }

    def tool_get_macro_news(self, keyword: str = "macro economy", limit: int = 10) -> dict:
        data_quality = {"missing_fields": [], "warnings": []}
        try:
            response = self.longbridge_client.search_macro_news(keyword=keyword, limit=max(1, min(int(limit), 20)))
            return {"source": "Longbridge macro news search", "keyword": response.keyword, "news": [item.model_dump() for item in response.items], "data_quality": data_quality}
        except (AttributeError, LongbridgeUnavailableError, LongbridgeExternalDataError, ValueError) as exc:
            data_quality["warnings"].append(f"Longbridge macro news unavailable: {exc}")
            return {"source": "Longbridge macro news search", "keyword": keyword, "news": [], "data_quality": data_quality}

    def _objective(self) -> dict:
        return {
            "target_annual_return": TARGET_ANNUAL_RETURN,
            "style": "aggressive_growth",
            "goal": "maximize_long_term_account_return",
        }

    def _data_sources(self) -> dict:
        return {
            "account_data": "IBKR_ONLY",
            "position_data": "IBKR_ONLY",
            "trade_data": "IBKR_ONLY",
            "public_market_data": "LONGBRIDGE_PUBLIC_ONLY",
            "llm": "LLMService",
        }

    def _build_account_context(self) -> dict:
        account = self._latest_account_snapshot()
        positions = self._latest_positions(limit=20)
        net_liquidation = to_float(account.get("total_equity")) if account else None
        cash = to_float(account.get("cash")) if account else None
        total_position_value = sum(abs(to_float(item.get("position_value")) or 0.0) for item in positions)
        cash_equivalent_positions = self._cash_equivalent_positions(positions)
        cash_equivalents_value = round(sum(abs(item.get("position_value") or 0.0) for item in cash_equivalent_positions), 4)
        deployable_liquidity = round((cash or 0.0) + cash_equivalents_value, 4)
        top_positions = [
            {
                "symbol": item.get("symbol"),
                "position_value": to_float(item.get("position_value")),
                "position_pct": self._nav_percent_to_ratio(item.get("percent_of_nav")),
            }
            for item in positions[:5]
        ]
        concentration = sum(item.get("position_pct") or 0.0 for item in top_positions[:3])
        risk_positions = [item for item in positions if not self._is_cash_equivalent_symbol(item.get("symbol"))]
        risk_concentration = sum(self._nav_percent_to_ratio(item.get("percent_of_nav")) or 0.0 for item in risk_positions[:3])
        return {
            "source": "IBKR",
            "net_liquidation": net_liquidation,
            "cash": cash,
            "cash_ratio": self.metrics.calculate_cash_ratio(cash, net_liquidation),
            "cash_equivalents_value": cash_equivalents_value,
            "cash_equivalents_ratio": self.metrics.calculate_cash_ratio(cash_equivalents_value, net_liquidation),
            "cash_equivalent_positions": cash_equivalent_positions,
            "deployable_liquidity": deployable_liquidity,
            "deployable_liquidity_ratio": self.metrics.calculate_cash_ratio(deployable_liquidity, net_liquidation),
            "margin_info": None,
            "total_position_value": round(total_position_value, 4),
            "top_positions": top_positions,
            "position_concentration": round(concentration, 6),
            "risk_position_concentration_ex_cash_equivalents": round(risk_concentration, 6),
        }

    def _cash_equivalent_positions(self, positions: list[dict]) -> list[dict]:
        items = []
        for position in positions:
            if not self._is_cash_equivalent_symbol(position.get("symbol")):
                continue
            items.append(
                {
                    "symbol": position.get("symbol"),
                    "position_value": abs(to_float(position.get("position_value")) or 0.0),
                    "position_pct": self._nav_percent_to_ratio(position.get("percent_of_nav")),
                    "liquidity_note": "cash_equivalent_sellable",
                }
            )
        return items

    def _is_cash_equivalent_symbol(self, symbol: object) -> bool:
        normalized = str(symbol or "").upper().split(".", 1)[0]
        return normalized in CASH_EQUIVALENT_SYMBOLS

    def _build_position_context(self, position: dict | None) -> dict:
        if not position:
            return {
                "source": "IBKR",
                "is_holding": False,
                "quantity": 0,
                "avg_cost": None,
                "current_price": None,
                "market_value": 0,
                "position_pct": 0,
                "unrealized_pnl": 0,
                "unrealized_pnl_pct": None,
                "realized_pnl": None,
            }
        position_pct = self._nav_percent_to_ratio(position.get("percent_of_nav"))
        unrealized = to_float(position.get("total_unrealized_pnl"))
        cost_basis = to_float(position.get("cost_basis_money"))
        return {
            "source": "IBKR",
            "is_holding": abs(to_float(position.get("quantity")) or 0.0) > 0,
            "quantity": to_float(position.get("quantity")),
            "avg_cost": to_float(position.get("average_cost_price")),
            "current_price": to_float(position.get("mark_price")),
            "market_value": to_float(position.get("position_value")),
            "position_pct": position_pct,
            "unrealized_pnl": unrealized,
            "unrealized_pnl_pct": self._ratio_from_percent_or_cost(position) or self.metrics.calculate_unrealized_pnl_pct(unrealized, cost_basis),
            "realized_pnl": to_float(position.get("total_realized_pnl")),
        }

    def _build_trade_history_context(self, trades: list[dict]) -> dict:
        normalized = [self._normalize_trade(item) for item in trades]
        dates = [item.get("date") for item in normalized if item.get("date")]
        first_buy = next((item.get("date") for item in normalized if item.get("side") == "BUY" and item.get("date")), None)
        last_trade = dates[-1] if dates else None
        holding_days = None
        if first_buy and last_trade:
            first_date = parse_date(first_buy)
            last_date = parse_date(last_trade)
            holding_days = (last_date - first_date).days if first_date and last_date else None
        return {
            "source": "IBKR",
            "recent_trades": normalized[-20:],
            "first_buy_date": first_buy,
            "last_trade_date": last_trade,
            "holding_days": holding_days,
        }

    def _build_review_context(self, symbol: str) -> dict:
        latest_review = self._latest_symbol_review(symbol)
        return {
            "source": "trade_review_agent",
            "symbol_latest_review": latest_review,
            "symbol_mistake_tags": latest_review.get("mistake_tags", []) if latest_review else [],
            "global_mistake_summary": self._global_mistake_summary(),
            "important_warnings": [],
        }

    def _build_public_context(self, symbol: str, data_quality: dict) -> dict:
        end = date.today().isoformat()
        start = (date.today() - timedelta(days=260)).isoformat()
        all_symbols = [symbol] + list(DEFAULT_BENCHMARKS)
        candle_results: dict[str, list[dict]] = {}
        with ThreadPoolExecutor(max_workers=len(all_symbols)) as executor:
            futures = {executor.submit(self._fetch_candles, s, start, end, data_quality): s for s in all_symbols}
            for future in as_completed(futures):
                sym = futures[future]
                try:
                    candle_results[sym] = future.result()
                except Exception:
                    candle_results[sym] = []
        candles = candle_results.get(symbol, [])
        benchmarks = {b: candle_results.get(b, []) for b in DEFAULT_BENCHMARKS}
        market_context = self.metrics.calculate_market_context(candles, benchmarks)

        def fetch_longbridge_fields() -> dict:
            results: dict[str, Any] = {}
            with ThreadPoolExecutor(max_workers=6) as executor:
                futures = [
                    executor.submit(self._fetch_longbridge_public_field, "quote snapshot", self.longbridge_client.get_quote_snapshot, symbol, data_quality),
                    executor.submit(self._fetch_longbridge_public_field, "static info", self.longbridge_client.get_static_info, symbol, data_quality),
                    executor.submit(self._fetch_longbridge_public_field, "calc indexes", self.longbridge_client.get_calc_indexes, symbol, data_quality),
                    executor.submit(self._fetch_longbridge_public_field, "filings", self.longbridge_client.get_filings, symbol, data_quality, 10),
                    executor.submit(self._fetch_longbridge_public_field, "topics", self.longbridge_client.get_topics, symbol, data_quality, 10),
                    executor.submit(self._fetch_news, symbol, data_quality),
                ]
                labels = ["quote", "static_info", "calc_indexes", "filings", "topics", "news"]
                for label, future in zip(labels, futures):
                    try:
                        results[label] = future.result()
                    except Exception:
                        results[label] = None if label != "news" else []
            return results

        def fetch_heavy_context() -> tuple:
            return self._build_financial_context(symbol, data_quality), self._build_market_snapshot(symbol, data_quality)

        lb_results, (financial_context, market_snapshot) = fetch_longbridge_fields(), fetch_heavy_context()
        quote = lb_results.get("quote")
        static_info = lb_results.get("static_info")
        calc_indexes = lb_results.get("calc_indexes")
        filings = lb_results.get("filings") or []
        topics = lb_results.get("topics") or []
        news = lb_results.get("news") or []
        return {
            "company_context": {
                "source": "Longbridge public static info and financial reports",
                "static_info": static_info or {},
                "financial_context": financial_context,
            },
            "valuation_context": {
                "source": "Longbridge public calc indexes",
                "quote": quote or {},
                "calc_indexes": calc_indexes or {},
                "market_snapshot": market_snapshot,
                "valuation_metrics": self._extract_valuation_metrics(static_info or {}, calc_indexes or {}),
            },
            "market_context": market_context,
            "external_events": {
                "source": "Longbridge public data",
                "news": news,
                "filings": filings or [],
                "topics": topics or [],
                "warnings": [],
            },
        }

    def _fetch_longbridge_public_field(self, label: str, fetcher, symbol: str, data_quality: dict, *args):
        try:
            value = fetcher(symbol, *args)
        except (AttributeError, LongbridgeUnavailableError, LongbridgeExternalDataError, ValueError) as exc:
            with self._data_quality_lock:
                data_quality["warnings"].append(f"Longbridge public {label} unavailable for {symbol}: {exc}")
            return None
        if _looks_empty_longbridge_payload(value, symbol):
            with self._data_quality_lock:
                data_quality["warnings"].append(
                    f"Longbridge public {label} returned no usable data for {symbol}; verify the ticker or Longbridge coverage"
                )
        return value

    def _build_financial_context(self, symbol: str, data_quality: dict) -> dict:
        try:
            from app.services.symbol_analysis_service import SymbolAnalysisService

            financials = SymbolAnalysisService(self.longbridge_client, None).get_financials(symbol, periods=4)
        except (AttributeError, LongbridgeUnavailableError, LongbridgeExternalDataError, ValueError) as exc:
            with self._data_quality_lock:
                data_quality["warnings"].append(f"Longbridge public financial reports unavailable for {symbol}: {exc}")
            return {"source": "Longbridge financial reports", "period_count": 0, "periods": []}

        periods = [
            {
                "label": period.label,
                "fiscal_year": period.fiscal_year,
                "metrics": self._compact_financial_metrics(period.metrics),
            }
            for period in financials.periods[:4]
        ]
        return {
            "source": "Longbridge financial reports",
            "currency": financials.currency,
            "report_type": financials.report_type,
            "period_count": financials.period_count,
            "periods": periods,
            "latest_metrics": periods[0]["metrics"] if periods else {},
        }

    def _build_market_snapshot(self, symbol: str, data_quality: dict) -> dict:
        try:
            from app.services.symbol_analysis_service import SymbolAnalysisService

            snapshot = SymbolAnalysisService(self.longbridge_client, None).get_market_snapshot(symbol)
        except (AttributeError, LongbridgeUnavailableError, LongbridgeExternalDataError, ValueError) as exc:
            with self._data_quality_lock:
                data_quality["warnings"].append(f"Longbridge public valuation snapshot unavailable for {symbol}: {exc}")
            return {}
        if snapshot is None:
            return {}
        return snapshot.model_dump()

    def _compact_financial_metrics(self, metrics: dict) -> dict:
        keys = [
            "revenue",
            "gross_profit",
            "gross_margin",
            "operating_income",
            "operating_margin",
            "net_income",
            "net_margin",
            "eps",
            "operating_cash_flow",
            "free_cash_flow",
            "cash_and_equivalents",
            "total_debt",
            "shareholders_equity",
            "roe",
        ]
        return {key: metrics.get(key) for key in keys if metrics.get(key) is not None}

    def _extract_valuation_metrics(self, static_info: dict, calc_indexes: dict) -> dict:
        return {
            "pe_ttm_ratio": to_float(calc_indexes.get("pe_ttm_ratio")),
            "pb_ratio": to_float(calc_indexes.get("pb_ratio")),
            "dividend_ratio_ttm": to_float(calc_indexes.get("dividend_ratio_ttm")),
            "total_market_value": to_float(calc_indexes.get("total_market_value")),
            "eps": to_float(static_info.get("eps")),
            "eps_ttm": to_float(static_info.get("eps_ttm")),
            "bps": to_float(static_info.get("bps")),
            "dividend_yield": to_float(static_info.get("dividend_yield")),
            "total_shares": to_float(static_info.get("total_shares")),
            "circulating_shares": to_float(static_info.get("circulating_shares")),
        }

    def _fetch_candles(self, symbol: str, start: str, end: str, data_quality: dict) -> list[dict]:
        try:
            response = self.longbridge_client.get_candles(symbol=symbol, start=start, end=end, period="day", adjust_type="forward")
            items = [item.model_dump() for item in response.items]
            if not items:
                with self._data_quality_lock:
                    data_quality["warnings"].append(
                        f"Longbridge public candles returned no data for {symbol}; verify the ticker or Longbridge coverage"
                    )
            return items
        except (LongbridgeUnavailableError, LongbridgeExternalDataError, ValueError) as exc:
            with self._data_quality_lock:
                data_quality["warnings"].append(f"Longbridge public candles unavailable for {symbol}: {exc}")
            return []

    def _fetch_news(self, symbol: str, data_quality: dict) -> list[dict]:
        try:
            response = self.longbridge_client.get_news(symbol=symbol, limit=20)
            with self._data_quality_lock:
                data_quality["warnings"].append("Longbridge news API may not provide complete historical news range")
            return [item.model_dump() for item in response.items]
        except (LongbridgeUnavailableError, LongbridgeExternalDataError, ValueError) as exc:
            with self._data_quality_lock:
                data_quality["warnings"].append(f"Longbridge public news unavailable for {symbol}: {exc}")
            return []

    def _latest_account_snapshot(self) -> dict | None:
        response = self.es_client.search(
            index=self.settings.es_account_index,
            body={
                "size": 1,
                "sort": [{"report_date": {"order": "desc"}}],
                "_source": ["account_id", "report_date", "currency", "total_equity", "cash"],
            },
        )
        hits = response.get("hits", {}).get("hits", [])
        return hits[0].get("_source", {}) if hits else None

    def _latest_account_date(self) -> str | None:
        account = self._latest_account_snapshot()
        return account.get("report_date") if account else None

    def _latest_positions(self, limit: int = 500) -> list[dict]:
        latest = self._latest_account_date()
        if not latest:
            return []
        response = self.es_client.search(
            index=self.settings.es_position_index,
            body={
                "query": {"bool": {"filter": [{"term": {"report_date": latest}}]}},
                "sort": [{"position_value": {"order": "desc", "missing": "_last"}}],
                "size": limit,
                "_source": ["symbol", "position_value", "percent_of_nav"],
            },
        )
        return [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]

    def _fetch_current_position(self, symbol: str) -> dict | None:
        latest = self._latest_account_date()
        if not latest:
            return None
        response = self.es_client.search(
            index=self.settings.es_position_index,
            body={
                "query": {"bool": {"filter": [{"term": {"report_date": latest}}, {"terms": {"symbol": self._symbol_variants(symbol)}}]}},
                "size": 1,
                "_source": True,
            },
        )
        hits = response.get("hits", {}).get("hits", [])
        return hits[0].get("_source", {}) if hits else None

    def _fetch_symbol_trades(self, symbol: str, limit: int) -> list[dict]:
        response = self.es_client.search(
            index=self.settings.es_trade_index,
            body={
                "query": {"bool": {"filter": [{"terms": {"symbol": self._symbol_variants(symbol)}}]}},
                "sort": [{"trade_date": {"order": "asc"}}, {"date_time": {"order": "asc", "missing": "_last"}}],
                "size": limit,
                "_source": True,
            },
        )
        return [self._with_id(hit) for hit in response.get("hits", {}).get("hits", [])]

    def _latest_symbol_review(self, symbol: str) -> dict | None:
        try:
            response = self.es_client.search(
                index=self.settings.es_trade_review_index,
                body={
                    "query": {"bool": {"filter": [{"term": {"symbol": normalize_longbridge_symbol(symbol)}}]}},
                    "sort": [{"created_at": {"order": "desc"}}],
                    "size": 1,
                    "_source": ["id", "overall_score", "rating", "summary", "mistake_tags", "created_at"],
                },
            )
        except ESIndexNotFoundError:
            return None
        hits = response.get("hits", {}).get("hits", [])
        return hits[0].get("_source", {}) if hits else None

    def _latest_symbol_decision(self, symbol: str) -> dict | None:
        try:
            response = self.es_client.search(
                index=self.settings.es_trade_decision_index,
                body={
                    "query": {"bool": {"filter": [{"term": {"symbol": normalize_longbridge_symbol(symbol)}}]}},
                    "sort": [{"created_at": {"order": "desc"}}],
                    "size": 1,
                    "_source": ["id", "action", "overall_score", "created_at"],
                },
            )
        except ESIndexNotFoundError:
            return None
        hits = response.get("hits", {}).get("hits", [])
        return hits[0].get("_source", {}) if hits else None

    def _global_mistake_summary(self) -> list[dict]:
        try:
            response = self.es_client.search(
                index=self.settings.es_trade_review_index,
                body={"size": 0, "aggs": {"mistakes": {"terms": {"field": "mistake_tags", "size": 20}}}},
            )
        except ESIndexNotFoundError:
            return []
        return [
            {"tag": bucket.get("key"), "count": bucket.get("doc_count", 0)}
            for bucket in response.get("aggregations", {}).get("mistakes", {}).get("buckets", [])
        ]

    def _normalize_trade(self, trade: dict) -> dict:
        side = str(trade.get("buy_sell") or "").upper()
        return {
            "trade_id": build_stable_trade_id(trade),
            "date": trade.get("trade_date") or (str(trade.get("date_time"))[:10] if trade.get("date_time") else None),
            "side": side,
            "quantity": abs(to_float(trade.get("quantity")) or 0.0),
            "price": to_float(trade.get("trade_price")),
            "amount": abs(to_float(trade.get("proceeds")) or 0.0),
            "commission": abs(to_float(trade.get("ib_commission")) or 0.0),
            "currency": trade.get("currency"),
            "realized_pnl": to_float(trade.get("fifo_pnl_realized")),
        }

    def _with_id(self, hit: dict) -> dict:
        source = dict(hit.get("_source", {}))
        source["_id"] = hit.get("_id")
        return source

    def _symbol_variants(self, symbol: str) -> list[str]:
        base = normalize_ibkr_symbol(symbol)
        return list(dict.fromkeys([base, f"{base}.US", f"US.{base}"]))

    def _nav_percent_to_ratio(self, value: object) -> float | None:
        number = to_float(value)
        if number is None:
            return None
        return round(number / 100.0 if abs(number) > 1 else number, 6)

    def _ratio_from_percent_or_cost(self, source: dict) -> float | None:
        percent = to_float(source.get("unrealized_pnl_percent"))
        if percent is not None:
            return round(percent / 100.0 if abs(percent) > 1 else percent, 6)
        return self.metrics.calculate_unrealized_pnl_pct(to_float(source.get("total_unrealized_pnl")), to_float(source.get("cost_basis_money")))

    @staticmethod
    def _run_parallel(*funcs: callable) -> tuple:
        with ThreadPoolExecutor(max_workers=len(funcs)) as executor:
            futures = [executor.submit(fn) for fn in funcs]
            return tuple(future.result() for future in futures)


def _looks_empty_longbridge_payload(value: object, symbol: str) -> bool:
    if value is None:
        return True
    if isinstance(value, list):
        return len(value) == 0
    if not isinstance(value, dict):
        return False
    meaningful_items = [item for key, item in value.items() if key != "symbol" and item not in (None, "", [], {})]
    return not meaningful_items and str(value.get("symbol") or "").upper() == symbol.upper()
