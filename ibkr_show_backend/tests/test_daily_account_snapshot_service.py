import json
from unittest.mock import MagicMock

import pytest

from app.services.daily_account_snapshot_service import DailyAccountSnapshotService


class DummySettings:
    es_account_index = "ibkr_account"
    es_position_index = "ibkr_position"
    es_trade_index = "ibkr_trade"
    es_cash_flow_index = "ibkr_cash_flow"


class DummyESClient:
    def __init__(self):
        self.search_results = {}

    def search(self, index: str, body: dict):
        result = self.search_results.get(index, {"hits": {"hits": []}, "aggregations": {}})
        requested_size = body.get("size", 0)
        if requested_size and requested_size > 0:
            hits = result.get("hits", {}).get("hits", [])
            if len(hits) > requested_size:
                result = dict(result)
                result["hits"] = dict(result.get("hits", {}))
                result["hits"]["hits"] = hits[:requested_size]
        return result

    def set_search_result(self, index: str, result: dict):
        self.search_results[index] = result


class DummyDailyReviewService:
    def __init__(self):
        self.report_dates = []
        self.review_context = {}

    def list_report_dates(self, limit: int = 1):
        return self.report_dates[:limit]

    def build_review_context(self, report_date: str = None):
        if not report_date:
            report_date = self.report_dates[0] if self.report_dates else None
        if not report_date:
            raise ValueError("No IBKR account report date is available")
        return self.review_context.get(report_date, {
            "overview": {},
            "positions": [],
            "rankings": {},
            "risk": {},
            "data_quality": {},
        })


def _make_snapshot_service(es_client: DummyESClient, review_service: DummyDailyReviewService) -> DailyAccountSnapshotService:
    return DailyAccountSnapshotService(es_client, DummySettings(), review_service)


def test_build_snapshot_returns_schema_version():
    es_client = DummyESClient()
    review_service = DummyDailyReviewService()
    review_service.report_dates = ["2026-05-19"]
    review_service.review_context = {
        "2026-05-19": {
            "overview": {
                "report_date": "2026-05-19",
                "currency": "USD",
                "total_equity": 100000.0,
                "cash": 10000.0,
                "stock_value": 80000.0,
                "daily_pnl": 1500.0,
                "daily_return_percent": 1.5,
                "cash_ratio": 0.1,
            },
            "positions": [],
            "rankings": {"profit_contributors": [], "loss_drags": []},
            "risk": {},
            "data_quality": {"missing_fields": [], "warnings": []},
        }
    }
    es_client.set_search_result("ibkr_trade", {
        "hits": {"hits": [], "total": {"value": 0}},
        "aggregations": {"buy_count": {"doc_count": 0}, "sell_count": {"doc_count": 0}},
    })
    es_client.set_search_result("ibkr_cash_flow", {
        "hits": {"hits": [], "total": {"value": 0}},
        "aggregations": {"by_currency": {"buckets": []}},
    })

    service = _make_snapshot_service(es_client, review_service)
    snapshot = service.build_snapshot("2026-05-19")

    assert snapshot["schema_version"] == "daily_account_snapshot_v1"
    assert snapshot["data_scope"] == "single_report_date_only"
    assert snapshot["report_date"] == "2026-05-19"


def test_build_snapshot_account_fields():
    es_client = DummyESClient()
    review_service = DummyDailyReviewService()
    review_service.report_dates = ["2026-05-19"]
    review_service.review_context = {
        "2026-05-19": {
            "overview": {
                "report_date": "2026-05-19",
                "currency": "USD",
                "total_equity": 100000.0,
                "cash": 10000.0,
                "stock_value": 80000.0,
                "daily_pnl": 1500.0,
                "daily_return_percent": 1.5,
                "cash_ratio": 0.1,
            },
            "positions": [],
            "rankings": {"profit_contributors": [], "loss_drags": []},
            "risk": {},
            "data_quality": {"missing_fields": [], "warnings": []},
        }
    }
    es_client.set_search_result("ibkr_trade", {
        "hits": {"hits": [], "total": {"value": 0}},
        "aggregations": {},
    })
    es_client.set_search_result("ibkr_cash_flow", {
        "hits": {"hits": [], "total": {"value": 0}},
        "aggregations": {},
    })

    service = _make_snapshot_service(es_client, review_service)
    snapshot = service.build_snapshot("2026-05-19")

    account = snapshot["account"]
    assert account["report_date"] == "2026-05-19"
    assert account["currency"] == "USD"
    assert account["total_equity"] == 100000.0
    assert account["cash"] == 10000.0
    assert account["stock_value"] == 80000.0
    assert account["daily_pnl"] == 1500.0
    assert account["daily_return_percent"] == 1.5
    assert account["cash_ratio"] == 0.1


def test_build_snapshot_stock_value_falls_back_to_total_position_value():
    es_client = DummyESClient()
    review_service = DummyDailyReviewService()
    review_service.report_dates = ["2026-05-19"]
    review_service.review_context = {
        "2026-05-19": {
            "overview": {
                "report_date": "2026-05-19",
                "currency": "USD",
                "total_equity": 100000.0,
                "cash": 10000.0,
                "total_position_value": 80000.0,
                "daily_pnl": 1500.0,
                "daily_return_percent": 1.5,
                "cash_ratio": 0.1,
            },
            "positions": [],
            "rankings": {"profit_contributors": [], "loss_drags": []},
            "risk": {},
            "data_quality": {"missing_fields": [], "warnings": []},
        }
    }
    es_client.set_search_result("ibkr_trade", {
        "hits": {"hits": [], "total": {"value": 0}},
        "aggregations": {},
    })
    es_client.set_search_result("ibkr_cash_flow", {
        "hits": {"hits": [], "total": {"value": 0}},
        "aggregations": {},
    })

    service = _make_snapshot_service(es_client, review_service)
    snapshot = service.build_snapshot("2026-05-19")

    assert snapshot["account"]["stock_value"] == 80000.0


def test_build_snapshot_with_empty_trades_and_cash_flows():
    es_client = DummyESClient()
    review_service = DummyDailyReviewService()
    review_service.report_dates = ["2026-05-19"]
    review_service.review_context = {
        "2026-05-19": {
            "overview": {
                "report_date": "2026-05-19",
                "currency": "USD",
                "total_equity": 100000.0,
                "cash": 10000.0,
                "stock_value": 80000.0,
                "daily_pnl": 1500.0,
                "daily_return_percent": 1.5,
                "cash_ratio": 0.1,
            },
            "positions": [],
            "rankings": {"profit_contributors": [], "loss_drags": []},
            "risk": {},
            "data_quality": {"missing_fields": [], "warnings": []},
        }
    }
    es_client.set_search_result("ibkr_trade", {
        "hits": {"hits": [], "total": {"value": 0}},
        "aggregations": {"buy_count": {"doc_count": 0}, "sell_count": {"doc_count": 0}},
    })
    es_client.set_search_result("ibkr_cash_flow", {
        "hits": {"hits": [], "total": {"value": 0}},
        "aggregations": {"by_currency": {"buckets": []}},
    })

    service = _make_snapshot_service(es_client, review_service)
    snapshot = service.build_snapshot("2026-05-19")

    assert snapshot["trades_today"] == []
    assert snapshot["trades_truncated"] is False
    assert snapshot["trades_total_count"] == 0
    assert snapshot["trades_included_count"] == 0
    assert snapshot["cash_flows_today"] == []
    assert snapshot["cash_flows_truncated"] is False
    assert snapshot["cash_flows_total_count"] == 0
    assert snapshot["cash_flows_included_count"] == 0


def test_build_snapshot_trades_today_only():
    es_client = DummyESClient()
    review_service = DummyDailyReviewService()
    review_service.report_dates = ["2026-05-19"]
    review_service.review_context = {
        "2026-05-19": {
            "overview": {
                "report_date": "2026-05-19",
                "currency": "USD",
                "total_equity": 100000.0,
                "cash": 10000.0,
                "stock_value": 80000.0,
                "daily_pnl": 1500.0,
                "daily_return_percent": 1.5,
                "cash_ratio": 0.1,
            },
            "positions": [],
            "rankings": {"profit_contributors": [], "loss_drags": []},
            "risk": {},
            "data_quality": {"missing_fields": [], "warnings": []},
        }
    }
    es_client.set_search_result("ibkr_trade", {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "trade_date": "2026-05-19",
                        "date_time": "2026-05-19T10:00:00",
                        "symbol": "AMD",
                        "asset_class": "STOCK",
                        "buy_sell": "BUY",
                        "quantity": 100.0,
                        "trade_price": 120.0,
                        "proceeds": -12000.0,
                        "ib_commission": 0.5,
                        "net_cash": -12000.5,
                        "fifo_pnl_realized": 0.0,
                        "currency": "USD",
                        "transaction_id": "T1",
                        "trade_id": "TR1",
                    }
                }
            ],
            "total": {"value": 1},
        },
        "aggregations": {
            "buy_count": {"doc_count": 1},
            "sell_count": {"doc_count": 0},
        },
    })
    es_client.set_search_result("ibkr_cash_flow", {
        "hits": {"hits": [], "total": {"value": 0}},
        "aggregations": {"by_currency": {"buckets": []}},
    })

    service = _make_snapshot_service(es_client, review_service)
    snapshot = service.build_snapshot("2026-05-19")

    assert len(snapshot["trades_today"]) == 1
    assert snapshot["trades_today"][0]["symbol"] == "AMD"
    assert snapshot["trades_today"][0]["trade_date"] == "2026-05-19"
    assert snapshot["trades_truncated"] is False
    assert snapshot["trade_summary"]["trade_count"] == 1
    assert snapshot["trade_summary"]["buy_count"] == 1


def test_build_snapshot_trades_truncated_over_limit():
    es_client = DummyESClient()
    review_service = DummyDailyReviewService()
    review_service.report_dates = ["2026-05-19"]
    review_service.review_context = {
        "2026-05-19": {
            "overview": {
                "report_date": "2026-05-19",
                "currency": "USD",
                "total_equity": 100000.0,
                "cash": 10000.0,
                "stock_value": 80000.0,
                "daily_pnl": 1500.0,
                "daily_return_percent": 1.5,
                "cash_ratio": 0.1,
            },
            "positions": [],
            "rankings": {"profit_contributors": [], "loss_drags": []},
            "risk": {},
            "data_quality": {"missing_fields": [], "warnings": []},
        }
    }

    hits = []
    for i in range(55):
        hits.append({
            "_source": {
                "trade_date": "2026-05-19",
                "date_time": f"2026-05-19T10:{i:02d}:00",
                "symbol": f"SYM{i}",
                "asset_class": "STOCK",
                "buy_sell": "BUY",
                "quantity": 10.0,
                "trade_price": 100.0,
                "proceeds": -1000.0,
                "ib_commission": 0.1,
                "net_cash": -1000.1,
                "fifo_pnl_realized": 0.0,
                "currency": "USD",
                "transaction_id": f"T{i}",
                "trade_id": f"TR{i}",
            }
        })

    es_client.set_search_result("ibkr_trade", {
        "hits": {"hits": hits, "total": {"value": 55}},
        "aggregations": {
            "buy_count": {"doc_count": 55},
            "sell_count": {"doc_count": 0},
        },
    })
    es_client.set_search_result("ibkr_cash_flow", {
        "hits": {"hits": [], "total": {"value": 0}},
        "aggregations": {"by_currency": {"buckets": []}},
    })

    service = _make_snapshot_service(es_client, review_service)
    snapshot = service.build_snapshot("2026-05-19")

    assert len(snapshot["trades_today"]) == 50
    assert snapshot["trades_truncated"] is True
    assert snapshot["trades_total_count"] == 55
    assert snapshot["trades_included_count"] == 50
    assert snapshot["trade_summary"]["trade_count"] == 55


def test_build_snapshot_cash_flows_truncated_over_limit():
    es_client = DummyESClient()
    review_service = DummyDailyReviewService()
    review_service.report_dates = ["2026-05-19"]
    review_service.review_context = {
        "2026-05-19": {
            "overview": {
                "report_date": "2026-05-19",
                "currency": "USD",
                "total_equity": 100000.0,
                "cash": 10000.0,
                "stock_value": 80000.0,
                "daily_pnl": 1500.0,
                "daily_return_percent": 1.5,
                "cash_ratio": 0.1,
            },
            "positions": [],
            "rankings": {"profit_contributors": [], "loss_drags": []},
            "risk": {},
            "data_quality": {"missing_fields": [], "warnings": []},
        }
    }

    hits = []
    for i in range(55):
        hits.append({
            "_source": {
                "date_time": f"2026-05-19T10:{i:02d}:00",
                "report_date": "2026-05-19",
                "currency": "USD",
                "symbol": "",
                "description": f"Cash flow {i}",
                "amount": 100.0,
                "amount_in_base": 100.0,
                "flow_direction": "deposit",
                "flow_type": "Deposits/Withdrawals",
                "dividend_type": "",
                "transaction_id": f"CF{i}",
                "settle_date": "2026-05-20",
            }
        })

    es_client.set_search_result("ibkr_trade", {
        "hits": {"hits": [], "total": {"value": 0}},
        "aggregations": {"buy_count": {"doc_count": 0}, "sell_count": {"doc_count": 0}},
    })
    es_client.set_search_result("ibkr_cash_flow", {
        "hits": {"hits": hits, "total": {"value": 55}},
        "aggregations": {
            "by_currency": {
                "buckets": [
                    {
                        "key": "USD",
                        "deposit_total": {"amount": {"value": 5500.0}},
                        "withdrawal_total": {"amount": {"value": 0.0}},
                        "by_flow_type": {
                            "buckets": [
                                {"key": "Deposits/Withdrawals", "total_amount": {"value": 5500.0}}
                            ]
                        },
                    }
                ]
            }
        },
    })

    service = _make_snapshot_service(es_client, review_service)
    snapshot = service.build_snapshot("2026-05-19")

    assert len(snapshot["cash_flows_today"]) == 50
    assert snapshot["cash_flows_truncated"] is True
    assert snapshot["cash_flows_total_count"] == 55
    assert snapshot["cash_flows_included_count"] == 50
    assert snapshot["cash_flow_summary"]["record_count"] == 55


def test_build_snapshot_positions_included():
    es_client = DummyESClient()
    review_service = DummyDailyReviewService()
    review_service.report_dates = ["2026-05-19"]
    review_service.review_context = {
        "2026-05-19": {
            "overview": {
                "report_date": "2026-05-19",
                "currency": "USD",
                "total_equity": 100000.0,
                "cash": 10000.0,
                "stock_value": 80000.0,
                "daily_pnl": 1500.0,
                "daily_return_percent": 1.5,
                "cash_ratio": 0.1,
            },
            "positions": [
                {
                    "symbol": "AMD",
                    "name": "Advanced Micro Devices",
                    "asset_class": "STOCK",
                    "quantity": 100.0,
                    "mark_price": 120.0,
                    "market_value": 12000.0,
                    "weight": 0.12,
                    "daily_change_percent": 2.5,
                    "daily_pnl": 300.0,
                    "average_cost": 100.0,
                    "cost_basis": 10000.0,
                    "unrealized_pnl": 2000.0,
                    "unrealized_pnl_percent": 0.2,
                },
                {
                    "symbol": "NVDA",
                    "name": "NVIDIA",
                    "asset_class": "STOCK",
                    "quantity": 50.0,
                    "mark_price": 800.0,
                    "market_value": 40000.0,
                    "weight": 0.4,
                    "daily_change_percent": 3.0,
                    "daily_pnl": 1200.0,
                    "average_cost": 700.0,
                    "cost_basis": 35000.0,
                    "unrealized_pnl": 5000.0,
                    "unrealized_pnl_percent": 0.14,
                },
            ],
            "rankings": {
                "profit_contributors": [
                    {"symbol": "NVDA", "daily_pnl": 1200.0, "contribution_ratio": 0.8, "daily_change_percent": 3.0},
                    {"symbol": "AMD", "daily_pnl": 300.0, "contribution_ratio": 0.2, "daily_change_percent": 2.5},
                ],
                "loss_drags": [],
            },
            "risk": {
                "max_position": {"symbol": "NVDA", "weight": 0.4},
                "max_single_position_weight": 0.4,
                "top3_weight": 0.52,
                "top5_weight": 0.52,
                "cash_ratio": 0.1,
            },
            "data_quality": {"missing_fields": [], "warnings": []},
        }
    }
    es_client.set_search_result("ibkr_trade", {
        "hits": {"hits": [], "total": {"value": 0}},
        "aggregations": {"buy_count": {"doc_count": 0}, "sell_count": {"doc_count": 0}},
    })
    es_client.set_search_result("ibkr_cash_flow", {
        "hits": {"hits": [], "total": {"value": 0}},
        "aggregations": {"by_currency": {"buckets": []}},
    })

    service = _make_snapshot_service(es_client, review_service)
    snapshot = service.build_snapshot("2026-05-19")

    assert len(snapshot["positions"]) == 2
    assert len(snapshot["top_positions"]) == 2
    assert snapshot["top_positions"][0]["symbol"] == "NVDA"
    assert snapshot["top_positions"][1]["symbol"] == "AMD"
    assert len(snapshot["top_contributors"]) == 2
    assert snapshot["top_contributors"][0]["symbol"] == "NVDA"


def test_build_snapshot_no_report_date_raises():
    es_client = DummyESClient()
    review_service = DummyDailyReviewService()
    review_service.report_dates = []

    service = _make_snapshot_service(es_client, review_service)

    with pytest.raises(ValueError, match="No IBKR account report date is available"):
        service.build_snapshot()


def test_build_snapshot_excludes_sensitive_fields_recursively():
    es_client = DummyESClient()
    review_service = DummyDailyReviewService()
    review_service.report_dates = ["2026-05-19"]
    review_service.review_context = {
        "2026-05-19": {
            "overview": {
                "report_date": "2026-05-19",
                "currency": "USD",
                "total_equity": 100000.0,
                "cash": 10000.0,
                "stock_value": 80000.0,
                "daily_pnl": 1500.0,
                "daily_return_percent": 1.5,
                "cash_ratio": 0.1,
            },
            "positions": [
                {"symbol": "AMD", "name": "secret_position", "flex_token": "token-123", "daily_pnl": 100.0}
            ],
            "rankings": {"profit_contributors": [], "loss_drags": []},
            "risk": {
                "max_position": {"symbol": "AMD", "weight": 0.4},
                "max_single_position_weight": 0.4,
                "top3_weight": 0.52,
                "top5_weight": 0.52,
                "cash_ratio": 0.1,
                "flex_token": "secret-token",
                "llm_api_key": "sk-secret",
                "nested": {
                    "api_key": "should-be-removed",
                    "smtp_password": "secret",
                },
                "list_items": [
                    {"token": "in-list"},
                    {"password": "also-removed"},
                ],
            },
            "data_quality": {
                "missing_fields": [],
                "warnings": [],
                "api_key_secret": "also-removed",
            },
        }
    }
    es_client.set_search_result("ibkr_trade", {
        "hits": {"hits": [], "total": {"value": 0}},
        "aggregations": {"buy_count": {"doc_count": 0}, "sell_count": {"doc_count": 0}},
    })
    es_client.set_search_result("ibkr_cash_flow", {
        "hits": {"hits": [], "total": {"value": 0}},
        "aggregations": {"by_currency": {"buckets": []}},
    })

    service = _make_snapshot_service(es_client, review_service)
    snapshot = service.build_snapshot("2026-05-19")

    snapshot_json = json.dumps(snapshot, ensure_ascii=False)

    assert "flex_token" not in snapshot_json
    assert "llm_api_key" not in snapshot_json
    assert "smtp_password" not in snapshot_json
    assert "api_key_secret" not in snapshot_json
    assert "token-123" not in snapshot_json
    assert "secret" not in snapshot_json.lower() or "secret_position" in snapshot_json

    risk = snapshot["risk"]
    assert "flex_token" not in risk
    assert "llm_api_key" not in risk
    assert "nested" not in risk or "api_key" not in str(risk.get("nested", {}))


def test_trade_summary_based_on_aggregations_not_50_items():
    es_client = DummyESClient()
    review_service = DummyDailyReviewService()
    review_service.report_dates = ["2026-05-19"]
    review_service.review_context = {
        "2026-05-19": {
            "overview": {
                "report_date": "2026-05-19",
                "currency": "USD",
                "total_equity": 100000.0,
                "cash": 10000.0,
                "stock_value": 80000.0,
                "daily_pnl": 1500.0,
                "daily_return_percent": 1.5,
                "cash_ratio": 0.1,
            },
            "positions": [],
            "rankings": {"profit_contributors": [], "loss_drags": []},
            "risk": {},
            "data_quality": {"missing_fields": [], "warnings": []},
        }
    }

    es_client.set_search_result("ibkr_trade", {
        "hits": {"hits": [{"_source": {"trade_date": "2026-05-19", "symbol": "A", "buy_sell": "BUY", "ib_commission": 0.1}}], "total": {"value": 100}},
        "aggregations": {
            "buy_count": {"doc_count": 80},
            "sell_count": {"doc_count": 20},
            "total_commission": {"value": 5.5},
            "total_realized_pnl": {"value": 1200.0},
            "total_proceeds": {"value": -50000.0},
            "symbols_count": {"value": 10},
        },
    })
    es_client.set_search_result("ibkr_cash_flow", {
        "hits": {"hits": [], "total": {"value": 0}},
        "aggregations": {"by_currency": {"buckets": []}},
    })

    service = _make_snapshot_service(es_client, review_service)
    snapshot = service.build_snapshot("2026-05-19")

    assert snapshot["trade_summary"]["trade_count"] == 100
    assert snapshot["trade_summary"]["buy_count"] == 80
    assert snapshot["trade_summary"]["sell_count"] == 20
    assert snapshot["trade_summary"]["total_commission"] == 5.5
    assert snapshot["trade_summary"]["total_realized_pnl"] == 1200.0
    assert snapshot["trade_summary"]["symbols_count"] == 10
    assert len(snapshot["trades_today"]) == 1
    assert snapshot["trades_truncated"] is True
    assert snapshot["trades_total_count"] == 100


def test_cash_flow_summary_includes_raw_flow_type_summary():
    es_client = DummyESClient()
    review_service = DummyDailyReviewService()
    review_service.report_dates = ["2026-05-19"]
    review_service.review_context = {
        "2026-05-19": {
            "overview": {
                "report_date": "2026-05-19",
                "currency": "USD",
                "total_equity": 100000.0,
                "cash": 10000.0,
                "stock_value": 80000.0,
                "daily_pnl": 1500.0,
                "daily_return_percent": 1.5,
                "cash_ratio": 0.1,
            },
            "positions": [],
            "rankings": {"profit_contributors": [], "loss_drags": []},
            "risk": {},
            "data_quality": {"missing_fields": [], "warnings": []},
        }
    }

    es_client.set_search_result("ibkr_trade", {
        "hits": {"hits": [], "total": {"value": 0}},
        "aggregations": {"buy_count": {"doc_count": 0}, "sell_count": {"doc_count": 0}},
    })
    es_client.set_search_result("ibkr_cash_flow", {
        "hits": {"hits": [{"_source": {"date_time": "2026-05-19T10:00:00", "report_date": "2026-05-19", "currency": "USD", "amount": 100.0, "flow_direction": "deposit", "flow_type": "Dividend"}}], "total": {"value": 10}},
        "aggregations": {
            "by_currency": {
                "buckets": [
                    {
                        "key": "USD",
                        "deposit_total": {"amount": {"value": 150.0}},
                        "withdrawal_total": {"amount": {"value": 50.0}},
                        "by_flow_type": {
                            "buckets": [
                                {"key": "Dividend", "total_amount": {"value": 100.0}},
                                {"key": "Deposits/Withdrawals", "total_amount": {"value": 50.0}},
                            ]
                        },
                    }
                ]
            }
        },
    })

    service = _make_snapshot_service(es_client, review_service)
    snapshot = service.build_snapshot("2026-05-19")

    assert "raw_flow_type_summary" in snapshot["cash_flow_summary"]
    assert "Dividend" in snapshot["cash_flow_summary"]["raw_flow_type_summary"]
    assert snapshot["cash_flow_summary"]["total_dividend"] == 100.0