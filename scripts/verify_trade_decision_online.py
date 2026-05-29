#!/usr/bin/env python3
"""Online verification for the trade decision runtime.

Environment:
  ONLINE_BASE_URL       default https://your-domain.example
  ONLINE_AUTH_COOKIE    optional raw Cookie header
  ONLINE_AUTH_TOKEN     optional bearer token
  ONLINE_USERNAME       optional login username when no cookie/token is provided
                        falls back to common .env admin/auth username names
  ONLINE_PASSWORD       optional login password when no cookie/token is provided
                        falls back to common .env admin/auth password names
  VERIFY_SYMBOLS        comma-separated symbols, default TC.US,NVDA.US
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


def load_dotenv_file(path: Path) -> None:
    """Load simple KEY=VALUE entries without requiring shell-compatible .env syntax."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not (key[0].isalpha() or key[0] == "_"):
            continue
        if not all(char.isalnum() or char == "_" for char in key):
            continue
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_dotenv_file(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = os.environ.get("ONLINE_BASE_URL", "https://your-domain.example").rstrip("/")
API_BASE = BASE_URL if BASE_URL.endswith("/api") else f"{BASE_URL}/api"
BAD_USER_VISIBLE_TERMS = ("Agent exceeded max_rounds", "subagent_failed", "mcp_field_missing", "1970-01-01", "Traceback")


def request_json(path: str, *, method: str = "GET", body: dict[str, Any] | None = None, auth: dict[str, str]) -> dict[str, Any]:
    headers = {"Content-Type": "application/json", **auth}
    data = json.dumps(body or {}).encode() if body is not None else None
    req = Request(f"{API_BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace") if exc.fp else ""
        raise RuntimeError(f"HTTP {exc.code} {path}: {detail[:500]}") from exc


def login() -> dict[str, str]:
    cookie = os.environ.get("ONLINE_AUTH_COOKIE")
    if cookie:
        return {"Cookie": cookie}
    token = os.environ.get("ONLINE_AUTH_TOKEN")
    if token:
        return {"Authorization": f"Bearer {token}"}
    username = _first_env(
        "ONLINE_USERNAME",
        "REMOTE_AUTH_USERNAME",
        "ADMIN_USERNAME",
        "ADMIN_USER",
        "AUTH_USERNAME",
        "AUTH_USER",
        "IBKR_SHOW_USERNAME",
    )
    password = _first_env("ONLINE_PASSWORD", "REMOTE_AUTH_PASSWORD", "ADMIN_PASSWORD", "AUTH_PASSWORD", "IBKR_SHOW_PASSWORD")
    if not username or not password:
        raise RuntimeError("Set ONLINE_AUTH_COOKIE, ONLINE_AUTH_TOKEN, or ONLINE_USERNAME/ONLINE_PASSWORD")
    data = json.dumps({"username": username, "password": password}).encode()
    req = Request(f"{API_BASE}/auth/login", data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=60) as resp:
        cookies = resp.headers.get_all("Set-Cookie") or []
    cookie_header = "; ".join(cookie_item.split(";")[0] for cookie_item in cookies)
    if not cookie_header:
        raise RuntimeError("Login succeeded but no auth cookie was returned")
    return {"Cookie": cookie_header}


def _first_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


def list_holding_symbols(auth: dict[str, str]) -> list[str]:
    try:
        payload = request_json("/agent/trade-decision/holdings", auth=auth)
    except Exception as exc:  # pragma: no cover - online diagnostic only
        print(f"warning: failed to load holdings for online verification: {exc}")
        return []
    items = payload.get("items") or []
    symbols: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("normalized_symbol") or item.get("symbol") or "").strip().upper()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols


def choose_test_cases(symbols: list[str], holding_symbols: list[str]) -> list[tuple[str, str]]:
    entry_symbol = symbols[0]
    explicit_holding = next((symbol for symbol in symbols[1:] if symbol in holding_symbols), "")
    holding_symbol = explicit_holding or (holding_symbols[0] if holding_symbols else (symbols[1] if len(symbols) > 1 else symbols[0]))
    if not explicit_holding and holding_symbols:
        print(f"using online holding symbol for holding_decision: {holding_symbol}")
    elif not holding_symbols:
        print(f"warning: no online holdings returned; falling back to configured holding symbol: {holding_symbol}")
    return [(entry_symbol, "entry_decision"), (holding_symbol, "holding_decision")]


def start_task(symbol: str, decision_type: str, auth: dict[str, str]) -> dict[str, Any]:
    if decision_type == "holding_decision":
        return request_json(
            f"/agent/trade-decision/holding/{quote(symbol)}/tasks",
            method="POST",
            body={"question": f"线上验证：评估 {symbol} 持仓，重点检查新闻事件和数据限制。"},
            auth=auth,
        )
    return request_json(
        "/agent/trade-decision/entry/tasks",
        method="POST",
        body={"symbol": symbol, "question": f"线上验证：评估 {symbol} 建仓，重点检查新闻事件和数据限制。"},
        auth=auth,
    )


def poll_task(task_id: str, auth: dict[str, str], *, timeout_seconds: int = 360) -> dict[str, Any]:
    started = time.time()
    transient_errors = 0
    while time.time() - started < timeout_seconds:
        try:
            task = request_json(f"/agent/trade-decision/tasks/{quote(task_id)}", auth=auth)
        except RuntimeError as exc:
            message = str(exc)
            if any(code in message for code in ("HTTP 502", "HTTP 503", "HTTP 504")):
                transient_errors += 1
                print(f"warning: transient task poll error for {task_id}: {message[:120]}")
                time.sleep(5)
                continue
            raise
        status = task.get("status")
        if status in {"completed", "failed"}:
            return task
        time.sleep(5)
    raise RuntimeError(f"Task {task_id} did not finish within {timeout_seconds}s")


def fetch_result(result_id: str, auth: dict[str, str]) -> dict[str, Any]:
    return request_json(f"/agent/trade-decision/{quote(result_id)}", auth=auth)


def assert_clean_user_visible(result: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    result_id = result.get("id", "unknown")
    visible_payload = {
        "decision_summary": result.get("decision_summary"),
        "key_reasons": result.get("key_reasons"),
        "major_risks": result.get("major_risks"),
        "review_warnings": result.get("review_warnings"),
        "data_limitations": result.get("data_limitations"),
        "card_pack": _card_public_fields(result.get("card_pack") or {}),
    }
    visible_text = json.dumps(visible_payload, ensure_ascii=False, default=str)
    for term in BAD_USER_VISIBLE_TERMS:
        if term in visible_text:
            failures.append(f"[{result_id}] user-visible payload contains forbidden term: {term}")

    card_pack = result.get("card_pack") or {}
    market_card = card_pack.get("market_trend_card") or {}
    event_card = card_pack.get("event_catalyst_card") or {}
    if market_card.get("data_limitations") and any("max_rounds=2" in str(item) for item in market_card.get("data_limitations") or []):
        failures.append(f"[{result_id}] market_trend still exposes max_rounds=2")
    event_limitations = " ".join(str(item) for item in (event_card.get("data_limitations") or []))
    if "1970-01-01" in event_limitations:
        failures.append(f"[{result_id}] event_catalyst exposes 1970-01-01")
    if not result.get("run_trace"):
        failures.append(f"[{result_id}] run_trace is empty")
    return failures


def _card_public_fields(card_pack: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, card in card_pack.items():
        if isinstance(card, dict):
            output[key] = {
                "summary": card.get("summary"),
                "data_limitations": card.get("data_limitations"),
                "key_events": card.get("key_events"),
                "risk_events": card.get("risk_events"),
            }
    return output


def main() -> int:
    auth = login()
    health = request_json("/agent/trade-decision/health", auth=auth)
    print("health:", json.dumps({
        "llm_configured": health.get("llm_configured"),
        "longbridge_configured": health.get("longbridge_configured"),
        "mcp_auth_status": health.get("mcp_auth_status"),
    }, ensure_ascii=False))

    symbols = [item.strip().upper() for item in os.environ.get("VERIFY_SYMBOLS", "TC.US,NVDA.US").split(",") if item.strip()]
    if not symbols:
        raise RuntimeError("VERIFY_SYMBOLS produced no symbols")
    test_cases = choose_test_cases(symbols, list_holding_symbols(auth))
    failures: list[str] = []
    result_ids: list[str] = []

    for symbol, decision_type in test_cases:
        print(f"\nstarting {decision_type} task for {symbol}")
        task = start_task(symbol, decision_type, auth)
        task_id = task["id"]
        print(f"task_id={task_id}")
        finished = poll_task(task_id, auth)
        if finished.get("status") != "completed":
            failures.append(f"{symbol} task failed: {finished.get('error_code')} {finished.get('error_message')}")
            continue
        result_id = finished.get("result_id")
        print(f"result_id={result_id}")
        if not result_id:
            failures.append(f"{symbol} completed without result_id")
            continue
        result = fetch_result(result_id, auth)
        result_ids.append(result_id)
        print(
            json.dumps(
                {
                    "symbol": result.get("symbol"),
                    "action": result.get("action"),
                    "confidence": result.get("confidence"),
                    "data_limitations": result.get("data_limitations"),
                    "tool_call_count": (result.get("run_trace_summary") or {}).get("tool_call_count"),
                },
                ensure_ascii=False,
            )
        )
        failures.extend(assert_clean_user_visible(result))

    print("\nverification_result_ids:", ",".join(result_ids))
    if failures:
        print("FAILURES:")
        for failure in failures:
            print("-", failure)
        return 1
    print("ONLINE TRADE DECISION VERIFICATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
