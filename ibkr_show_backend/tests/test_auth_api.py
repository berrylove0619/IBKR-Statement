from fastapi.testclient import TestClient

from app.api.deps import get_trade_service
from app.core.config import get_settings
from app.main import app
from app.schemas.common import PaginationInfo
from app.schemas.trades import TradeItem, TradeListResponse, TradeSummaryResponse


class DummyTradeService:
    def list_trades(self, **_: object) -> TradeListResponse:
        return TradeListResponse(
            items=[TradeItem(account_id="U1", trade_date="2026-04-17", symbol="AAPL")],
            pagination=PaginationInfo(page=1, page_size=20, total=1, total_pages=1),
        )

    def summarize_trades(self, **_: object) -> TradeSummaryResponse:
        return TradeSummaryResponse(
            trade_count=1,
            buy_count=1,
            sell_count=0,
            total_commission=1.0,
            total_realized_pnl=2.0,
            total_proceeds=3.0,
            symbols_count=1,
        )


client = TestClient(app)


def test_auth_session_defaults_to_guest() -> None:
    response = client.get("/api/auth/session")

    assert response.status_code == 200
    assert response.json() == {"authenticated": False, "username": None}


def test_protected_trade_routes_require_login() -> None:
    app.dependency_overrides[get_trade_service] = DummyTradeService

    try:
        list_response = client.get("/api/trades")
        summary_response = client.get("/api/trades/summary")
    finally:
        app.dependency_overrides.clear()

    assert list_response.status_code == 401
    assert list_response.json()["detail"] == "请先登录后查看该模块"
    assert summary_response.status_code == 401
    assert summary_response.json()["detail"] == "请先登录后查看该模块"


def test_login_sets_cookie_and_unlocks_trade_routes() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    app.dependency_overrides[get_trade_service] = DummyTradeService

    try:
        login_response = client.post(
            "/api/auth/login",
            json={"username": settings.auth_username, "password": settings.auth_password},
        )
        trade_response = client.get("/api/trades")
        session_response = client.get("/api/auth/session")
        logout_response = client.post("/api/auth/logout")
        post_logout_trade_response = client.get("/api/trades")
    finally:
        app.dependency_overrides.clear()

    assert login_response.status_code == 200
    assert login_response.json() == {"authenticated": True, "username": settings.auth_username}
    assert "ibkr_show_session" in login_response.headers.get("set-cookie", "")

    assert trade_response.status_code == 200
    assert trade_response.json()["pagination"]["total"] == 1

    assert session_response.status_code == 200
    assert session_response.json() == {"authenticated": True, "username": settings.auth_username}

    assert logout_response.status_code == 200
    assert logout_response.json() == {"authenticated": False, "username": None}
    assert post_logout_trade_response.status_code == 401


def test_login_rejects_invalid_credentials() -> None:
    response = client.post(
        "/api/auth/login",
        json={"username": "wrong", "password": "wrong"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "用户名或密码错误"
