#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "ibkr_show_backend"
sys.path.insert(0, str(BACKEND))

SENSITIVE_RE = re.compile(r"(token|access_token|refresh_token|authorization|api_key|secret|password|cookie)", re.I)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("***REDACTED***" if SENSITIVE_RE.search(str(key)) else redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return SENSITIVE_RE.sub("[redacted_key]", value)
    return value


class HttpProbeClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def login(self) -> None:
        cookie = os.getenv("ACCOUNT_COPILOT_SESSION_COOKIE")
        if cookie:
            self.session.headers.update({"Cookie": cookie})
            return
        username = os.getenv("ACCOUNT_COPILOT_USERNAME")
        password = os.getenv("ACCOUNT_COPILOT_PASSWORD")
        if not username or not password:
            raise SystemExit("Missing ACCOUNT_COPILOT_USERNAME/PASSWORD or ACCOUNT_COPILOT_SESSION_COOKIE.")
        response = self.session.post(f"{self.base_url}/api/auth/login", json={"username": username, "password": password}, timeout=60)
        if response.status_code >= 400:
            raise SystemExit(f"Login failed: HTTP {response.status_code}")

    def run_probe(self, payload: dict) -> dict:
        response = self.session.post(f"{self.base_url}/api/agent/account-copilot/tool-reliability/probe", json=payload, timeout=300)
        if response.status_code >= 400:
            raise RuntimeError(f"Probe failed: HTTP {response.status_code} {response.text[:300]}")
        return response.json()


def run_local_probe(args: argparse.Namespace) -> dict:
    from app.agents.account_copilot.skill_registry import build_default_skill_registry
    from app.agents.account_copilot.tool_registry import build_default_tool_registry
    from app.services.account_copilot.tool_reliability_service import AccountCopilotToolReliabilityService

    class _FakeIBKRService:
        def __getattr__(self, name: str):
            def _handler(**kwargs):
                return {
                    "ok": False,
                    "tool": name,
                    "arguments": kwargs,
                    "data": {},
                    "data_source": "LOCAL_DRY_RUN",
                    "data_limitations": ["Local dry-run does not invoke live IBKR data."],
                    "error_code": "LOCAL_DRY_RUN",
                }
            return _handler

    class _FakeLongbridgeService:
        def list_public_tool_categories(self, **kwargs):
            return {"ok": False, "tool": "longbridge_list_public_tool_categories", "arguments": kwargs, "data": {}, "data_source": "LOCAL_DRY_RUN", "data_limitations": ["Local dry-run does not invoke Longbridge MCP."]}

        def list_public_tools(self, **kwargs):
            return {"ok": False, "tool": "longbridge_list_public_tools", "arguments": kwargs, "data": {}, "data_source": "LOCAL_DRY_RUN", "data_limitations": ["Local dry-run does not invoke Longbridge MCP."]}

        def get_public_tool_schema(self, **kwargs):
            return {"ok": False, "tool": "longbridge_get_public_tool_schema", "arguments": kwargs, "data": {}, "data_source": "LOCAL_DRY_RUN", "data_limitations": ["Local dry-run does not invoke Longbridge MCP."]}

        def get_public_tool_schemas(self, **kwargs):
            return {"ok": False, "tool": "longbridge_get_public_tool_schemas", "arguments": kwargs, "data": {}, "data_source": "LOCAL_DRY_RUN", "data_limitations": ["Local dry-run does not invoke Longbridge MCP."]}

        def call_public_tool(self, **kwargs):
            return {"ok": False, "tool": "longbridge_call_public_tool", "arguments": kwargs, "data": {}, "data_source": "LOCAL_DRY_RUN", "data_limitations": ["Local dry-run does not invoke Longbridge MCP."]}

        def call_public_tools(self, **kwargs):
            return {"ok": False, "tool": "longbridge_call_public_tools", "arguments": kwargs, "data": {}, "data_source": "LOCAL_DRY_RUN", "data_limitations": ["Local dry-run does not invoke Longbridge MCP."]}

    service = AccountCopilotToolReliabilityService(
        repository=None,
        tool_registry=build_default_tool_registry(_FakeIBKRService(), _FakeLongbridgeService()),
        skill_registry=build_default_skill_registry(),
        longbridge_adapter=None,
    )
    return service.run_probe(
        include_ibkr_live=False,
        include_longbridge_live=False,
        include_agent_eval=args.include_agent_eval,
        symbol=args.symbol,
        keyword=args.keyword,
        max_tools=args.max_tools,
        persist=False,
    )


def summarize_by_domain(results: list[dict]) -> list[dict]:
    domains = sorted({result.get("tool_domain") or "unknown" for result in results})
    rows = []
    for domain in domains:
        items = [result for result in results if (result.get("tool_domain") or "unknown") == domain]
        latencies = [int(item.get("latency_ms") or 0) for item in items if int(item.get("latency_ms") or 0) > 0]
        passed = len([item for item in items if item.get("status") == "pass"])
        rows.append(
            {
                "domain": domain,
                "total": len(items),
                "pass": passed,
                "fail": len([item for item in items if item.get("status") == "fail"]),
                "partial": len([item for item in items if item.get("status") == "partial"]),
                "skipped": len([item for item in items if item.get("status") == "skipped"]),
                "success_rate": round(passed / len(items) * 100, 1) if items else 0,
                "p95_latency_ms": percentile(latencies, 0.95),
            }
        )
    return rows


def normalize_report_statuses(report: dict) -> dict:
    results = report.get("results") or []
    for result in results:
        if result.get("error_code") == "LONGBRIDGE_ADAPTER_UNAVAILABLE":
            result["status"] = "fail"
            result["ok"] = False
    report["summary"] = summarize_results(results)
    return report


def summarize_results(results: list[dict]) -> dict:
    latencies = [int(item.get("latency_ms") or 0) for item in results if int(item.get("latency_ms") or 0) > 0]
    statuses = ("pass", "fail", "partial", "skipped")
    counts = {status: len([item for item in results if item.get("status") == status]) for status in statuses}
    return {
        "total_tools": len({item.get("tool_name") for item in results}),
        "total_results": len(results),
        **{f"{status}_count": count for status, count in counts.items()},
        "avg_latency_ms": int(mean(latencies)) if latencies else 0,
        "p95_latency_ms": percentile(latencies, 0.95),
    }


def percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * pct))))]


def render_report(report: dict, path: Path, started_at: str, finished_at: str) -> None:
    results = report.get("results") or []
    summary = report.get("summary") or {}
    domain_rows = summarize_by_domain(results)
    latencies = [int(item.get("latency_ms") or 0) for item in results if int(item.get("latency_ms") or 0) > 0]
    lines = [
        "# Account Copilot Tool Reliability Report",
        "",
        "## Summary",
        f"- probe_run_id: `{report.get('probe_run_id')}`",
        f"- started_at: `{started_at}`",
        f"- finished_at: `{finished_at}`",
        f"- total_tools: `{summary.get('total_tools', 0)}`",
        f"- pass_count: `{summary.get('pass_count', 0)}`",
        f"- fail_count: `{summary.get('fail_count', 0)}`",
        f"- partial_count: `{summary.get('partial_count', 0)}`",
        f"- skipped_count: `{summary.get('skipped_count', 0)}`",
        f"- avg_latency_ms: `{int(mean(latencies)) if latencies else 0}`",
        f"- p95_latency_ms: `{percentile(latencies, 0.95)}`",
        "",
        "## Domain Summary",
        "| Domain | Total | Pass | Fail | Partial | Skipped | Success Rate | P95 Latency |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in domain_rows:
        lines.append(f"| {row['domain']} | {row['total']} | {row['pass']} | {row['fail']} | {row['partial']} | {row['skipped']} | {row['success_rate']}% | {row['p95_latency_ms']} |")
    lines.extend(["", "## Tool Results", "| Tool | Domain | Probe Type | Status | Latency | Error | Notes |", "|---|---|---|---|---:|---|---|"])
    for result in results:
        notes = "; ".join(result.get("data_limitations") or [])
        lines.append(
            f"| {result.get('tool_name')} | {result.get('tool_domain')} | {result.get('probe_type')} | {result.get('status')} | "
            f"{result.get('latency_ms') or 0} | {result.get('error_code') or ''} | {notes[:180]} |"
        )
    public_longbridge = [item for item in results if item.get("tool_domain") == "longbridge"]
    lines.extend(["", "## Longbridge Public Tools", "| Tool | Probe | Status | Latency | Error |", "|---|---|---|---:|---|"])
    for result in public_longbridge:
        lines.append(f"| {result.get('tool_name')} | {result.get('probe_type')} | {result.get('status')} | {result.get('latency_ms') or 0} | {result.get('error_code') or ''} |")
    blocked_counts = [((item.get("metadata") or {}).get("blocked_count") or 0) for item in results if item.get("tool_name") == "longbridge_catalog"]
    lines.extend(["", "## Blocked Summary", f"- blocked_count: `{max(blocked_counts) if blocked_counts else 0}`"])
    agent_results = [item for item in results if item.get("probe_type") == "agent_eval"]
    lines.extend(["", "## Agent Eval", "| Question | Expected Tools | Actual Tools | Forbidden Called | Evidence Based | Status |", "|---|---|---|---|---|---|"])
    for result in agent_results:
        meta = result.get("metadata") or {}
        lines.append(
            f"| {meta.get('question', result.get('tool_name'))} | {', '.join(meta.get('expected_tools') or [])} | n/a | "
            f"{meta.get('forbidden_called')} | {meta.get('evidence_based')} | {result.get('status')} |"
        )
    failures = [item for item in results if item.get("status") == "fail"]
    lines.extend(["", "## Failures"])
    if not failures:
        lines.append("No failures.")
    for item in failures:
        lines.append(f"- {item.get('tool_name')} / {item.get('probe_type')}: {item.get('error_code') or ''} {item.get('error_message') or ''}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("ACCOUNT_COPILOT_BASE_URL", ""))
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--symbol", default="AMD.US")
    parser.add_argument("--keyword", default="AMD")
    parser.add_argument("--include-agent-eval", action="store_true")
    parser.add_argument("--include-longbridge-live", action="store_true")
    parser.add_argument("--include-ibkr-live", action="store_true")
    parser.add_argument("--max-tools", type=int, default=200)
    parser.add_argument("--report-path", default="docs/account_copilot_tool_reliability_report.md")
    parser.add_argument("--json-output", default="")
    args = parser.parse_args()
    started_at = utc_now()
    if args.base_url and not args.local:
        client = HttpProbeClient(args.base_url)
        client.login()
        report = client.run_probe(
            {
                "include_live": bool(args.include_longbridge_live or args.include_ibkr_live),
                "include_longbridge": args.include_longbridge_live,
                "include_ibkr": args.include_ibkr_live,
                "include_agent_eval": args.include_agent_eval,
                "symbol": args.symbol,
                "keyword": args.keyword,
                "max_tools": args.max_tools,
            }
        )
    else:
        report = run_local_probe(args)
    report = normalize_report_statuses(report)
    report = redact(report)
    finished_at = utc_now()
    render_report(report, ROOT / args.report_path, started_at, finished_at)
    if args.json_output:
        Path(args.json_output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report_path={args.report_path}")
    print(json.dumps(report.get("summary") or {}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
