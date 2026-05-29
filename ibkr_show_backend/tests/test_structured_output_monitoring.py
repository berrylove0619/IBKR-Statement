"""Tests for structured output monitoring service and runtime integration."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.agents.structured_output.contracts import StructuredOutputContract
from app.agents.structured_output.runtime import StructuredOutputRuntime
from app.services.account_copilot.monitoring_service import AccountCopilotMonitoringService


def _make_contract() -> StructuredOutputContract:
    from pydantic import BaseModel

    class TestModel(BaseModel):
        value: str

    return StructuredOutputContract(
        name="test_contract",
        agent_name="test_agent",
        node_name="test_node",
        output_model=TestModel,
        schema_hint={"type": "object"},
        examples=[{"value": "ok"}],
        max_repair_attempts=1,
        repair_enabled=False,
        fallback_enabled=False,
    )


class TestRecordStructuredOutputEvent:
    def test_record_success(self):
        mock_repo = MagicMock()
        mock_repo.create_structured_output_metric.return_value = {"id": "test_1"}
        service = AccountCopilotMonitoringService(mock_repo)
        result = service.record_structured_output_event({
            "contract_name": "test_contract",
            "agent_name": "test_agent",
            "node_name": "test_node",
            "ok": True,
            "schema_validation_passed": True,
            "repaired": False,
            "repair_attempts": 0,
            "fallback_used": False,
            "output_model_name": "TestModel",
        })
        assert result is not None
        mock_repo.create_structured_output_metric.assert_called_once()
        call_args = mock_repo.create_structured_output_metric.call_args[0][0]
        assert call_args["contract_name"] == "test_contract"
        assert call_args["ok"] is True

    def test_record_failure_does_not_raise(self):
        mock_repo = MagicMock()
        mock_repo.create_structured_output_metric.side_effect = Exception("ES down")
        service = AccountCopilotMonitoringService(mock_repo)
        result = service.record_structured_output_event({"contract_name": "test"})
        assert result is None


class TestQueryStructuredOutputEvents:
    def test_query_returns_empty_when_no_index(self):
        mock_repo = MagicMock()
        mock_repo.query_recent_structured_output_events.return_value = []
        service = AccountCopilotMonitoringService(mock_repo)
        result = service.query_recent_structured_output_events(limit=10)
        assert result["items"] == []

    def test_query_normalizes_fields(self):
        mock_repo = MagicMock()
        mock_repo.query_recent_structured_output_events.return_value = [
            {
                "id": "so_1",
                "created_at": "2026-05-28T00:00:00Z",
                "source": "runtime",
                "agent_name": "account_copilot",
                "node_name": "planner",
                "contract_name": "account_copilot_planner",
                "run_id": "run_1",
                "task_id": "",
                "session_id": "sess_1",
                "ok": True,
                "schema_validation_passed": True,
                "repaired": False,
                "repair_attempts": 0,
                "fallback_used": False,
                "error_code": None,
                "error_message": None,
                "output_model_name": "CopilotPlannerAction",
            },
            {
                "id": "so_2",
                "created_at": "2026-05-28T00:01:00Z",
                "source": "runtime",
                "agent_name": "account_copilot",
                "node_name": "planner",
                "contract_name": "account_copilot_planner",
                "run_id": "run_2",
                "ok": False,
                "schema_validation_passed": False,
                "repaired": True,
                "repair_attempts": 1,
                "fallback_used": False,
                "error_code": "LLM_SCHEMA_INVALID",
                "error_message": "validation failed",
                "output_model_name": "CopilotPlannerAction",
            },
        ]
        service = AccountCopilotMonitoringService(mock_repo)
        result = service.query_recent_structured_output_events(limit=10)
        items = result["items"]
        assert len(items) == 2
        # Items are reversed to chronological order; rolling rates use current + prior 9
        assert items[0]["rolling_success_rate_10"] == 0.0  # so_2: ok=False, window=[so_2]
        assert items[1]["rolling_success_rate_10"] == 0.5  # so_1: ok=True, window=[so_2, so_1]
        assert items[0]["rolling_repair_rate_10"] == 1.0
        assert items[1]["rolling_repair_rate_10"] == 0.5
        assert items[1]["rolling_repair_rate_10"] == 0.5


class TestRollingRates:
    def test_rolling_rates_correct(self):
        mock_repo = MagicMock()
        mock_repo.query_recent_structured_output_events.return_value = [
            {"id": f"so_{i}", "created_at": f"2026-05-28T00:{i:02d}:00Z", "ok": i % 3 != 0, "repaired": i % 3 == 0, "fallback_used": False}
            for i in range(15)
        ]
        service = AccountCopilotMonitoringService(mock_repo)
        result = service.query_recent_structured_output_events(limit=15)
        items = result["items"]
        last = items[-1]
        window = items[-10:]
        expected_ok = sum(1 for item in window if item["ok"]) / 10
        expected_repair = sum(1 for item in window if item["repaired"]) / 10
        assert abs(last["rolling_success_rate_10"] - expected_ok) < 0.01
        assert abs(last["rolling_repair_rate_10"] - expected_repair) < 0.01
        assert last["rolling_window_size"] == 10

    def test_rolling_rates_insufficient_data(self):
        mock_repo = MagicMock()
        mock_repo.query_recent_structured_output_events.return_value = [
            {"id": "so_1", "created_at": "2026-05-28T00:00:00Z", "ok": True, "repaired": False, "fallback_used": False},
            {"id": "so_2", "created_at": "2026-05-28T00:01:00Z", "ok": False, "repaired": True, "fallback_used": False},
        ]
        service = AccountCopilotMonitoringService(mock_repo)
        result = service.query_recent_structured_output_events(limit=10)
        items = result["items"]
        assert items[0]["rolling_window_size"] == 1
        assert items[1]["rolling_window_size"] == 2
        assert items[1]["rolling_success_rate_10"] == 0.5


class TestRuntimeMonitoringIntegration:
    def test_runtime_records_monitoring_on_success(self):
        mock_llm = MagicMock()
        mock_monitoring = MagicMock()
        mock_monitoring.record_structured_output_event = MagicMock()
        runtime = StructuredOutputRuntime(mock_llm, monitoring_service=mock_monitoring)
        contract = _make_contract()
        result = runtime.parse_validate_repair('{"value": "hello"}', contract)
        assert result.ok is True
        mock_monitoring.record_structured_output_event.assert_called_once()
        metadata = mock_monitoring.record_structured_output_event.call_args[0][0]
        assert metadata["contract_name"] == "test_contract"
        assert metadata["ok"] is True

    def test_runtime_monitoring_failure_does_not_affect_result(self):
        mock_llm = MagicMock()
        mock_monitoring = MagicMock()
        mock_monitoring.record_structured_output_event.side_effect = Exception("ES down")
        runtime = StructuredOutputRuntime(mock_llm, monitoring_service=mock_monitoring)
        contract = _make_contract()
        result = runtime.parse_validate_repair('{"value": "hello"}', contract)
        assert result.ok is True

    def test_runtime_passes_ids_to_metadata(self):
        mock_llm = MagicMock()
        mock_monitoring = MagicMock()
        mock_monitoring.record_structured_output_event = MagicMock()
        runtime = StructuredOutputRuntime(mock_llm, monitoring_service=mock_monitoring)
        contract = _make_contract()
        result = runtime.parse_validate_repair(
            '{"value": "hello"}',
            contract,
            run_id="run_123",
            session_id="sess_456",
            task_id="task_789",
        )
        assert result.ok is True
        assert result.metadata["run_id"] == "run_123"
        assert result.metadata["session_id"] == "sess_456"
        assert result.metadata["task_id"] == "task_789"

    def test_runtime_no_monitoring_service(self):
        mock_llm = MagicMock()
        runtime = StructuredOutputRuntime(mock_llm, monitoring_service=None)
        contract = _make_contract()
        result = runtime.parse_validate_repair('{"value": "hello"}', contract)
        assert result.ok is True

    def test_runtime_monitoring_without_method(self):
        mock_llm = MagicMock()
        mock_monitoring = MagicMock(spec=[])  # no record_structured_output_event
        runtime = StructuredOutputRuntime(mock_llm, monitoring_service=mock_monitoring)
        contract = _make_contract()
        result = runtime.parse_validate_repair('{"value": "hello"}', contract)
        assert result.ok is True

    def test_generate_llm_failure_records_monitoring(self):
        mock_llm = MagicMock()
        mock_llm.chat_with_metadata.side_effect = RuntimeError("LLM down")
        mock_monitoring = MagicMock()
        mock_monitoring.record_structured_output_event = MagicMock()
        runtime = StructuredOutputRuntime(mock_llm, monitoring_service=mock_monitoring)
        contract = _make_contract()
        result = runtime.generate(
            [{"role": "user", "content": "test"}],
            contract,
            run_id="r1",
            session_id="s1",
            task_id="t1",
        )
        assert result.ok is False
        assert result.error_code == "LLM_CALL_FAILED"
        mock_monitoring.record_structured_output_event.assert_called_once()
        metadata = mock_monitoring.record_structured_output_event.call_args[0][0]
        assert metadata["contract_name"] == "test_contract"
        assert metadata["error_code"] == "LLM_CALL_FAILED"
        assert metadata["run_id"] == "r1"
        assert metadata["session_id"] == "s1"
        assert metadata["task_id"] == "t1"


class TestMetadataFilter:
    def test_only_allowed_keys_in_metadata(self):
        mock_repo = MagicMock()
        mock_repo.create_structured_output_metric.return_value = {"id": "test_1"}
        service = AccountCopilotMonitoringService(mock_repo)
        service.record_structured_output_event({
            "contract_name": "test",
            "ok": True,
            "monitoring_recorded": True,
            "fallback_reason": "some reason",
            "initial_error_code": "LLM_SCHEMA_INVALID",
            "random_none": None,
            "huge_context": {"big": "data"},
            "raw_response": "full text here",
            "trace": [{"event": "x"}],
        })
        call_args = mock_repo.create_structured_output_metric.call_args[0][0]
        meta = call_args["metadata"]
        assert "monitoring_recorded" in meta
        assert "fallback_reason" in meta
        assert "initial_error_code" in meta
        assert "random_none" not in meta
        assert "huge_context" not in meta
        assert "raw_response" not in meta
        assert "trace" not in meta

    def test_allowed_keys_with_none_value_pass_through(self):
        mock_repo = MagicMock()
        mock_repo.create_structured_output_metric.return_value = {"id": "test_1"}
        service = AccountCopilotMonitoringService(mock_repo)
        service.record_structured_output_event({
            "contract_name": "test",
            "fallback_reason": None,
            "initial_error_code": None,
        })
        call_args = mock_repo.create_structured_output_metric.call_args[0][0]
        meta = call_args["metadata"]
        assert "fallback_reason" in meta
        assert meta["fallback_reason"] is None
        assert "initial_error_code" in meta
