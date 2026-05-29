#!/usr/bin/env python3
"""API-level E2E contract smoke check for P0-P3 agents.

This script intentionally avoids logging passwords. By default it runs in
--no-write mode and checks health/detail contracts only. Generation endpoints
are called only when --no-write is omitted and the required symbol/date/trade
arguments are provided.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


HEALTH_ENDPOINTS = {
    "P0_trade_decision": "/api/agent/trade-decision/health",
    "P1_risk_assessment": "/api/agent/risk-assessment/health",
    "P2_daily_position_review": "/api/agent/daily-position-review/health",
    "P3_trade_review": "/api/agent/trade-review/health",
}


EXPECTED = {
    "P0_trade_decision": ("trade_decision_langgraph_v1", "trade_decision_graph_v1"),
    "P1_risk_assessment": ("risk_assessment_langgraph_v1", "risk_assessment_graph_v1"),
    "P2_daily_position_review": ("daily_position_review_langgraph_v1", "daily_position_review_graph_v1"),
    "P3_trade_review": ("trade_review_langgraph_v1", "trade_review_graph_v1"),
}


def _url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def _safe_json(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {"raw": response.text[:500]}
    return payload if isinstance(payload, dict) else {"items": payload}


def _summarize_health(agent: str, endpoint: str, status_code: int, payload: dict[str, Any]) -> dict[str, Any]:
    expected_mode, expected_graph = EXPECTED[agent]
    metadata_ok = payload.get("agent_mode") == expected_mode and payload.get("graph_version") == expected_graph
    return {
        "agent": agent,
        "endpoint": endpoint,
        "http": status_code,
        "agent_mode": payload.get("agent_mode"),
        "graph_version": payload.get("graph_version"),
        "llm_configured": payload.get("llm_configured"),
        "mcp_available": payload.get("mcp_available"),
        "public_data_mode": payload.get("public_data_mode"),
        "account_data_source": payload.get("account_data_source"),
        "public_market_data_source": payload.get("public_market_data_source"),
        "ok": status_code < 400 and metadata_ok,
        "message": payload.get("message"),
    }


def _contract_flags(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata") or {}
    run_trace = payload.get("run_trace") or []
    card_pack = payload.get("card_pack") or payload.get("subagent_card_pack") or {}
    return {
        "id": payload.get("id"),
        "agent_mode": metadata.get("agent_mode"),
        "graph_version": metadata.get("graph_version"),
        "fallback_used": payload.get("fallback_used") or metadata.get("fallback_used"),
        "fallback_reason": payload.get("fallback_reason") or metadata.get("fallback_reason"),
        "run_trace_count": len(run_trace) if isinstance(run_trace, list) else 0,
        "card_pack_present": bool(card_pack),
        "evidence_pack_present": bool(payload.get("evidence_pack")),
        "evidence_summary_present": bool(payload.get("evidence_summary")),
        "data_limitations": payload.get("data_limitations") or [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--cookie")
    parser.add_argument("--no-write", action="store_true", default=False)
    parser.add_argument("--entry-symbol", default="")
    parser.add_argument("--holding-symbol", default="")
    parser.add_argument("--daily-date", default="")
    parser.add_argument("--trade-symbol", default="")
    parser.add_argument("--trade-id", default="")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    parser.add_argument("--out-json", default="agent_contract_report.json")
    parser.add_argument("--out-md", default="agent_contract_report.md")
    args = parser.parse_args()

    session = requests.Session()
    if args.cookie:
        session.headers.update({"Cookie": args.cookie})
    elif args.username and args.password:
        response = session.post(
            _url(args.base_url, "/api/auth/login"),
            json={"username": args.username, "password": args.password},
            timeout=30,
        )
        if response.status_code >= 400:
            raise SystemExit(f"login failed: HTTP {response.status_code}")
    else:
        raise SystemExit("provide --cookie or --username/--password")

    report: dict[str, Any] = {
        "base_url": args.base_url,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "no_write": args.no_write,
        "health": [],
        "generation": [],
    }

    for agent, endpoint in HEALTH_ENDPOINTS.items():
        response = session.get(_url(args.base_url, endpoint), timeout=30)
        payload = _safe_json(response)
        report["health"].append(_summarize_health(agent, endpoint, response.status_code, payload))

    generation_calls: list[tuple[str, str, str, dict[str, Any]]] = []
    if not args.no_write:
        if args.entry_symbol:
            generation_calls.append(("P0_entry", "POST", "/api/agent/trade-decision/entry/analyze", {"symbol": args.entry_symbol}))
        if args.holding_symbol:
            generation_calls.append(("P0_holding", "POST", f"/api/agent/trade-decision/holding/{args.holding_symbol}/analyze", {}))
        generation_calls.append(("P1_risk", "POST", "/api/agent/risk-assessment/tasks", {}))
        if args.daily_date:
            generation_calls.append(("P2_daily", "POST", f"/api/agent/daily-position-review/{args.daily_date}/generate", {}))
        if args.trade_symbol:
            generation_calls.append(
                (
                    "P3_symbol",
                    "POST",
                    f"/api/agent/trade-review/symbol/{args.trade_symbol}/generate",
                    {"start_date": args.start_date or None, "end_date": args.end_date or None},
                )
            )
        if args.trade_id:
            generation_calls.append(("P3_single_trade", "POST", f"/api/agent/trade-review/trade/{args.trade_id}/generate", {}))

    for name, method, endpoint, body in generation_calls:
        response = session.request(method, _url(args.base_url, endpoint), json=body, timeout=180)
        payload = _safe_json(response)
        report["generation"].append(
            {
                "name": name,
                "endpoint": endpoint,
                "http": response.status_code,
                **_contract_flags(payload),
            }
        )

    Path(args.out_json).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    health_rows = [
        "| Agent | endpoint | HTTP | agent_mode | graph_version | MCP | public_data_mode | ok |",
        "|---|---|---:|---|---|---|---|---|",
    ]
    for item in report["health"]:
        health_rows.append(
            f"| {item['agent']} | `{item['endpoint']}` | {item['http']} | {item.get('agent_mode')} | "
            f"{item.get('graph_version')} | {item.get('mcp_available')} | {item.get('public_data_mode')} | {item.get('ok')} |"
        )
    md = "# Agent Contract Check\n\n" + "\n".join(health_rows) + "\n"
    if report["generation"]:
        md += "\n## Generation\n\n```json\n" + json.dumps(report["generation"], ensure_ascii=False, indent=2) + "\n```\n"
    Path(args.out_md).write_text(md, encoding="utf-8")
    print(f"wrote {args.out_json} and {args.out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
