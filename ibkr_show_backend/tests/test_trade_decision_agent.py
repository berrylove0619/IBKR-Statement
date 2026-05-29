"""Minimal test utilities for trade_decision_agent - V2 architecture."""
from dataclasses import dataclass


@dataclass
class DummySettings:
    es_trade_index: str = "trade-index"
    es_position_index: str = "position-index"
    es_account_index: str = "account-index"
    es_trade_review_index: str = "review-index"
    es_trade_decision_index: str = "decision-index"


class StubESClient:
    def search(self, index: str, body: dict) -> dict:
        if index == "account-index":
            return {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "account_id": "U1",
                                "report_date": "2026-05-01",
                                "currency": "USD",
                                "total_equity": 100000,
                                "cash": 15000,
                            }
                        }
                    ]
                }
            }
        if index == "position-index":
            return {"hits": {"hits": []}}
        return {"hits": {"hits": []}}


class StubLongbridgeClient:
    """Minimal stub for LongbridgeClient - V2 doesn't use it but tests need it."""
    def health(self) -> dict:
        return {"configured": False}

    def get_candlesticks(self, symbol: str, period: str = "day", start: str = "", end: str = "", adjust: str = "forward"):
        return {"items": []}

    def get_quote(self, symbol: str) -> dict | None:
        return None


def valid_decision_payload():
    return {
        "symbol": "AAPL",
        "decision_type": "entry_decision",
        "overall_score": 75,
        "rating": "BULLISH",
        "action": "buy",
        "confidence": "high",
        "decision_summary": "Strong buy signal based on technical and fundamental analysis.",
        "score_detail": {
            "account_fit": {"score": 18, "max_score": 20, "reason": "Good account fit"},
            "trend": {"score": 12, "max_score": 15, "reason": "Uptrend confirmed"},
            "fundamental": {"score": 28, "max_score": 35, "reason": "Healthy fundamentals"},
            "event": {"score": 4, "max_score": 5, "reason": "Positive catalyst"},
            "risk_reward": {"score": 12, "max_score": 15, "reason": "Favorable risk/reward"},
        },
        "position_advice": {
            "current_position_pct": 0.0,
            "suggested_target_position_pct": 0.05,
            "max_position_pct": 0.08,
            "suggested_cash_amount": 5000,
            "position_size_label": "medium",
        },
        "execution_plan": {
            "should_act_now": True,
            "plan": [
                {"action": "buy", "amount": 5000, "order_type": "market"},
            ],
            "invalid_conditions": [],
            "recheck_triggers": ["Price drops below $140", "Volume spikes"],
        },
        "key_reasons": ["Strong uptrend", "Healthy fundamentals", "Positive catalyst"],
        "major_risks": ["Market volatility", "Earnings risk"],
        "data_limitations": [],
        "evidence_used": ["price_data", "fundamental_data"],
        "created_at": "2026-05-21T10:00:00Z",
    }