#!/usr/bin/env python3
"""Live Account Copilot routing evaluation.

Tests the Planner's ability to route questions to the correct capability:
1. Skill first (for account/trading/review/risk questions)
2. SubAgent second (for public market exploration)
3. Plain tools last (for general knowledge)

Requires real server, real LLM, real Longbridge MCP, real Elasticsearch.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


SENSITIVE_KEYS = {
    "token", "access_token", "refresh_token", "authorization",
    "api_key", "secret", "password", "cookie", "set_cookie",
    "chain_of_thought", "reasoning", "thinking",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key in os.environ:
            continue
        value = value.strip().strip("'").strip('"')
        os.environ[key] = value


def safe_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text[:500]}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in SENSITIVE_KEYS:
                cleaned[key] = "***REDACTED***"
            else:
                cleaned[key] = redact(item)
        return cleaned
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def find_sensitive_paths(value: Any, prefix: str = "$") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            path = f"{prefix}.{key}"
            if normalized in SENSITIVE_KEYS:
                paths.append(path)
            paths.extend(find_sensitive_paths(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            paths.extend(find_sensitive_paths(item, f"{prefix}[{index}]"))
    return paths


def preview(value: Any, limit: int = 320) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def make_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


@dataclass
class CaseResult:
    case: str
    question: str
    expected_action: str
    expected_target: str
    status: str = "PENDING"
    actual_action: str = ""
    actual_target: str = ""
    run_status: str = ""
    session_id: str | None = None
    run_id: str | None = None
    final_answer_preview: str = ""
    notes: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    def note(self, message: str) -> None:
        self.notes.append(message)

    def issue(self, message: str) -> None:
        self.issues.append(message)


@dataclass
class RoutingCase:
    name: str
    question: str
    expected_action: str
    expected_target: str
    forbidden_actions: list[str] = field(default_factory=list)
    forbidden_targets: list[str] = field(default_factory=list)
    expect_awaiting_approval: bool = False
    validator: Any = None  # optional callable(CaseResult, dict) -> None


class LiveRoutingClient:
    def __init__(self, base_url: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def login(self, username: str | None, password: str | None, cookie: str | None) -> None:
        if cookie:
            self.session.headers.update({"Cookie": cookie})
            return
        if not username or not password:
            raise SystemExit("Missing credentials.")
        response = self.session.post(
            make_url(self.base_url, "/api/auth/login"),
            json={"username": username, "password": password},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise SystemExit(f"Login failed: HTTP {response.status_code}")

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        return self.session.request(
            method, make_url(self.base_url, path),
            timeout=kwargs.pop("timeout", self.timeout), **kwargs,
        )

    def get_json(self, path: str, **kwargs) -> tuple[int, Any]:
        response = self.request("GET", path, **kwargs)
        return response.status_code, safe_json(response)

    def post_json(self, path: str, body: dict | None = None, **kwargs) -> tuple[int, Any]:
        response = self.request("POST", path, json=body or {}, **kwargs)
        return response.status_code, safe_json(response)

    def create_session(self, title: str) -> dict:
        status, payload = self.post_json("/api/agent/account-copilot/sessions", {"title": title})
        if status >= 400:
            raise RuntimeError(f"create session failed: HTTP {status} {preview(payload)}")
        return payload

    def send_stream(self, session_id: str, content: str) -> dict:
        status, payload = self.post_json(
            f"/api/agent/account-copilot/sessions/{session_id}/messages/stream",
            {"content": content},
        )
        if status >= 400:
            raise RuntimeError(f"send stream failed: HTTP {status} {preview(payload)}")
        return payload

    def get_run(self, run_id: str) -> dict:
        status, payload = self.get_json(f"/api/agent/account-copilot/runs/{run_id}")
        if status >= 400:
            raise RuntimeError(f"get run failed: HTTP {status} {preview(payload)}")
        return payload

    def list_events(self, run_id: str, after_seq: int = 0, limit: int = 1000) -> list[dict]:
        status, payload = self.get_json(
            f"/api/agent/account-copilot/runs/{run_id}/events/list?after_seq={after_seq}&limit={limit}"
        )
        if status >= 400:
            return []
        return payload.get("items") or []

    def wait_run(self, run_id: str, timeout_seconds: int = 180) -> tuple[dict, list[dict]]:
        started = time.monotonic()
        events: list[dict] = []
        last_seq = 0
        while time.monotonic() - started <= timeout_seconds:
            for event in self.list_events(run_id, after_seq=last_seq):
                events.append(event)
                last_seq = max(last_seq, int(event.get("seq") or 0))
            run = self.get_run(run_id)
            if run.get("status") in {"completed", "failed", "cancelled", "awaiting_approval"}:
                return run, events
            time.sleep(2)
        return self.get_run(run_id), events

    def check_health(self) -> dict:
        status, payload = self.get_json("/api/agent/account-copilot/health")
        if status >= 400:
            raise SystemExit(f"Health check failed: HTTP {status}")
        return payload


def extract_routing(run: dict, events: list[dict]) -> tuple[str, str]:
    """Extract the primary action_type and target (skill_name or subagent_name) from a run."""
    actions = run.get("actions") or []
    observations = run.get("observations") or []

    # Check actions for the primary routing decision
    for action in actions:
        action_type = action.get("action_type", "")
        if action_type == "delegate_to_subagent":
            return "delegate_to_subagent", action.get("subagent_name") or ""
        if action_type == "request_skill_approval":
            return "request_skill_approval", action.get("skill_name") or ""
        if action_type == "call_tool":
            return "call_tool", action.get("tool_name") or ""
        if action_type == "final_answer":
            return "final_answer", ""

    # Fallback: check events
    for event in events:
        etype = event.get("event_type", "")
        payload = event.get("payload") or {}
        if etype == "planner_finished":
            at = payload.get("action_type", "")
            if at == "delegate_to_subagent":
                return "delegate_to_subagent", payload.get("subagent_name") or ""
            if at == "request_skill_approval":
                return "request_skill_approval", payload.get("skill_name") or ""
            if at == "call_tool":
                return "call_tool", payload.get("tool_name") or ""
            if at == "final_answer":
                return "final_answer", ""

    # Check run status for awaiting_approval
    if run.get("status") == "awaiting_approval":
        pending = run.get("pending_approval") or {}
        return "request_skill_approval", pending.get("skill_name") or ""

    return "unknown", ""


def validate_no_secrets(payload: dict) -> list[str]:
    """Check that no sensitive keys leak in the response."""
    return find_sensitive_paths(payload)


# --- Test Cases ---

CASES: list[RoutingCase] = [
    RoutingCase(
        name="Case 1: Public market research - AMD drop",
        question="AMD 最近为什么大跌？",
        expected_action="delegate_to_subagent",
        expected_target="public_market_research_subagent",
        forbidden_actions=["request_skill_approval"],
        forbidden_targets=[
            "trade_decision_entry_skill", "trade_decision_holding_skill",
            "trade_review_symbol_skill", "daily_position_review_skill",
            "risk_assessment_skill",
        ],
    ),
    RoutingCase(
        name="Case 2: Public market long-term research - AMD factors",
        question="AMD 未来三年有哪些多空因素？",
        expected_action="delegate_to_subagent",
        expected_target="public_market_research_subagent",
        forbidden_actions=["request_skill_approval"],
        forbidden_targets=[
            "trade_decision_entry_skill", "trade_decision_holding_skill",
        ],
    ),
    RoutingCase(
        name="Case 3: Trading decision - add AMD position",
        question="我现在要不要加仓 AMD？",
        expected_action="request_skill_approval",
        expected_target="trade_decision_holding_skill",
        forbidden_actions=["delegate_to_subagent"],
        forbidden_targets=["public_market_research_subagent"],
        expect_awaiting_approval=True,
    ),
    RoutingCase(
        name="Case 4: Entry decision - buy MSTR",
        question="我准备买 10 股 MSTR，合理吗？",
        expected_action="request_skill_approval",
        expected_target="trade_decision_entry_skill",
        forbidden_actions=["delegate_to_subagent"],
        forbidden_targets=["public_market_research_subagent"],
        expect_awaiting_approval=True,
    ),
    RoutingCase(
        name="Case 5: Trade review - AMD sell regret",
        question="复盘一下我最近 AMD 的交易，我是不是卖飞了？",
        expected_action="request_skill_approval",
        expected_target="trade_review_symbol_skill",
        forbidden_actions=["delegate_to_subagent"],
        forbidden_targets=["public_market_research_subagent"],
        expect_awaiting_approval=True,
    ),
    RoutingCase(
        name="Case 6: Account risk assessment",
        question="我的账户现在风险大吗？仓位会不会太集中？",
        expected_action="request_skill_approval",
        expected_target="risk_assessment_skill",
        forbidden_actions=["delegate_to_subagent"],
        forbidden_targets=["public_market_research_subagent"],
        expect_awaiting_approval=True,
    ),
    RoutingCase(
        name="Case 7: Daily position review",
        question="帮我分析一下昨天账户为什么涨跌。",
        expected_action="request_skill_approval",
        expected_target="daily_position_review_skill",
        forbidden_actions=["delegate_to_subagent"],
        forbidden_targets=["public_market_research_subagent"],
        expect_awaiting_approval=True,
    ),
    RoutingCase(
        name="Case 8: General knowledge question",
        question="什么是摊薄成本？",
        expected_action="final_answer",
        expected_target="",
        forbidden_actions=["request_skill_approval", "delegate_to_subagent"],
        forbidden_targets=[
            "public_market_research_subagent",
            "trade_decision_entry_skill", "trade_decision_holding_skill",
            "trade_review_symbol_skill", "daily_position_review_skill",
            "risk_assessment_skill",
        ],
    ),
]


def run_single_case(client: LiveRoutingClient, case: RoutingCase, timeout: int) -> CaseResult:
    """Execute a single routing case against the live server."""
    result = CaseResult(
        case=case.name,
        question=case.question,
        expected_action=case.expected_action,
        expected_target=case.expected_target,
    )

    try:
        session = client.create_session(case.name)
        session_id = session["id"]
        result.session_id = session_id
    except Exception as exc:
        result.status = "FAIL"
        result.issue(f"Session creation failed: {exc}")
        return result

    try:
        send_response = client.send_stream(session_id, case.question)
        run_id = send_response.get("run", {}).get("id")
        if not run_id:
            result.status = "FAIL"
            result.issue("No run_id in send response")
            return result
        result.run_id = run_id
    except Exception as exc:
        result.status = "FAIL"
        result.issue(f"Message send failed: {exc}")
        return result

    try:
        run, events = client.wait_run(run_id, timeout_seconds=timeout)
    except Exception as exc:
        result.status = "FAIL"
        result.issue(f"Wait run failed: {exc}")
        return result

    result.run_status = run.get("status", "unknown")
    result.final_answer_preview = preview(run.get("final_answer") or "")

    actual_action, actual_target = extract_routing(run, events)
    result.actual_action = actual_action
    result.actual_target = actual_target

    # --- Validation ---

    # Check for sensitive data leaks
    secrets = validate_no_secrets(run)
    if secrets:
        result.issue(f"Sensitive data leak at paths: {secrets}")

    # Check expected action
    if actual_action != case.expected_action:
        result.issue(f"Action mismatch: expected={case.expected_action}, actual={actual_action}")

    # Check expected target (allow partial match for skills)
    if case.expected_target and case.expected_target not in actual_target:
        result.issue(f"Target mismatch: expected={case.expected_target}, actual={actual_target}")

    # Check forbidden actions
    if actual_action in case.forbidden_actions:
        result.issue(f"Forbidden action used: {actual_action}")

    # Check forbidden targets
    for forbidden in case.forbidden_targets:
        if forbidden in actual_target:
            result.issue(f"Forbidden target used: {forbidden}")

    # Check awaiting_approval status for skill cases
    if case.expect_awaiting_approval and result.run_status != "awaiting_approval":
        result.issue(f"Expected awaiting_approval but got: {result.run_status}")

    # Check observation_type=subagent_result for subagent cases
    if case.expected_action == "delegate_to_subagent":
        observations = run.get("observations") or []
        has_subagent_obs = any(
            obs.get("observation_type") == "subagent_result" for obs in observations
        )
        if has_subagent_obs:
            result.note("observation_type=subagent_result confirmed")
        else:
            result.note("No subagent_result observation found (may be in events)")

    result.status = "PASS" if not result.issues else "FAIL"
    return result


def render_table(results: list[CaseResult]) -> str:
    """Render results as a markdown table."""
    lines = [
        "| Case | Question | Expected | Actual Action | Skill/SubAgent | Run Status | Result |",
        "|------|----------|----------|---------------|----------------|------------|--------|",
    ]
    for r in results:
        q = r.question[:20] + "..." if len(r.question) > 20 else r.question
        exp = f"{r.expected_action}" + (f"({r.expected_target})" if r.expected_target else "")
        target = r.actual_target or "-"
        status_icon = "PASS" if r.status == "PASS" else "FAIL"
        lines.append(
            f"| {r.case} | {q} | {exp} | {r.actual_action} | {target} | {r.run_status} | {status_icon} |"
        )
    return "\n".join(lines)


def render_detail(results: list[CaseResult]) -> str:
    """Render detailed results for each case."""
    sections = []
    for r in results:
        lines = [
            f"### {r.case}",
            f"- Question: {r.question}",
            f"- Expected: {r.expected_action}" + (f"({r.expected_target})" if r.expected_target else ""),
            f"- Actual: {r.actual_action}({r.actual_target or '-'})",
            f"- Run Status: {r.run_status}",
            f"- Session ID: {r.session_id or 'N/A'}",
            f"- Run ID: {r.run_id or 'N/A'}",
            f"- Result: {r.status}",
            f"- Final Answer: {r.final_answer_preview[:200] or 'N/A'}",
        ]
        if r.issues:
            lines.append(f"- Issues: {'; '.join(r.issues)}")
        if r.notes:
            lines.append(f"- Notes: {'; '.join(r.notes)}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def main() -> int:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    parser = argparse.ArgumentParser(description="Account Copilot live routing evaluation")
    parser.add_argument("--base-url", default=os.environ.get("ACCOUNT_COPILOT_BASE_URL", "https://your-domain.example"))
    parser.add_argument("--username", default=os.environ.get("REMOTE_AUTH_USERNAME") or os.environ.get("ACCOUNT_COPILOT_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("REMOTE_AUTH_PASSWORD") or os.environ.get("ACCOUNT_COPILOT_PASSWORD"))
    parser.add_argument("--cookie", default=os.environ.get("ACCOUNT_COPILOT_SESSION_COOKIE"))
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--case", type=int, help="Run only a specific case number (1-8)")
    parser.add_argument("--json-output", type=str, help="Write JSON results to file")
    args = parser.parse_args()

    client = LiveRoutingClient(args.base_url, timeout=30)
    client.login(args.username, args.password, args.cookie)

    # Health check
    print("=" * 60)
    print("HEALTH CHECK")
    print("=" * 60)
    try:
        health = client.check_health()
        checks = health.get("checks", {})
        health_ok = health.get("ok", False)
        print(f"  ok: {health_ok}")
        print(f"  ibkr_tools: {checks.get('ibkr_tools', {}).get('count')} (expected 9)")
        print(f"  longbridge_meta_tools: {checks.get('longbridge_meta_tools', {}).get('count')} (expected >= 6)")
        print(f"  skills: {checks.get('skills', {}).get('count')} (expected 5)")

        # Check no secrets leak
        secrets = find_sensitive_paths(health)
        if secrets:
            print(f"  WARNING: sensitive paths found: {secrets}")
        else:
            print("  No sensitive data leaks in health response")

        if not health_ok:
            print("WARNING: health ok=false, proceeding anyway")
    except Exception as exc:
        print(f"Health check error: {exc}")
        return 1

    # Run cases
    cases_to_run = CASES
    if args.case:
        idx = args.case - 1
        if idx < 0 or idx >= len(CASES):
            print(f"Invalid case number: {args.case}. Valid range: 1-{len(CASES)}")
            return 1
        cases_to_run = [CASES[idx]]

    results: list[CaseResult] = []
    print(f"\n{'=' * 60}")
    print(f"RUNNING {len(cases_to_run)} ROUTING CASES")
    print(f"{'=' * 60}")

    for i, case in enumerate(cases_to_run, 1):
        print(f"\n[{i}/{len(cases_to_run)}] {case.name}")
        print(f"  Q: {case.question}")
        result = run_single_case(client, case, args.timeout_seconds)
        results.append(result)
        print(f"  Action: {result.actual_action} | Target: {result.actual_target or '-'}")
        print(f"  Run: {result.run_status} | Result: {result.status}")
        if result.issues:
            for issue in result.issues:
                print(f"  ISSUE: {issue}")

    # Summary
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    total = len(results)

    print(f"\n{'=' * 60}")
    print(f"SUMMARY: {passed}/{total} PASS, {failed}/{total} FAIL")
    print(f"{'=' * 60}")
    print(render_table(results))

    # Detailed results
    print(f"\n{'=' * 60}")
    print("DETAILED RESULTS")
    print(f"{'=' * 60}")
    print(render_detail(results))

    # JSON output
    if args.json_output:
        output = {
            "base_url": args.base_url,
            "timestamp": utc_now(),
            "summary": {"passed": passed, "failed": failed, "total": total},
            "results": [
                {
                    "case": r.case,
                    "question": r.question,
                    "expected_action": r.expected_action,
                    "expected_target": r.expected_target,
                    "actual_action": r.actual_action,
                    "actual_target": r.actual_target,
                    "run_status": r.run_status,
                    "session_id": r.session_id,
                    "run_id": r.run_id,
                    "status": r.status,
                    "issues": r.issues,
                    "final_answer_preview": r.final_answer_preview[:200],
                }
                for r in results
            ],
        }
        Path(args.json_output).write_text(json.dumps(output, ensure_ascii=False, indent=2))
        print(f"\nJSON output written to: {args.json_output}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
