from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.agents.account_copilot.agent_eval_cases import FORBIDDEN_AGENT_TOOL_PATTERNS
from app.agents.account_copilot.skill_registry import build_default_skill_registry
from app.agents.account_copilot.tool_probe_cases import build_safe_longbridge_arguments
from app.agents.account_copilot.tool_registry import AccountCopilotToolRegistry, AccountCopilotToolSpec
from app.api.deps import (
    get_account_copilot_monitoring_service,
    get_account_copilot_tool_reliability_repository,
    get_account_copilot_tool_reliability_service,
    require_authenticated_session,
)
from app.main import app
from app.services.account_copilot.tool_reliability_repository import AccountCopilotToolReliabilityRepository
from app.services.account_copilot.tool_reliability_service import AccountCopilotToolReliabilityService, summarize_probe_results


class Settings:
    es_copilot_tool_probe_index = "probe-index"


class FakeES:
    def __init__(self):
        self.docs = {}
        self.created = []

    def create_index_if_missing(self, index, body):
        self.created.append((index, body))

    def index_document(self, index, id, document):
        self.docs[id] = document
        return {"result": "created"}

    def search(self, index, body):
        hits = [{"_source": doc} for doc in self.docs.values()]
        return {"hits": {"hits": hits[: body.get("size", 10)]}}


class FakeAdapter:
    def __init__(self):
        self.calls = []

    def get_tool_catalog(self, *, force_refresh=False):
        return {
            "source": "mcp_tools_list",
            "tools": [
                {
                    "name": "quote",
                    "classification": "public_market_readonly",
                    "allowed": True,
                    "description": "quote",
                    "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]},
                },
                {
                    "name": "submit_order",
                    "classification": "trading_write",
                    "allowed": False,
                    "description": "write",
                    "input_schema": {"type": "object", "properties": {"account_id": {"type": "string"}}},
                },
                {
                    "name": "custom_public",
                    "classification": "public_market_readonly",
                    "allowed": True,
                    "description": "custom",
                    "input_schema": {"type": "object", "properties": {}, "required": ["unmapped_required"]},
                },
            ],
            "public_market_readonly": ["quote", "custom_public"],
            "blocked": ["submit_order"],
        }

    def call(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        return {"ok": True, "tool": tool_name, "data": {"price": 1}, "data_limitations": []}


class FakeReliabilityRepository:
    def __init__(self, results=None, latest_probe_run_id=None):
        self.results = results or []
        self._latest_probe_run_id = latest_probe_run_id

    def latest_probe_run_id(self):
        return self._latest_probe_run_id

    def list_results(self, probe_run_id=None, limit=200):
        return self.results[:limit]


class FakeReliabilityService:
    def __init__(self, results):
        self.results = results

    def run_probe(self, **kwargs):
        return {"probe_run_id": "probe_run_test", "results": self.results, "summary": {}}


class FakeMonitoringService:
    def __init__(self):
        self.probe_results = []

    def record_probe_results(self, **kwargs):
        self.probe_results.append(kwargs)


class FailingMonitoringService:
    def record_probe_results(self, **kwargs):
        raise RuntimeError("boom")


def _client_with_tool_reliability(repo=None, service=None):
    app.dependency_overrides[require_authenticated_session] = lambda: object()
    if repo is not None:
        app.dependency_overrides[get_account_copilot_tool_reliability_repository] = lambda: repo
    if service is not None:
        app.dependency_overrides[get_account_copilot_tool_reliability_service] = lambda: service
    app.dependency_overrides[get_account_copilot_monitoring_service] = lambda: FakeMonitoringService()
    return TestClient(app)


def _sample_probe_results():
    return [
        {
            "id": "r1",
            "probe_run_id": "probe_run_latest",
            "tool_name": "ibkr_positions",
            "tool_domain": "ibkr",
            "category": "portfolio",
            "probe_type": "schema",
            "status": "pass",
            "ok": True,
            "latency_ms": 10,
            "created_at": "2026-05-24T01:00:00+00:00",
            "arguments_preview": {},
            "data_empty": False,
            "data_size": 10,
            "data_limitations": [],
            "metadata": {},
        },
        {
            "id": "r2",
            "probe_run_id": "probe_run_latest",
            "tool_name": "longbridge_quote",
            "tool_domain": "longbridge",
            "category": "quote",
            "probe_type": "invoke",
            "status": "fail",
            "ok": False,
            "latency_ms": 200,
            "created_at": "2026-05-24T02:00:00+00:00",
            "arguments_preview": {"symbol": "AMD.US"},
            "data_empty": True,
            "data_size": 0,
            "data_limitations": [],
            "metadata": {},
        },
        {
            "id": "r3",
            "probe_run_id": "probe_run_latest",
            "tool_name": "review_skill",
            "tool_domain": "skill",
            "category": "skill",
            "probe_type": "schema",
            "status": "partial",
            "ok": False,
            "latency_ms": None,
            "created_at": "2026-05-24T01:30:00+00:00",
            "arguments_preview": {},
            "data_empty": False,
            "data_size": 1,
            "data_limitations": [],
            "metadata": {},
        },
        {
            "id": "r4",
            "probe_run_id": "probe_run_latest",
            "tool_name": "agent_case",
            "tool_domain": "agent",
            "category": "agent_eval",
            "probe_type": "agent_eval",
            "status": "skipped",
            "ok": False,
            "latency_ms": 0,
            "created_at": "2026-05-24T01:15:00+00:00",
            "arguments_preview": {},
            "data_empty": False,
            "data_size": 1,
            "data_limitations": [],
            "metadata": {},
        },
    ]


def test_probe_result_repository_writes_document():
    es = FakeES()
    repo = AccountCopilotToolReliabilityRepository(es, Settings())
    doc = repo.create_result(
        {
            "probe_run_id": "run1",
            "tool_name": "tool",
            "tool_domain": "ibkr",
            "category": "x",
            "probe_type": "schema",
            "status": "pass",
            "ok": True,
        }
    )
    assert doc["id"] in es.docs
    assert es.created[0][0] == "probe-index"


def test_latest_tool_reliability_api_returns_empty_aggregate():
    client = _client_with_tool_reliability(repo=FakeReliabilityRepository())
    try:
        response = client.get("/api/agent/account-copilot/tool-reliability/latest")
        assert response.status_code == 200
        data = response.json()
        assert data["probe_run_id"] is None
        assert data["total"] == 0
        assert data["results"] == []
        assert data["domain_stats"] == {}
        assert data["success_rate"] == 0
    finally:
        app.dependency_overrides.clear()


def test_latest_tool_reliability_api_returns_aggregate_stats():
    results = _sample_probe_results()
    client = _client_with_tool_reliability(
        repo=FakeReliabilityRepository(results=results, latest_probe_run_id="probe_run_latest")
    )
    try:
        response = client.get("/api/agent/account-copilot/tool-reliability/latest")
        assert response.status_code == 200
        data = response.json()
        assert data["probe_run_id"] == "probe_run_latest"
        assert data["total"] == 4
        assert data["pass"] == 1
        assert data["fail"] == 1
        assert data["partial"] == 1
        assert data["skipped"] == 1
        assert data["success_rate"] == 0.25
        assert data["p95_latency_ms"] == 200
        assert data["last_run_at"] == "2026-05-24T02:00:00+00:00"
        assert data["domain_stats"]["ibkr"]["success_rate"] == 1
        assert data["domain_stats"]["longbridge"]["fail"] == 1
        assert data["domain_stats"]["agent"]["avg_latency_ms"] == 0
        assert data["results"] == results
    finally:
        app.dependency_overrides.clear()


def test_probe_tool_reliability_api_returns_aggregate_stats():
    results = _sample_probe_results()
    monitoring = FakeMonitoringService()
    client = _client_with_tool_reliability(service=FakeReliabilityService(results))
    app.dependency_overrides[get_account_copilot_monitoring_service] = lambda: monitoring
    try:
        response = client.post(
            "/api/agent/account-copilot/tool-reliability/probe",
            json={
                "include_live": False,
                "include_longbridge": False,
                "include_ibkr": False,
                "include_agent_eval": False,
                "symbol": "AMD.US",
                "keyword": "AMD",
                "max_tools": 10,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["probe_run_id"] == "probe_run_test"
        assert data["total"] == 4
        assert data["pass"] == 1
        assert data["fail"] == 1
        assert data["partial"] == 1
        assert data["skipped"] == 1
        assert data["success_rate"] == 0.25
        assert data["p95_latency_ms"] == 200
        assert data["last_run_at"] == "2026-05-24T02:00:00+00:00"
        assert set(data["domain_stats"]) == {"ibkr", "longbridge", "skill", "agent"}
        assert data["results"] == results
        assert monitoring.probe_results[0]["probe_run_id"] == "probe_run_test"
        assert monitoring.probe_results[0]["results"] == results
    finally:
        app.dependency_overrides.clear()


def test_probe_monitoring_write_failure_does_not_break_probe_api():
    results = _sample_probe_results()
    client = _client_with_tool_reliability(service=FakeReliabilityService(results))
    app.dependency_overrides[get_account_copilot_monitoring_service] = lambda: FailingMonitoringService()
    try:
        response = client.post(
            "/api/agent/account-copilot/tool-reliability/probe",
            json={
                "include_live": False,
                "include_longbridge": False,
                "include_ibkr": False,
                "include_agent_eval": False,
                "symbol": "AMD.US",
                "keyword": "AMD",
                "max_tools": 10,
            },
        )
        assert response.status_code == 200
        assert response.json()["probe_run_id"] == "probe_run_test"
    finally:
        app.dependency_overrides.clear()


def test_build_safe_longbridge_arguments_for_public_schema():
    args, reason = build_safe_longbridge_arguments(
        "quote",
        {"type": "object", "properties": {"symbol": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["symbol"]},
        symbol="AMD.US",
        keyword="AMD",
    )
    assert reason is None
    assert args == {"symbol": "AMD.US", "limit": 5}


def test_build_safe_longbridge_arguments_skips_unknown_required():
    args, reason = build_safe_longbridge_arguments("x", {"type": "object", "properties": {}, "required": ["mystery"]})
    assert args is None
    assert reason == "SKIPPED_UNSUPPORTED_ARGS"


def test_forbidden_private_write_tools_are_not_called():
    adapter = FakeAdapter()
    service = AccountCopilotToolReliabilityService(None, AccountCopilotToolRegistry(), build_default_skill_registry(), adapter)
    results = service.probe_longbridge_tools("probe")
    called_names = [name for name, _args in adapter.calls]
    assert "submit_order" not in called_names
    assert "quote" in called_names
    assert any(result["tool_name"] == "custom_public" and result["status"] == "skipped" for result in results)


def test_longbridge_adapter_unavailable_is_fail_for_live_probe():
    service = AccountCopilotToolReliabilityService(None, AccountCopilotToolRegistry(), build_default_skill_registry(), None)
    result = service.probe_longbridge_tools("probe")[0]
    assert result["status"] == "fail"
    assert result["error_code"] == "LONGBRIDGE_ADAPTER_UNAVAILABLE"


def test_sensitive_keys_do_not_enter_results():
    registry = AccountCopilotToolRegistry()

    def handler(**kwargs):
        return {"ok": False, "data": {}, "message": "authorization token failed", "data_limitations": []}

    registry.register(AccountCopilotToolSpec(name="ibkr_x", description="x", schema={"name": "ibkr_x", "parameters": {}}, handler=handler))
    service = AccountCopilotToolReliabilityService(None, registry, build_default_skill_registry())
    result = service.probe_ibkr_tools("probe")[0]
    assert "token" not in (result["error_message"] or "").lower()
    assert "authorization" not in (result["error_message"] or "").lower()


def test_single_tool_failure_does_not_stop_probe():
    registry = AccountCopilotToolRegistry()
    registry.register(AccountCopilotToolSpec(name="ibkr_bad", description="bad", schema={"name": "ibkr_bad", "parameters": {}}, handler=lambda: (_ for _ in ()).throw(RuntimeError("boom"))))
    registry.register(AccountCopilotToolSpec(name="ibkr_good", description="good", schema={"name": "ibkr_good", "parameters": {}}, handler=lambda: {"ok": True, "data": {"x": 1}, "data_limitations": []}))
    service = AccountCopilotToolReliabilityService(None, registry, build_default_skill_registry())
    results = service.probe_ibkr_tools("probe")
    assert {result["status"] for result in results} == {"fail", "pass"}


def test_success_rate_and_p95_latency_stats():
    summary = summarize_probe_results(
        [
            {"tool_name": "a", "status": "pass", "latency_ms": 10},
            {"tool_name": "b", "status": "fail", "latency_ms": 100},
            {"tool_name": "c", "status": "skipped", "latency_ms": 0},
        ]
    )
    assert summary["pass_count"] == 1
    assert summary["fail_count"] == 1
    assert summary["p95_latency_ms"] == 100


def test_agent_eval_detects_forbidden_tool_called_constant():
    assert "submit_order" in FORBIDDEN_AGENT_TOOL_PATTERNS


def test_probe_script_dry_run_generates_report(tmp_path):
    report_path = tmp_path / "tool_reliability.md"
    script = Path(__file__).resolve().parents[2] / "scripts" / "account_copilot_tool_reliability_probe.py"
    result = subprocess.run(
        [sys.executable, str(script), "--local", "--report-path", str(report_path)],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    text = report_path.read_text(encoding="utf-8")
    assert "Account Copilot Tool Reliability Report" in text
    assert "token" not in text.lower()
