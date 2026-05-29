from __future__ import annotations

from typing import Any

from app.services.trade_review_scoring import TradeReviewMetricsCalculator


POSITION_SIZE_LABELS = [
    ("none", 0.0),
    ("tiny", 0.02),
    ("small", 0.05),
    ("medium", 0.15),
    ("large", 0.30),
]


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class TradeDecisionMetricsCalculator:
    def __init__(self) -> None:
        self.review_metrics = TradeReviewMetricsCalculator()

    def calculate_cash_ratio(self, cash: float | None, net_liquidation: float | None) -> float | None:
        if cash is None or not net_liquidation:
            return None
        return round(cash / net_liquidation, 6)

    def calculate_unrealized_pnl_pct(self, unrealized_pnl: float | None, cost_basis: float | None) -> float | None:
        if unrealized_pnl is None or not cost_basis:
            return None
        return round(unrealized_pnl / abs(cost_basis), 6)

    def classify_position_pct(self, position_pct: float | None) -> str:
        if position_pct is None or position_pct <= 0:
            return "none"
        for label, threshold in POSITION_SIZE_LABELS[1:]:
            if position_pct < threshold:
                return label
        return "concentrated"

    def calculate_price_change(self, candles: list[dict], days: int) -> float | None:
        if not candles:
            return None
        end = candles[-1]
        start_index = max(0, len(candles) - days)
        start = candles[start_index]
        start_close = to_float(start.get("close"))
        end_close = to_float(end.get("close"))
        if not start_close or end_close is None:
            return None
        return round((end_close - start_close) / start_close, 6)

    def calculate_market_context(self, symbol_candles: list[dict], benchmark_candles: dict[str, list[dict]]) -> dict:
        changes = {
            "price_change_7d": self.calculate_price_change(symbol_candles, 7),
            "price_change_30d": self.calculate_price_change(symbol_candles, 30),
            "price_change_90d": self.calculate_price_change(symbol_candles, 90),
            "price_change_180d": self.calculate_price_change(symbol_candles, 180),
        }
        symbol_90d = changes["price_change_90d"]
        highs = [to_float(item.get("high")) for item in symbol_candles]
        lows = [to_float(item.get("low")) for item in symbol_candles]
        highs = [item for item in highs if item is not None]
        lows = [item for item in lows if item is not None]
        latest_close = to_float(symbol_candles[-1].get("close")) if symbol_candles else None
        period_high = max(highs) if highs else None
        period_low = min(lows) if lows else None

        context = {
            "source": "Longbridge public market data",
            **changes,
            "relative_to_spy_90d": self._relative_return(symbol_90d, benchmark_candles.get("SPY.US")),
            "relative_to_qqq_90d": self._relative_return(symbol_90d, benchmark_candles.get("QQQ.US")),
            "relative_to_smh_90d": self._relative_return(symbol_90d, benchmark_candles.get("SMH.US")),
            "period_high_180d": period_high,
            "period_low_180d": period_low,
            "distance_from_180d_high": round((latest_close - period_high) / period_high, 6) if latest_close is not None and period_high else None,
            "distance_from_180d_low": round((latest_close - period_low) / period_low, 6) if latest_close is not None and period_low else None,
        }
        return context

    def _relative_return(self, symbol_return: float | None, benchmark_candles: list[dict] | None) -> float | None:
        if symbol_return is None or not benchmark_candles:
            return None
        benchmark_return = self.calculate_price_change(benchmark_candles, 90)
        if benchmark_return is None:
            return None
        return round(symbol_return - benchmark_return, 6)
