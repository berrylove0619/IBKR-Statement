from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.utils.dates import parse_date

POSITION_SIZE_THRESHOLDS = [
    ("tiny", 0.02),
    ("small", 0.05),
    ("medium", 0.15),
    ("large", 0.30),
]


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class TradeReviewMetricsCalculator:
    def calculate_symbol_trade_summary(
        self,
        symbol_trades: list[dict],
        current_position: dict | None = None,
        latest_price: float | None = None,
    ) -> dict:
        buy_quantity = 0.0
        sell_quantity = 0.0
        total_buy_amount = 0.0
        total_sell_amount = 0.0
        total_commission = 0.0
        realized_pnl = 0.0
        has_realized_pnl = False
        first_buy_date = None
        last_trade_date = None

        for trade in symbol_trades:
            trade_date = trade.get("date")
            side = str(trade.get("side") or "").upper()
            quantity = abs(_to_float(trade.get("quantity")) or 0.0)
            price = _to_float(trade.get("price")) or 0.0
            amount = abs(_to_float(trade.get("amount")) or quantity * price)
            commission = abs(_to_float(trade.get("commission")) or 0.0)
            realized_value = _to_float(trade.get("realized_pnl"))

            if trade_date:
                last_trade_date = str(trade_date)
            if side == "BUY":
                buy_quantity += quantity
                total_buy_amount += amount
                if first_buy_date is None:
                    first_buy_date = str(trade_date)
            elif side == "SELL":
                sell_quantity += quantity
                total_sell_amount += amount

            total_commission += commission
            if realized_value is not None:
                realized_pnl += realized_value
                has_realized_pnl = True

        net_quantity = buy_quantity - sell_quantity
        avg_buy_price = total_buy_amount / buy_quantity if buy_quantity else None
        avg_sell_price = total_sell_amount / sell_quantity if sell_quantity else None
        unrealized_pnl = None
        if current_position and current_position.get("total_unrealized_pnl") is not None:
            unrealized_pnl = float(current_position["total_unrealized_pnl"])
        elif net_quantity > 0 and latest_price is not None and avg_buy_price is not None:
            unrealized_pnl = (latest_price - avg_buy_price) * net_quantity

        total_pnl = (realized_pnl if has_realized_pnl else 0.0) + (unrealized_pnl or 0.0)
        invested_base = total_buy_amount or None
        return_rate = total_pnl / invested_base if invested_base else None
        holding_days = self._calculate_holding_days(first_buy_date, last_trade_date)

        return {
            "total_buy_amount": round(total_buy_amount, 4),
            "total_sell_amount": round(total_sell_amount, 4),
            "net_quantity": round(net_quantity, 6),
            "avg_buy_price": round(avg_buy_price, 4) if avg_buy_price is not None else None,
            "avg_sell_price": round(avg_sell_price, 4) if avg_sell_price is not None else None,
            "total_commission": round(total_commission, 4),
            "realized_pnl": round(realized_pnl, 4) if has_realized_pnl else None,
            "unrealized_pnl": round(unrealized_pnl, 4) if unrealized_pnl is not None else None,
            "total_pnl": round(total_pnl, 4),
            "return_rate": round(return_rate, 6) if return_rate is not None else None,
            "holding_days": holding_days,
        }

    def calculate_benchmark_return(self, candles: list[dict], start_date: str, end_date: str) -> float | None:
        start_candle = self._nearest_candle(candles, parse_date(start_date), direction="after")
        end_candle = self._nearest_candle(candles, parse_date(end_date), direction="before")
        if not start_candle or not end_candle:
            return None
        start_close = _to_float(start_candle.get("close"))
        end_close = _to_float(end_candle.get("close"))
        if not start_close:
            return None
        return round((end_close - start_close) / start_close, 6) if end_close is not None else None

    def calculate_post_trade_returns(self, candles: list[dict], trade_date: str) -> dict[str, float | None]:
        base_date = parse_date(trade_date)
        base_candle = self._nearest_candle(candles, base_date, direction="after")
        base_close = _to_float(base_candle.get("close")) if base_candle else None
        returns: dict[str, float | None] = {}
        for days in (7, 30, 90):
            target_candle = self._nearest_candle(candles, base_date + timedelta(days=days), direction="after")
            target_close = _to_float(target_candle.get("close")) if target_candle else None
            key = f"{days}d"
            returns[key] = round((target_close - base_close) / base_close, 6) if base_close and target_close is not None else None
        return returns

    def calculate_max_profit_and_drawdown(
        self,
        candles: list[dict],
        entry_price: float | None,
        start_date: str,
        end_date: str,
    ) -> dict[str, float | None]:
        if not entry_price:
            return {"max_profit_rate_during_holding": None, "max_drawdown_during_holding": None}
        start = parse_date(start_date)
        end = parse_date(end_date)
        scoped = [item for item in candles if self._date_in_range(item.get("date"), start, end)]
        highs = [_to_float(item.get("high")) for item in scoped]
        lows = [_to_float(item.get("low")) for item in scoped]
        highs = [item for item in highs if item is not None]
        lows = [item for item in lows if item is not None]
        max_profit = (max(highs) - entry_price) / entry_price if highs else None
        max_drawdown = (min(lows) - entry_price) / entry_price if lows else None
        return {
            "max_profit_rate_during_holding": round(max_profit, 6) if max_profit is not None else None,
            "max_drawdown_during_holding": round(max_drawdown, 6) if max_drawdown is not None else None,
        }

    def classify_position_size(self, trade_amount: float | None, account_value: float | None) -> str | None:
        if trade_amount is None or not account_value:
            return None
        ratio = abs(trade_amount) / account_value
        for label, threshold in POSITION_SIZE_THRESHOLDS:
            if ratio < threshold:
                return label
        return "concentrated"

    def _calculate_holding_days(self, first_buy_date: str | None, last_trade_date: str | None) -> int | None:
        if not first_buy_date or not last_trade_date:
            return None
        first = parse_date(first_buy_date)
        last = parse_date(last_trade_date)
        if not first or not last:
            return None
        return max((last - first).days, 0)

    def _nearest_candle(self, candles: list[dict], target_date: date | None, direction: str) -> dict | None:
        if target_date is None:
            return None
        dated = [(parse_date(str(item.get("date"))), item) for item in candles if item.get("date")]
        dated = [(item_date, item) for item_date, item in dated if item_date is not None]
        if direction == "after":
            candidates = [(item_date, item) for item_date, item in dated if item_date >= target_date]
            return min(candidates, key=lambda item: item[0])[1] if candidates else None
        candidates = [(item_date, item) for item_date, item in dated if item_date <= target_date]
        return max(candidates, key=lambda item: item[0])[1] if candidates else None

    def _date_in_range(self, raw_date: str | None, start: date | None, end: date | None) -> bool:
        item_date = parse_date(raw_date)
        if item_date is None:
            return False
        if start and item_date < start:
            return False
        if end and item_date > end:
            return False
        return True
