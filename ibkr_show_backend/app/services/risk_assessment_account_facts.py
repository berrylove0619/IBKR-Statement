"""Account risk facts builder - reads IBKR data from ES only."""

from __future__ import annotations

from typing import Any

from app.agents.risk_assessment_graph.cards import AccountRiskSnapshot, PositionEntry
from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings
from app.services.trade_decision_metrics import to_float


CASH_EQUIVALENT_SYMBOLS = {"SGOV", "STRC", "BIL", "SHV", "USFR", "TFLO", "BOXX"}


def _is_cash_equivalent(symbol: str) -> bool:
    return str(symbol or "").upper().split(".", 1)[0] in CASH_EQUIVALENT_SYMBOLS


def _nav_percent_to_ratio(value: object) -> float | None:
    number = to_float(value)
    if number is None:
        return None
    return round(number / 100.0 if abs(number) > 1 else number, 6)


def _normalize_symbol(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    if "." not in normalized:
        normalized = f"{normalized}.US"
    return normalized


class RiskAssessmentAccountFactsBuilder:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    def build(self, question: str | None = None) -> AccountRiskSnapshot:
        account = self._latest_account_snapshot()
        raw_positions = self._latest_positions(limit=50)

        net_liquidation = to_float(account.get("total_equity")) if account else None
        cash = to_float(account.get("cash")) if account else None

        positions: list[PositionEntry] = []
        total_position_value = 0.0
        total_unrealized_pnl = 0.0

        for item in raw_positions:
            sym = item.get("symbol")
            if not sym:
                continue
            normalized = _normalize_symbol(sym)
            mv = abs(to_float(item.get("position_value")) or 0.0)
            total_position_value += mv
            pos_pct = _nav_percent_to_ratio(item.get("percent_of_nav")) or 0.0
            u_pnl = to_float(item.get("total_unrealized_pnl")) or 0.0
            total_unrealized_pnl += u_pnl
            u_pnl_pct = _nav_percent_to_ratio(item.get("unrealized_pnl_percent"))
            positions.append(PositionEntry(
                symbol=sym,
                normalized_symbol=normalized,
                quantity=abs(to_float(item.get("quantity")) or 0.0),
                avg_cost=to_float(item.get("average_cost_price")),
                current_price=to_float(item.get("mark_price")),
                market_value=mv,
                position_pct=pos_pct,
                unrealized_pnl=u_pnl,
                unrealized_pnl_pct=u_pnl_pct,
            ))

        # Sort by market_value desc
        positions.sort(key=lambda p: p.market_value, reverse=True)

        # Compute concentration metrics
        risk_positions = [p for p in positions if not _is_cash_equivalent(p.symbol)]
        largest_pct = risk_positions[0].position_pct if risk_positions else 0.0
        top_3_pct = sum(p.position_pct for p in risk_positions[:3])
        top_5_pct = sum(p.position_pct for p in risk_positions[:5])

        cash_pct = round((cash or 0.0) / net_liquidation, 6) if net_liquidation else 0.0
        margin_usage_pct = 0.0
        if net_liquidation and total_position_value > net_liquidation:
            margin_usage_pct = round((total_position_value - net_liquidation) / net_liquidation, 6)

        top_positions_dict = [
            {"symbol": p.symbol, "position_value": p.market_value, "position_pct": p.position_pct}
            for p in positions[:10]
        ]

        return AccountRiskSnapshot(
            net_liquidation=net_liquidation,
            cash=cash,
            deployable_liquidity=round((cash or 0.0) + sum(
                p.market_value for p in positions if _is_cash_equivalent(p.symbol)
            ), 4),
            margin_info=None,
            positions=positions,
            total_position_value=round(total_position_value, 4),
            top_positions=top_positions_dict,
            position_count=len(positions),
            largest_position_pct=round(largest_pct, 6),
            top_3_position_pct=round(top_3_pct, 6),
            top_5_position_pct=round(top_5_pct, 6),
            cash_pct=round(cash_pct, 6),
            margin_usage_pct=round(margin_usage_pct, 6),
            unrealized_pnl=round(total_unrealized_pnl, 4),
            unrealized_pnl_pct=round(total_unrealized_pnl / total_position_value, 6) if total_position_value else 0.0,
            data_quality={"warnings": [], "missing_fields": []},
        )

    def _latest_account_snapshot(self) -> dict | None:
        try:
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
        except ESIndexNotFoundError:
            return None

    def _latest_account_date(self) -> str | None:
        account = self._latest_account_snapshot()
        return account.get("report_date") if account else None

    def _latest_positions(self, limit: int = 50) -> list[dict]:
        latest = self._latest_account_date()
        if not latest:
            return []
        try:
            response = self.es_client.search(
                index=self.settings.es_position_index,
                body={
                    "query": {"bool": {"filter": [{"term": {"report_date": latest}}]}},
                    "sort": [{"position_value": {"order": "desc", "missing": "_last"}}],
                    "size": limit,
                    "_source": [
                        "symbol", "quantity", "mark_price", "position_value",
                        "percent_of_nav", "average_cost_price", "cost_basis_money",
                        "total_unrealized_pnl", "unrealized_pnl_percent",
                    ],
                },
            )
            return [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]
        except ESIndexNotFoundError:
            return []
