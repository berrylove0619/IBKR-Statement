from unittest.mock import MagicMock

from app.agents.risk_assessment_graph.runner import RiskAssessmentGraphRunner
from app.schemas.risk_assessment import RiskAssessmentResult
from app.services.risk_assessment_agent import RiskAssessmentAgent


def test_health_uses_get_active_provider_and_returns_langgraph_contract() -> None:
    llm_service = MagicMock()
    llm_service.get_active_provider.return_value = object()
    agent = RiskAssessmentAgent(MagicMock(), llm_service, MagicMock(), mcp_adapter=None)

    health = agent.health()

    llm_service.get_active_provider.assert_called_once()
    assert health["agent_mode"] == "risk_assessment_langgraph_v1"
    assert health["graph_version"] == "risk_assessment_graph_v1"
    assert health["account_data_source"] == "IBKR_ONLY"


def test_graph_exception_returns_schema_valid_fallback_document() -> None:
    runner = RiskAssessmentGraphRunner(MagicMock(), MagicMock(), MagicMock())
    runner.graph = MagicMock()
    runner.graph.invoke.side_effect = RuntimeError("graph exploded")
    runner.deps.repository.save_assessment.side_effect = RuntimeError("ES down")

    document = runner.analyze(question="risk?")
    result = RiskAssessmentResult(**document)

    assert result.fallback_used is True
    assert result.metadata["agent_mode"] == "risk_assessment_langgraph_v1"
    assert result.metadata["graph_version"] == "risk_assessment_graph_v1"
    assert any("save_failed" in item for item in result.data_limitations)
