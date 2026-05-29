#!/usr/bin/env python3
"""Live Account Copilot goal validation.

This script intentionally uses only real online services. It does not enable
demo mode or fake providers. Sensitive values are read from environment
variables and never printed or written to the report.
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
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "api_key",
    "secret",
    "password",
    "cookie",
    "set_cookie",
    "chain_of_thought",
    "reasoning",
    "thinking",
}
FORBIDDEN_LONGBRIDGE_PATTERNS = re.compile(
    r"(submit_order|order|orders|account|balance|position|positions|trade|trades|withdraw|deposit|transfer|cash|bank)",
    re.IGNORECASE,
)
FINANCIAL_AMOUNT_PATTERNS = [
    re.compile(r"([$¥￥]\s*)[-+]?\d[\d,]*(?:\.\d+)?"),
    re.compile(r"\b(?:USD|HKD|CNY|RMB)\s*[-+]?\d[\d,]*(?:\.\d+)?\b", re.IGNORECASE),
    re.compile(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?"),
]


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


def redact_financial_text(text: str) -> str:
    cleaned = text
    for pattern in FINANCIAL_AMOUNT_PATTERNS:
        cleaned = pattern.sub("[amount]", cleaned)
    return cleaned


def preview(value: Any, limit: int = 320) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = re.sub(r"\s+", " ", text).strip()
    text = redact_financial_text(text)
    return text[:limit]


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


def url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


@dataclass
class CaseResult:
    case: str
    name: str
    status: str = "PENDING"
    session_id: str | None = None
    run_id: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    final_answer_preview: str = ""
    notes: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    def note(self, message: str) -> None:
        self.notes.append(message)

    def issue(self, message: str) -> None:
        self.issues.append(message)


class LiveGoalClient:
    def __init__(self, base_url: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def login(self, username: str | None, password: str | None, cookie: str | None) -> None:
        if cookie:
            self.session.headers.update({"Cookie": cookie})
            return
        if not username or not password:
            raise SystemExit("Missing credentials: provide ACCOUNT_COPILOT_SESSION_COOKIE or username/password.")
        response = self.session.post(
            url(self.base_url, "/api/auth/login"),
            json={"username": username, "password": password},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise SystemExit(f"Login failed: HTTP {response.status_code}")

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        return self.session.request(method, url(self.base_url, path), timeout=kwargs.pop("timeout", self.timeout), **kwargs)

    def get_json(self, path: str, **kwargs) -> tuple[int, Any]:
        response = self.request("GET", path, **kwargs)
        return response.status_code, safe_json(response)

    def post_json(self, path: str, body: dict | None = None, **kwargs) -> tuple[int, Any]:
        response = self.request("POST", path, json=body or {}, **kwargs)
        return response.status_code, safe_json(response)

    def patch_json(self, path: str, body: dict | None = None) -> tuple[int, Any]:
        response = self.request("PATCH", path, json=body or {})
        return response.status_code, safe_json(response)

    def create_session(self, title: str) -> dict:
        status, payload = self.post_json("/api/agent/account-copilot/sessions", {"title": title})
        if status >= 400:
            raise RuntimeError(f"create session failed: HTTP {status} {preview(payload)}")
        return payload

    def send_stream(self, session_id: str, content: str) -> dict:
        status, payload = self.post_json(f"/api/agent/account-copilot/sessions/{session_id}/messages/stream", {"content": content})
        if status >= 400:
            raise RuntimeError(f"send stream failed: HTTP {status} {preview(payload)}")
        return payload

    def list_events(self, run_id: str, after_seq: int = 0, limit: int = 1000) -> list[dict]:
        status, payload = self.get_json(f"/api/agent/account-copilot/runs/{run_id}/events/list?after_seq={after_seq}&limit={limit}")
        if status >= 400:
            return []
        return payload.get("items") or []

    def get_run(self, run_id: str) -> dict:
        status, payload = self.get_json(f"/api/agent/account-copilot/runs/{run_id}")
        if status >= 400:
            raise RuntimeError(f"get run failed: HTTP {status} {preview(payload)}")
        return payload

    def wait_run(self, run_id: str, timeout_seconds: int = 240, collect_sse: bool = True) -> tuple[dict, list[dict]]:
        started = time.monotonic()
        events: list[dict] = []
        last_seq = 0
        if collect_sse:
            # The endpoint is SSE; using short streamed reads gives real coverage
            # without relying on a third-party EventSource client.
            try:
                with self.session.get(
                    url(self.base_url, f"/api/agent/account-copilot/runs/{run_id}/events?after_seq=0"),
                    stream=True,
                    timeout=(10, min(timeout_seconds, 90)),
                ) as response:
                    buffer: list[str] = []
                    for raw_line in response.iter_lines(decode_unicode=True):
                        if time.monotonic() - started > timeout_seconds:
                            break
                        line = raw_line or ""
                        if line == "":
                            event = self._parse_sse(buffer)
                            buffer = []
                            if event:
                                events.append(event)
                                last_seq = max(last_seq, int(event.get("seq") or 0))
                                if event.get("event_type") in {"run_completed", "run_failed", "run_cancelled"}:
                                    break
                            continue
                        buffer.append(line)
            except requests.RequestException:
                pass
        while time.monotonic() - started <= timeout_seconds:
            for event in self.list_events(run_id, after_seq=last_seq):
                events.append(event)
                last_seq = max(last_seq, int(event.get("seq") or 0))
            run = self.get_run(run_id)
            if run.get("status") in {"completed", "failed", "cancelled", "awaiting_approval"}:
                return run, events
            time.sleep(2)
        return self.get_run(run_id), events

    @staticmethod
    def _parse_sse(lines: list[str]) -> dict | None:
        data_lines = [line.removeprefix("data:").strip() for line in lines if line.startswith("data:")]
        if not data_lines:
            return None
        try:
            parsed = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None


def summarize_run(result: CaseResult, run: dict, events: list[dict]) -> None:
    result.run_id = run.get("id")
    result.session_id = run.get("session_id")
    result.events = events
    result.tool_calls = run.get("tool_calls") or []
    result.observations = run.get("observations") or []
    result.final_answer_preview = preview(run.get("final_answer") or "")
    result.note(f"run_status={run.get('status')}; event_count={len(events)}")


def has_event(events: list[dict], prefix: str) -> bool:
    return any(str(event.get("event_type") or "").startswith(prefix) for event in events)


def event_types(events: list[dict]) -> set[str]:
    return {str(event.get("event_type") or "") for event in events}


def validate_no_sensitive_events(events: list[dict]) -> list[str]:
    findings = []
    for event in events:
        for path in find_sensitive_paths(event.get("payload") or {}):
            findings.append(f"run={event.get('run_id')} seq={event.get('seq')} path={path}")
    return findings


def validate_longbridge_safety(run: dict) -> list[str]:
    issues = []
    for call in run.get("tool_calls") or []:
        name = str(call.get("tool_name") or "")
        if name.startswith("longbridge_") and name not in {
            "longbridge_list_public_tools",
            "longbridge_get_public_tool_schema",
            "longbridge_call_public_tool",
        }:
            issues.append(f"unexpected longbridge top-level tool {name}")
        arguments_text = json.dumps(call.get("arguments") or {}, ensure_ascii=False, default=str)
        if name.startswith("longbridge_") and FORBIDDEN_LONGBRIDGE_PATTERNS.search(arguments_text):
            issues.append(f"forbidden longbridge argument path in {name}")
    return issues


def run_case_a(client: LiveGoalClient) -> tuple[CaseResult, dict]:
    result = CaseResult("A", "健康检查")
    status, health = client.get_json("/api/agent/account-copilot/health")
    if status < 400:
        raw = json.dumps(health, ensure_ascii=False).lower()
        checks = health.get("checks") or {}
        ok = (
            "token" not in raw
            and "api_key" not in raw
            and checks.get("ibkr_tools", {}).get("count") == 9
            and checks.get("longbridge_meta_tools", {}).get("count") >= 6
            and checks.get("skills", {}).get("count") == 5
        )
        result.status = "PASS" if ok else "FAIL"
        if not ok:
            result.issue("health checks did not match expected counts or leaked sensitive keys")
        result.note(f"demo_mode={health.get('settings', {}).get('demo_mode')}; ok={health.get('ok')}")
    else:
        result.status = "FAIL"
        result.issue(f"HTTP {status}: {preview(health)}")
    return result, health if isinstance(health, dict) else {}


def run_case_b(client: LiveGoalClient) -> tuple[CaseResult, dict]:
    result = CaseResult("B", "多会话")
    session = client.create_session(f"Live Goal {datetime.now().strftime('%Y%m%d %H%M%S')}")
    result.session_id = session.get("id")
    status, payload = client.get_json("/api/agent/account-copilot/sessions?limit=100")
    visible = status < 400 and any(item.get("id") == session.get("id") for item in payload.get("items", []))
    result.status = "PASS" if visible else "FAIL"
    if not visible:
        result.issue("created session was not visible in session list")
    return result, session


def run_stream_question(client: LiveGoalClient, case: str, name: str, session_id: str, question: str, timeout: int = 240) -> tuple[CaseResult, dict]:
    result = CaseResult(case, name, session_id=session_id)
    payload = client.send_stream(session_id, question)
    run_id = payload["run"]["id"]
    run, events = client.wait_run(run_id, timeout_seconds=timeout)
    summarize_run(result, run, events)
    return result, run


def run_case_c(client: LiveGoalClient, session_id: str) -> tuple[CaseResult, dict]:
    result, run = run_stream_question(client, "C", "IBKR 账户事实问答", session_id, "我现在账户风险高不高？请基于真实 IBKR 账户事实回答，不要编造。")
    types = event_types(result.events)
    ibkr_calls = [call for call in run.get("tool_calls") or [] if str(call.get("tool_name") or "").startswith("ibkr_")]
    status, messages = client.get_json(f"/api/agent/account-copilot/sessions/{session_id}/messages?limit=200")
    ok = (
        run.get("status") == "completed"
        and "planner_started" in types
        and any(item in types for item in {"tool_finished", "tool_failed"})
        and "observation_created" in types
        and "final_answer" in types
        and "run_completed" in types
        and bool(ibkr_calls)
        and status < 400
        and bool(messages.get("items"))
    )
    result.status = "PASS" if ok else "PARTIAL"
    if not ibkr_calls:
        result.issue("no ibkr_ tool call observed")
    return result, run


def run_case_d(client: LiveGoalClient, session_id: str) -> tuple[CaseResult, dict]:
    result, run = run_stream_question(
        client,
        "D",
        "Longbridge 渐进式披露",
        session_id,
        "AMD 最近为什么涨跌？请先查可用的长桥公开市场工具，再按需查询公开行情或新闻。",
    )
    calls = [str(call.get("tool_name") or "") for call in run.get("tool_calls") or []]
    longbridge_calls = [name for name in calls if name.startswith("longbridge_")]
    safety_issues = validate_longbridge_safety(run)
    expected_meta_flow = {
        "longbridge_list_public_tools",
        "longbridge_get_public_tool_schema",
        "longbridge_call_public_tool",
    }
    observed_meta_flow = set(longbridge_calls)
    ok = run.get("status") == "completed" and expected_meta_flow.issubset(observed_meta_flow) and not safety_issues
    result.status = "PASS" if ok else "PARTIAL"
    for issue in safety_issues:
        result.issue(issue)
    if not longbridge_calls:
        result.issue("no longbridge meta tool call observed")
    missing_meta = sorted(expected_meta_flow - observed_meta_flow)
    if missing_meta:
        result.issue(f"longbridge progressive flow missing: {', '.join(missing_meta)}")
    return result, run


def request_skill_until_approval(client: LiveGoalClient, session_id: str, prompts: list[str], case: str, name: str) -> tuple[CaseResult, dict]:
    last_result: CaseResult | None = None
    last_run: dict | None = None
    for prompt in prompts:
        result, run = run_stream_question(client, case, name, session_id, prompt)
        last_result, last_run = result, run
        if run.get("status") == "awaiting_approval" and run.get("pending_approval"):
            result.status = "PASS"
            return result, run
        if run.get("status") in {"completed", "failed"}:
            # Continue only when the run is terminal and does not block the session.
            continue
    assert last_result is not None and last_run is not None
    last_result.status = "PARTIAL"
    last_result.issue("model did not request skill approval")
    return last_result, last_run


def run_case_e(client: LiveGoalClient, session_id: str) -> tuple[CaseResult, dict]:
    result, run = request_skill_until_approval(
        client,
        session_id,
        [
            "MU 现在适合建仓吗？如果需要专业交易决策 Skill，请先申请我的确认。",
            "请申请 trade_decision_entry_skill 来分析 MU 是否适合建仓，先等待我审批，不要直接给结论。",
        ],
        "E",
        "Skill 申请 + 同意",
    )
    if run.get("status") != "awaiting_approval":
        return result, run
    pending = run["pending_approval"]
    if not all(pending.get(key) for key in ("approval_id", "plan_hash", "skill_name", "skill_arguments")):
        result.status = "FAIL"
        result.issue("pending_approval missing required approval fields")
        return result, run
    if run.get("observations"):
        skill_observations = [obs for obs in run.get("observations") or [] if obs.get("observation_type") == "skill_result"]
        if skill_observations:
            result.status = "FAIL"
            result.issue("skill_result observation existed before approval")
            return result, run
    status, payload = client.post_json(
        f"/api/agent/account-copilot/runs/{run['id']}/approval",
        {"approval_id": pending["approval_id"], "approved": True, "plan_hash": pending["plan_hash"]},
        timeout=300,
    )
    approval_http_failed = status >= 400
    if status >= 400:
        result.note(f"approval_http={status}; polling run for backend completion")
        deadline = time.monotonic() + 300
        approved_run = client.get_run(run["id"])
        while time.monotonic() < deadline:
            if approved_run.get("status") in {"completed", "failed", "cancelled"}:
                break
            time.sleep(3)
            approved_run = client.get_run(run["id"])
        if approved_run.get("status") not in {"completed", "failed", "cancelled"}:
            result.status = "FAIL"
            result.issue(f"approval failed HTTP {status}: {preview(payload)}")
            return result, approved_run
    else:
        approved_run = payload.get("run") or client.get_run(run["id"])
    summarize_run(result, approved_run, client.list_events(run["id"]))
    skill_obs = [obs for obs in approved_run.get("observations") or [] if obs.get("observation_type") == "skill_result"]
    ok = approved_run.get("status") == "completed" and bool(skill_obs) and bool(approved_run.get("final_answer"))
    result.status = "PARTIAL" if ok and approval_http_failed else ("PASS" if ok else "PARTIAL")
    if ok and approval_http_failed:
        result.issue("approval endpoint returned an HTTP error but backend completed and executed the approved skill")
    if not skill_obs:
        result.issue("no skill_result observation after approval")
    return result, approved_run


def run_case_f(client: LiveGoalClient, session_id: str) -> tuple[CaseResult, dict]:
    result, run = request_skill_until_approval(
        client,
        session_id,
        [
            "AMD 要不要继续持有？如果需要 Skill，请申请确认。",
            "请申请 trade_decision_holding_skill 来分析 AMD 是否继续持有，先等待我审批，不要直接执行。",
        ],
        "F",
        "Skill 申请 + 拒绝",
    )
    if run.get("status") != "awaiting_approval":
        return result, run
    pending = run["pending_approval"]
    status, payload = client.post_json(
        f"/api/agent/account-copilot/runs/{run['id']}/approval",
        {"approval_id": pending["approval_id"], "approved": False, "plan_hash": pending["plan_hash"]},
        timeout=120,
    )
    rejected_run = (payload.get("run") if isinstance(payload, dict) else None) or client.get_run(run["id"])
    summarize_run(result, rejected_run, client.list_events(run["id"]))
    rejected = (rejected_run.get("pending_approval") or {}).get("status") == "rejected"
    no_skill_result = not any(obs.get("observation_type") == "skill_result" for obs in rejected_run.get("observations") or [])
    result.status = "PASS" if status < 400 and rejected and no_skill_result else "FAIL"
    if not rejected:
        result.issue("pending approval was not rejected")
    if not no_skill_result:
        result.issue("skill executed despite rejection")
    return result, rejected_run


def run_case_g(client: LiveGoalClient, run_id: str) -> CaseResult:
    result = CaseResult("G", "SSE after_seq 恢复", run_id=run_id)
    events = client.list_events(run_id)
    if len(events) < 2:
        result.status = "PARTIAL"
        result.issue("not enough persisted events to validate after_seq")
        return result
    last_seq = int(events[min(1, len(events) - 1)].get("seq") or 0)
    after = client.list_events(run_id, after_seq=last_seq)
    duplicate = any(int(event.get("seq") or 0) <= last_seq for event in after)
    result.events = after
    result.status = "PASS" if not duplicate else "FAIL"
    if duplicate:
        result.issue("events/list returned duplicate old events")
    result.note(f"last_seq={last_seq}; recovered={len(after)}")
    return result


def run_case_h(client: LiveGoalClient) -> tuple[CaseResult, dict, str]:
    result = CaseResult("H", "取消运行")
    session = client.create_session("Live Goal Cancel")
    result.session_id = session["id"]
    payload = client.send_stream(
        session["id"],
        "请综合分析账户风险、AMD/MU/NVDA 公开市场信息、历史交易行为和现金流，分多步规划后再回答。",
    )
    run_id = payload["run"]["id"]
    result.run_id = run_id
    status, cancel_payload = client.post_json(f"/api/agent/account-copilot/runs/{run_id}/cancel", {"reason": "live goal cancellation"})
    time.sleep(5)
    run = client.get_run(run_id)
    events = client.list_events(run_id)
    summarize_run(result, run, events)
    if status < 400 and run.get("status") == "cancelled" and "run_cancelled" in event_types(events):
        try:
            follow_up = client.send_stream(session["id"], "取消后继续：请简单确认这个会话还能继续提问。")
            follow_run, follow_events = client.wait_run(follow_up["run"]["id"], timeout_seconds=180)
            if follow_run.get("status") in {"completed", "awaiting_approval", "failed"}:
                result.status = "PASS"
            else:
                result.status = "PARTIAL"
                result.issue("follow-up message did not reach terminal or approval state")
        except Exception as exc:
            result.status = "PARTIAL"
            result.issue(f"follow-up after cancellation failed: {str(exc)[:160]}")
    else:
        result.status = "FAIL"
        result.issue(f"cancel failed HTTP {status}: {preview(cancel_payload)}")
    return result, run, session["id"]


def run_case_i(client: LiveGoalClient) -> CaseResult:
    result = CaseResult("I", "active run 防并发")
    session = client.create_session("Live Goal Active Run")
    result.session_id = session["id"]
    payload = client.send_stream(session["id"], "请申请 risk_assessment_skill，先等待审批，不要直接执行。")
    run, events = client.wait_run(payload["run"]["id"], timeout_seconds=180)
    summarize_run(result, run, events)
    if run.get("status") not in {"running", "awaiting_approval"}:
        result.status = "PARTIAL"
        result.issue("could not create stable active run for concurrency check")
        return result
    status, body = client.post_json(f"/api/agent/account-copilot/sessions/{session['id']}/messages/stream", {"content": "并发发送测试"})
    blocked = status == 409
    if run.get("status") == "awaiting_approval" and run.get("pending_approval"):
        pending = run["pending_approval"]
        client.post_json(
            f"/api/agent/account-copilot/runs/{run['id']}/approval",
            {"approval_id": pending["approval_id"], "approved": False, "plan_hash": pending["plan_hash"]},
        )
    elif run.get("status") == "running":
        client.post_json(f"/api/agent/account-copilot/runs/{run['id']}/cancel", {"reason": "finish active run check"})
    result.status = "PASS" if blocked else "FAIL"
    if not blocked:
        result.issue(f"expected 409, got HTTP {status}: {preview(body)}")
    return result


def run_case_j(client: LiveGoalClient) -> CaseResult:
    result = CaseResult("J", "Memory")
    session = client.create_session("Live Goal Memory")
    result.session_id = session["id"]
    prompts = [
        "后面请记住我更关注长期收益，但不想单一股票过度集中。",
        "请基于这个偏好，简单看一下我的账户风险。",
        "如果后续讨论 AMD，请优先提醒我集中度风险。",
        "请总结一下刚才我告诉你的长期偏好。",
        "再追问一次：现金比例和集中度哪个更值得优先关注？",
        "请记住：涉及交易建议时必须说明风险，不要给确定性指令。",
    ]
    for prompt in prompts:
        try:
            payload = client.send_stream(session["id"], prompt)
            run, _events = client.wait_run(payload["run"]["id"], timeout_seconds=180, collect_sse=False)
            if run.get("status") == "awaiting_approval" and run.get("pending_approval"):
                pending = run["pending_approval"]
                client.post_json(
                    f"/api/agent/account-copilot/runs/{run['id']}/approval",
                    {"approval_id": pending["approval_id"], "approved": False, "plan_hash": pending["plan_hash"]},
                    timeout=120,
                )
            elif run.get("status") == "running":
                client.post_json(
                    f"/api/agent/account-copilot/runs/{run['id']}/cancel",
                    {"reason": "clear memory validation run"},
                    timeout=60,
                )
        except Exception as exc:
            result.issue(f"memory prompt failed: {str(exc)[:160]}")
            break
    client.post_json(f"/api/agent/account-copilot/sessions/{session['id']}/memories/rebuild")
    status, memories = client.get_json(f"/api/agent/account-copilot/sessions/{session['id']}/memories?limit=100")
    status_messages, messages = client.get_json(f"/api/agent/account-copilot/sessions/{session['id']}/messages?limit=200")
    status_session, session_payload = client.get_json(f"/api/agent/account-copilot/sessions/{session['id']}")
    items = memories.get("items") if isinstance(memories, dict) else []
    result.note(f"memory_count={len(items or [])}; message_count={len((messages or {}).get('items') or [])}")
    has_memory_fields = any(
        memory.get("summary") or memory.get("topics") or memory.get("user_preferences") or memory.get("non_compressible_constraints")
        for memory in (items or [])
    )
    original_messages_preserved = status_messages < 400 and len(messages.get("items") or []) >= 6
    rolling_summary = bool((session_payload or {}).get("rolling_summary"))
    if has_memory_fields and original_messages_preserved:
        result.status = "PASS" if rolling_summary else "PARTIAL"
    else:
        result.status = "PARTIAL"
        if not has_memory_fields:
            result.issue("no structured memory fields found after rebuild")
        if not original_messages_preserved:
            result.issue("original messages were not recoverable")
    return result


def run_case_k(client: LiveGoalClient, session_ids: list[str], run_ids: list[str]) -> CaseResult:
    result = CaseResult("K", "历史恢复")
    ok = True
    for session_id in session_ids:
        sessions_status, _sessions = client.get_json("/api/agent/account-copilot/sessions?limit=100")
        messages_status, messages = client.get_json(f"/api/agent/account-copilot/sessions/{session_id}/messages?limit=200")
        memories_status, _memories = client.get_json(f"/api/agent/account-copilot/sessions/{session_id}/memories?limit=20")
        ok = ok and sessions_status < 400 and messages_status < 400 and memories_status < 400 and bool(messages.get("items"))
    for run_id in run_ids:
        try:
            run = client.get_run(run_id)
            events = client.list_events(run_id)
            ok = ok and bool(run.get("status")) and isinstance(events, list)
        except Exception as exc:
            ok = False
            result.issue(f"run recovery failed {run_id}: {str(exc)[:120]}")
    result.session_id = session_ids[0] if session_ids else None
    result.run_id = run_ids[0] if run_ids else None
    result.status = "PASS" if ok else "FAIL"
    return result


def run_case_l(client: LiveGoalClient, approval_run: dict | None) -> CaseResult:
    result = CaseResult("L", "approval expired")
    if not approval_run or not approval_run.get("pending_approval"):
        result.status = "SKIPPED"
        result.issue("no pending approval run available")
        return result
    pending = approval_run["pending_approval"]
    result.run_id = approval_run.get("id")
    result.session_id = approval_run.get("session_id")
    expires_at = pending.get("expires_at")
    if not expires_at:
        result.status = "SKIPPED"
        result.note("pending approval has no expires_at")
        return result
    try:
        expiry_ts = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00")).timestamp()
    except ValueError:
        result.status = "SKIPPED"
        result.note("expires_at not parseable")
        return result
    wait_seconds = expiry_ts - time.time() + 2
    if wait_seconds > 300:
        result.status = "SKIPPED"
        result.note("approval expires later than 5 minutes; requires staging short TTL")
        return result
    if wait_seconds > 0:
        time.sleep(wait_seconds)
    status, payload = client.post_json(
        f"/api/agent/account-copilot/runs/{approval_run['id']}/approval",
        {"approval_id": pending["approval_id"], "approved": True, "plan_hash": pending["plan_hash"]},
        timeout=60,
    )
    run = client.get_run(approval_run["id"])
    expired = status == 400 and (run.get("pending_approval") or {}).get("status") == "expired"
    result.status = "PASS" if expired else "FAIL"
    if not expired:
        result.issue(f"expected expired approval; HTTP {status}; body={preview(payload)}")
    return result


def run_case_m(client: LiveGoalClient, run_ids: list[str]) -> CaseResult:
    result = CaseResult("M", "event sanitizer")
    findings = []
    events = []
    for run_id in run_ids:
        run_events = client.list_events(run_id)
        events.extend(run_events)
        findings.extend(validate_no_sensitive_events(run_events))
    result.events = events
    result.status = "PASS" if not findings else "FAIL"
    for finding in findings:
        result.issue(finding)
    result.note(f"scanned_events={len(events)}")
    return result


def load_tool_reliability_summary(path: Path = Path("docs/account_copilot_tool_reliability_live_report.json")) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    results = payload.get("results") or []
    summary = payload.get("summary") or {}
    longbridge_public_tool_count = len(
        {
            item.get("tool_name")
            for item in results
            if item.get("tool_domain") == "longbridge"
            and item.get("probe_type") == "schema"
            and item.get("tool_name") != "longbridge_catalog"
        }
    )

    def _success_rate(domain: str) -> float:
        domain_results = [
            item
            for item in results
            if item.get("tool_domain") == domain and item.get("probe_type") in {"invoke", "schema", "catalog"}
        ]
        if not domain_results:
            return 0.0
        passed = len([item for item in domain_results if item.get("status") == "pass"])
        return round(passed / len(domain_results) * 100, 1)

    return {
        "total_tools": summary.get("total_tools", 0),
        "pass_count": summary.get("pass_count", 0),
        "fail_count": summary.get("fail_count", 0),
        "partial_count": summary.get("partial_count", 0),
        "skipped_count": summary.get("skipped_count", 0),
        "longbridge_public_tool_count": longbridge_public_tool_count,
        "ibkr_success_rate": _success_rate("ibkr"),
        "longbridge_success_rate": _success_rate("longbridge"),
        "p95_latency_ms": summary.get("p95_latency_ms", 0),
    }


def render_report(
    report_path: Path,
    base_url: str,
    started_at: str,
    finished_at: str,
    health: dict,
    cases: list[CaseResult],
    bugs: list[dict[str, str]],
) -> None:
    counts = {status: len([case for case in cases if case.status == status]) for status in ["PASS", "FAIL", "PARTIAL", "SKIPPED"]}
    health_summary = redact(health)
    reliability_summary = load_tool_reliability_summary()
    rows = ["| Case | Name | Status | Session | Run | Notes |", "|---|---|---|---|---|---|"]
    for case in cases:
        rows.append(
            f"| {case.case} | {case.name} | {case.status} | `{case.session_id or ''}` | `{case.run_id or ''}` | {preview('; '.join(case.notes + case.issues), 220)} |"
        )
    details = []
    for case in cases:
        details.append(
            "\n".join(
                [
                    f"### Case {case.case}: {case.name}",
                    "",
                    f"- Status: **{case.status}**",
                    f"- session_id: `{case.session_id or ''}`",
                    f"- run_id: `{case.run_id or ''}`",
                    f"- event_count: {len(case.events)}",
                    f"- tool_calls: `{', '.join(str(call.get('tool_name')) for call in case.tool_calls)}`",
                    f"- observations: {len(case.observations)}",
                    f"- final_answer_preview: {case.final_answer_preview or ''}",
                    f"- notes: {preview('; '.join(case.notes), 500)}",
                    f"- issues: {preview('; '.join(case.issues), 500)}",
                ]
            )
        )
    matrix = {
        "多会话": "PASS" if any(case.case == "B" and case.status == "PASS" for case in cases) else "PARTIAL",
        "IBKR": next((case.status for case in cases if case.case == "C"), "MISSING"),
        "Longbridge": next((case.status for case in cases if case.case == "D"), "MISSING"),
        "ReAct": "PASS" if any(case.tool_calls or case.observations for case in cases) else "PARTIAL",
        "SSE": next((case.status for case in cases if case.case == "G"), "MISSING"),
        "Skill同意": next((case.status for case in cases if case.case == "E"), "MISSING"),
        "Skill拒绝": next((case.status for case in cases if case.case == "F"), "MISSING"),
        "Memory": next((case.status for case in cases if case.case == "J"), "MISSING"),
        "Cancel": next((case.status for case in cases if case.case == "H"), "MISSING"),
        "防并发": next((case.status for case in cases if case.case == "I"), "MISSING"),
        "Expired": next((case.status for case in cases if case.case == "L"), "MISSING"),
        "Sanitizer": next((case.status for case in cases if case.case == "M"), "MISSING"),
    }
    matrix_rows = ["| Feature | Status |", "|---|---|"]
    matrix_rows.extend(f"| {name} | {status} |" for name, status in matrix.items())
    bug_rows = ["No blockers found."] if not bugs else [
        f"- **{bug['title']}** ({bug['severity']}): {bug['actual']} Suggested fix: {bug['suggested_fix']}" for bug in bugs
    ]
    reliability_rows = [
        f"- total_tools: `{reliability_summary.get('total_tools', 0)}`",
        f"- pass_count: `{reliability_summary.get('pass_count', 0)}`",
        f"- fail_count: `{reliability_summary.get('fail_count', 0)}`",
        f"- partial_count: `{reliability_summary.get('partial_count', 0)}`",
        f"- skipped_count: `{reliability_summary.get('skipped_count', 0)}`",
        f"- longbridge_public_tool_count: `{reliability_summary.get('longbridge_public_tool_count', 0)}`",
        f"- ibkr_success_rate: `{reliability_summary.get('ibkr_success_rate', 0.0)}%`",
        f"- longbridge_success_rate: `{reliability_summary.get('longbridge_success_rate', 0.0)}%`",
        f"- p95_latency_ms: `{reliability_summary.get('p95_latency_ms', 0)}`",
    ]
    reliability_fail_count = int(reliability_summary.get("fail_count") or 0)
    if reliability_fail_count and not bugs:
        bug_rows = [
            "- **Tool Reliability live probe failed** (blocker): "
            f"{reliability_fail_count} reliability probe result(s) failed. "
            "Expected Longbridge catalog and read-only tools to be available; actual probe reported a live tool reliability failure. "
            "Suggested fix: inspect Longbridge MCP OAuth/client configuration and rerun the reliability probe."
        ]
    elif reliability_fail_count:
        bug_rows.append(
            "- **Tool Reliability live probe failed** (blocker): "
            f"{reliability_fail_count} reliability probe result(s) failed. "
            "Suggested fix: inspect failing probe result error_code/error_message."
        )
    has_blocker = any(bug.get("severity") == "blocker" for bug in bugs) or counts["FAIL"] > 0 or reliability_fail_count > 0
    longbridge_status = next((case.status for case in cases if case.case == "D"), "MISSING")
    longbridge_usable = (
        longbridge_status == "PASS"
        and reliability_fail_count == 0
        and reliability_summary.get("longbridge_success_rate", 0.0) >= 100.0
    )
    final_verdict = [
        f"- recommended_for_release: `{'no' if has_blocker else 'gray/internal yes'}`",
        f"- blocker_exists: `{has_blocker}`",
        f"- longbridge_mcp_available: `{longbridge_usable}`",
        f"- tool_reliability_pass_rate_acceptable: `{reliability_summary.get('fail_count', 0) == 0}`",
        f"- sensitive_leak_found: `{any(case.case == 'M' and case.status == 'FAIL' for case in cases)}`",
    ]
    md = "\n".join(
        [
            "# Account Copilot Live Goal Report",
            "",
            "## Environment",
            "",
            f"- base_url: `{base_url}`",
            f"- started_at: `{started_at}`",
            f"- finished_at: `{finished_at}`",
            f"- demo_mode: `{health.get('settings', {}).get('demo_mode')}`",
            f"- health summary:",
            "",
            "```json",
            json.dumps(health_summary, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Summary",
            "",
            f"PASS={counts['PASS']} PARTIAL={counts['PARTIAL']} FAIL={counts['FAIL']} SKIPPED={counts['SKIPPED']}",
            "",
            *rows,
            "",
            "## Tool Reliability Summary",
            "",
            *reliability_rows,
            "",
            "## Detailed Cases",
            "",
            "\n\n".join(details),
            "",
            "## Feature Coverage Matrix",
            "",
            *matrix_rows,
            "",
            "## Bugs Found",
            "",
            *bug_rows,
            "",
            "## Final Verdict",
            "",
            *final_verdict,
            "",
            "## Next Actions",
            "",
            "- Review PARTIAL/SKIPPED cases and decide whether staging-specific settings are needed.",
            "- Re-run this script after any Account Copilot runtime, tool, Skill, memory, or SSE change.",
        ]
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(md + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-path", default="docs/account_copilot_live_goal_report.md")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()

    load_dotenv(Path(".env"))
    base_url = args.base_url or os.getenv("ACCOUNT_COPILOT_BASE_URL", "")
    username = os.getenv("ACCOUNT_COPILOT_USERNAME")
    password = os.getenv("ACCOUNT_COPILOT_PASSWORD")
    cookie = os.getenv("ACCOUNT_COPILOT_SESSION_COOKIE")
    if not base_url:
        raise SystemExit("Missing ACCOUNT_COPILOT_BASE_URL.")

    client = LiveGoalClient(base_url, timeout=args.timeout)
    client.login(username, password, cookie)
    started_at = utc_now()
    cases: list[CaseResult] = []
    bugs: list[dict[str, str]] = []
    run_ids: list[str] = []
    session_ids: list[str] = []
    approval_for_expiry: dict | None = None

    case_a, health = run_case_a(client)
    cases.append(case_a)
    if health.get("settings", {}).get("demo_mode"):
        case_a.status = "FAIL"
        case_a.issue("demo mode is enabled; live validation forbids demo mode")
    case_b, main_session = run_case_b(client)
    cases.append(case_b)
    session_ids.append(main_session["id"])

    for runner in (run_case_c, run_case_d):
        try:
            case, run = runner(client, main_session["id"])
            cases.append(case)
            if run.get("id"):
                run_ids.append(run["id"])
        except Exception as exc:
            failed = CaseResult("?", runner.__name__, status="FAIL", session_id=main_session["id"])
            failed.issue(str(exc)[:500])
            cases.append(failed)

    skill_sessions: list[tuple[Any, dict]] = []
    for runner, title in (
        (run_case_e, "Live Goal Skill Approval"),
        (run_case_f, "Live Goal Skill Reject"),
    ):
        try:
            skill_session = client.create_session(title)
            skill_sessions.append((runner, skill_session))
            session_ids.append(skill_session["id"])
        except Exception as exc:
            failed = CaseResult("?", f"{runner.__name__}_session", status="FAIL")
            failed.issue(str(exc)[:500])
            cases.append(failed)

    for runner, skill_session in skill_sessions:
        try:
            case, run = runner(client, skill_session["id"])
            cases.append(case)
            if run.get("id"):
                run_ids.append(run["id"])
            if run.get("status") == "awaiting_approval":
                approval_for_expiry = run
        except Exception as exc:
            failed = CaseResult("?", runner.__name__, status="FAIL", session_id=skill_session["id"])
            failed.issue(str(exc)[:500])
            cases.append(failed)

    if run_ids:
        cases.append(run_case_g(client, run_ids[0]))
    try:
        case_h, run_h, session_h = run_case_h(client)
        cases.append(case_h)
        session_ids.append(session_h)
        if run_h.get("id"):
            run_ids.append(run_h["id"])
    except Exception as exc:
        failed = CaseResult("H", "取消运行", status="FAIL")
        failed.issue(str(exc)[:500])
        cases.append(failed)
    try:
        cases.append(run_case_i(client))
    except Exception as exc:
        failed = CaseResult("I", "active run 防并发", status="FAIL")
        failed.issue(str(exc)[:500])
        cases.append(failed)
    case_j: CaseResult | None = None
    for attempt in range(2):
        try:
            case_j = run_case_j(client)
            if attempt:
                case_j.note(f"retried_after_attempt={attempt}")
            break
        except requests.RequestException as exc:
            if attempt == 0:
                time.sleep(5)
                continue
            failed = CaseResult("J", "Memory", status="FAIL")
            failed.issue(str(exc)[:500])
            case_j = failed
        except Exception as exc:
            failed = CaseResult("J", "Memory", status="FAIL")
            failed.issue(str(exc)[:500])
            case_j = failed
            break
    if case_j is not None:
        cases.append(case_j)
        if case_j.session_id:
            session_ids.append(case_j.session_id)
    cases.append(run_case_k(client, session_ids, run_ids))
    cases.append(run_case_l(client, approval_for_expiry))
    cases.append(run_case_m(client, run_ids))

    for case in cases:
        if case.status == "FAIL":
            bugs.append(
                {
                    "title": f"Case {case.case} failed: {case.name}",
                    "severity": "high" if case.case in {"A", "C", "E", "M"} else "medium",
                    "steps": "; ".join(case.notes),
                    "expected": "Case should pass live validation.",
                    "actual": "; ".join(case.issues) or "Unknown failure.",
                    "suggested_fix": "Inspect run trace and backend logs for this run/session, then apply the smallest targeted fix.",
                }
            )

    finished_at = utc_now()
    render_report(Path(args.report_path), base_url, started_at, finished_at, health, cases, bugs)
    counts = {status: len([case for case in cases if case.status == status]) for status in ["PASS", "FAIL", "PARTIAL", "SKIPPED"]}
    print(f"report_path={args.report_path}")
    print(f"PASS={counts['PASS']} PARTIAL={counts['PARTIAL']} FAIL={counts['FAIL']} SKIPPED={counts['SKIPPED']}")
    if bugs:
        print("blockers=" + "; ".join(bug["title"] for bug in bugs))
    else:
        print("blockers=none")
    return 1 if any(case.status == "FAIL" for case in cases) else 0


if __name__ == "__main__":
    sys.exit(main())
