"""Tests for the LangGraph-based risk assessment agent."""

import inspect
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from app.agents.risk_assessment_graph.cards import (
    AccountRiskSnapshot,
    ConcentrationRiskCard,
    CorrelationRiskCard,
    EarningsCalendarRiskCard,
    RiskAssessmentCardPack,
    RiskLevel,
    SectorThemeExposureCard,
    StressTestCard,
    PositionEntry,
    classify_symbol_theme,
)
from app.agents.risk_assessment_graph.state import RiskAssessmentGraphState


# === Fixtures ===

def _make_position(symbol, pct, value=10000.0):
    return PositionEntry(
        symbol=symbol,
        normalized_symbol=f"{symbol}.US",
        quantity=100,
        avg_cost=100.0,
        current_price=value / 100,
        market_value=value,
        position_pct=pct,
    )


def _make_snapshot(positions=None, net_liquidation=100000.0, cash=20000.0):
    if positions is None:
        positions = [
            _make_position("AAPL", 0.25, 25000),
            _make_position("NVDA", 0.20, 20000),
            _make_position("MSFT", 0.15, 15000),
            _make_position("GOOGL", 0.10, 10000),
            _make_position("AMZN", 0.08, 8000),
        ]
    total = sum(p.market_value for p in positions)
    top3_pct = sum(p.position_pct for p in positions[:3])
    top5_pct = sum(p.position_pct for p in positions[:5])
    return AccountRiskSnapshot(
        net_liquidation=net_liquidation,
        cash=cash,
        deployable_liquidity=cash,
        positions=positions,
        total_position_value=total,
        top_positions=[{"symbol": p.symbol, "position_value": p.market_value, "position_pct": p.position_pct} for p in positions[:5]],
        position_count=len(positions),
        largest_position_pct=positions[0].position_pct if positions else 0,
        top_3_position_pct=top3_pct,
        top_5_position_pct=top5_pct,
        cash_pct=round(cash / net_liquidation, 6) if net_liquidation else 0,
        margin_usage_pct=0.0,
    )


# === Test: Graph structure ===

class TestGraphStructure:

    def test_graph_has_parallel_edges(self):
        from app.agents.risk_assessment_graph.graph import build_risk_assessment_graph, RiskAssessmentGraphDeps

        deps = RiskAssessmentGraphDeps(
            account_facts_builder=MagicMock(),
            repository=MagicMock(),
            llm_service=MagicMock(),
        )
        graph = build_risk_assessment_graph(deps)
        graph_obj = graph.get_graph()
        node_names = list(graph_obj.nodes.keys())
        assert "build_account_risk_facts" in node_names
        assert "position_concentration" in node_names
        assert "sector_theme_exposure" in node_names
        assert "correlation" in node_names
        assert "earnings_calendar_risk" in node_names
        assert "stress_test" in node_names
        assert "risk_report_composer" in node_names
        assert "persist_risk_assessment" in node_names

    def test_build_facts_fans_out_to_four(self):
        from app.agents.risk_assessment_graph.graph import build_risk_assessment_graph, RiskAssessmentGraphDeps

        deps = RiskAssessmentGraphDeps(
            account_facts_builder=MagicMock(),
            repository=MagicMock(),
            llm_service=MagicMock(),
        )
        graph = build_risk_assessment_graph(deps)
        graph_obj = graph.get_graph()

        edges_from_facts = [e.target for e in graph_obj.edges if e.source == "build_account_risk_facts"]
        assert "position_concentration" in edges_from_facts
        assert "sector_theme_exposure" in edges_from_facts
        assert "correlation" in edges_from_facts
        assert "earnings_calendar_risk" in edges_from_facts

    def test_four_nodes_fan_in_to_stress_test(self):
        from app.agents.risk_assessment_graph.graph import build_risk_assessment_graph, RiskAssessmentGraphDeps

        deps = RiskAssessmentGraphDeps(
            account_facts_builder=MagicMock(),
            repository=MagicMock(),
            llm_service=MagicMock(),
        )
        graph = build_risk_assessment_graph(deps)
        graph_obj = graph.get_graph()

        edges_to_stress = [e.source for e in graph_obj.edges if e.target == "stress_test"]
        assert "position_concentration" in edges_to_stress
        assert "sector_theme_exposure" in edges_to_stress
        assert "correlation" in edges_to_stress
        assert "earnings_calendar_risk" in edges_to_stress


# === Test: Reducer safety ===

class TestReducerSafety:

    def test_node_traces_merged_from_parallel_nodes(self):
        from app.agents.graph.base_state import _merge_trace_list
        left = [{"node_name": "a", "status": "success"}]
        right = [{"node_name": "b", "status": "success"}]
        result = _merge_trace_list(left, right)
        assert len(result) == 2

    def test_data_limitations_merged(self):
        from app.agents.graph.base_state import _merge_str_list
        left = ["limit_a"]
        right = ["limit_b", "limit_a"]
        result = _merge_str_list(left, right)
        assert "limit_a" in result
        assert "limit_b" in result


# === Test: Theme classification ===

class TestThemeClassification:

    def test_semiconductor_classification(self):
        result = classify_symbol_theme("NVDA")
        assert result["semiconductor"] is True
        assert result["ai"] is True

    def test_china_classification(self):
        result = classify_symbol_theme("BABA")
        assert result["china"] is True

    def test_mega_cap_classification(self):
        result = classify_symbol_theme("AAPL")
        assert result["mega_cap_tech"] is True

    def test_unknown_symbol(self):
        result = classify_symbol_theme("XYZ123")
        assert result["semiconductor"] is False
        assert result["ai"] is False
        assert result["china"] is False
        assert result["mega_cap_tech"] is False

    def test_cash_equivalent(self):
        result = classify_symbol_theme("SGOV")
        assert result["cash_equivalent"] is True


# === Test: Concentration risk ===

class TestConcentrationRisk:

    def test_low_concentration(self):
        from app.agents.risk_assessment_graph.nodes import make_position_concentration_node

        snapshot = _make_snapshot(positions=[
            _make_position("AAPL", 0.08, 8000),
            _make_position("NVDA", 0.07, 7000),
            _make_position("MSFT", 0.06, 6000),
        ])
        node_fn = make_position_concentration_node(MagicMock())
        result = node_fn({"account_risk_snapshot": snapshot, "node_traces": []})
        card = result["concentration_card"]
        assert card.risk_level == RiskLevel.LOW
        assert card.score < 7

    def test_extreme_concentration(self):
        from app.agents.risk_assessment_graph.nodes import make_position_concentration_node

        snapshot = _make_snapshot(positions=[
            _make_position("AAPL", 0.55, 55000),
            _make_position("NVDA", 0.10, 10000),
        ])
        node_fn = make_position_concentration_node(MagicMock())
        result = node_fn({"account_risk_snapshot": snapshot, "node_traces": []})
        card = result["concentration_card"]
        assert card.risk_level in (RiskLevel.HIGH, RiskLevel.EXTREME)
        assert card.score >= 14

    def test_high_top3_concentration(self):
        from app.agents.risk_assessment_graph.nodes import make_position_concentration_node

        snapshot = _make_snapshot(positions=[
            _make_position("A", 0.30, 30000),
            _make_position("B", 0.25, 25000),
            _make_position("C", 0.20, 20000),
            _make_position("D", 0.05, 5000),
        ])
        node_fn = make_position_concentration_node(MagicMock())
        result = node_fn({"account_risk_snapshot": snapshot, "node_traces": []})
        card = result["concentration_card"]
        assert card.top_3_position_pct > 0.70
        assert len(card.concentration_findings) > 0


# === Test: Stress test ===

class TestStressTest:

    def test_market_minus_20_scenario(self):
        from app.agents.risk_assessment_graph.nodes import make_stress_test_node

        snapshot = _make_snapshot(positions=[
            _make_position("AAPL", 0.50, 50000),
            _make_position("NVDA", 0.30, 30000),
        ])
        node_fn = make_stress_test_node(MagicMock())
        result = node_fn({"account_risk_snapshot": snapshot, "node_traces": []})
        card = result["stress_test_card"]

        # market_minus_20: total 80000 * 0.20 = 16000
        market_20 = next(s for s in card.scenarios if s["scenario_name"] == "market_minus_20")
        assert market_20["estimated_loss_amount"] == 16000.0
        assert market_20["estimated_drawdown_pct"] == pytest.approx(0.16, abs=0.01)

    def test_largest_position_minus_30(self):
        from app.agents.risk_assessment_graph.nodes import make_stress_test_node

        snapshot = _make_snapshot(positions=[
            _make_position("AAPL", 0.50, 50000),
            _make_position("NVDA", 0.30, 30000),
        ])
        node_fn = make_stress_test_node(MagicMock())
        result = node_fn({"account_risk_snapshot": snapshot, "node_traces": []})
        card = result["stress_test_card"]

        largest = next(s for s in card.scenarios if s["scenario_name"] == "largest_position_minus_30")
        assert largest["estimated_loss_amount"] == 15000.0  # 50000 * 0.30

    def test_worst_case_drawdown(self):
        from app.agents.risk_assessment_graph.nodes import make_stress_test_node

        snapshot = _make_snapshot(positions=[
            _make_position("AAPL", 0.50, 50000),
            _make_position("NVDA", 0.30, 30000),
        ])
        node_fn = make_stress_test_node(MagicMock())
        result = node_fn({"account_risk_snapshot": snapshot, "node_traces": []})
        card = result["stress_test_card"]

        # market_minus_20 is worst: 80000*0.20 = 16000, drawdown = 16000/100000 = 0.16
        assert card.worst_case_drawdown_pct == pytest.approx(0.16, abs=0.01)
        assert card.worst_case_loss_amount == 16000.0

    def test_semiconductor_scenario_uses_theme(self):
        from app.agents.risk_assessment_graph.nodes import make_stress_test_node

        snapshot = _make_snapshot(positions=[
            _make_position("NVDA", 0.30, 30000),
            _make_position("AMD", 0.20, 20000),
            _make_position("AAPL", 0.20, 20000),
        ])
        sector_card = SectorThemeExposureCard(
            theme_exposures={"semiconductor": {"NVDA.US": 0.30, "AMD.US": 0.20}},
        )
        node_fn = make_stress_test_node(MagicMock())
        result = node_fn({"account_risk_snapshot": snapshot, "sector_theme_card": sector_card, "node_traces": []})
        card = result["stress_test_card"]

        semi = next(s for s in card.scenarios if s["scenario_name"] == "semiconductor_minus_30")
        # NVDA: 30000*0.30=9000, AMD: 20000*0.30=6000, AAPL: 20000*0.10=2000 => 17000
        assert semi["estimated_loss_amount"] == 17000.0


# === Test: Composer ===

class TestRiskReportComposer:

    def test_overall_risk_score_and_level(self):
        from app.agents.risk_assessment_graph.nodes import make_risk_report_composer_node

        conc = ConcentrationRiskCard(score=5, max_score=25, risk_level=RiskLevel.LOW)
        sector = SectorThemeExposureCard(score=4, max_score=20, risk_level=RiskLevel.LOW)
        corr = CorrelationRiskCard(score=4, max_score=20, risk_level=RiskLevel.LOW)
        earn = EarningsCalendarRiskCard(score=3, max_score=15, risk_level=RiskLevel.LOW)
        stress = StressTestCard(score=4, max_score=20, risk_level=RiskLevel.LOW)

        node_fn = make_risk_report_composer_node(MagicMock())
        state = {
            "account_risk_snapshot": _make_snapshot(),
            "concentration_card": conc,
            "sector_theme_card": sector,
            "correlation_card": corr,
            "earnings_calendar_card": earn,
            "stress_test_card": stress,
            "node_traces": [],
        }
        result = node_fn(state)
        report = result["risk_report"]
        assert 0 <= report["overall_risk_score"] <= 100
        assert report["risk_level"] in (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.EXTREME)

    def test_data_insufficient_biases_toward_medium(self):
        from app.agents.risk_assessment_graph.nodes import make_risk_report_composer_node

        conc = ConcentrationRiskCard(score=0, max_score=25, evidence_quality="low")
        sector = SectorThemeExposureCard(score=0, max_score=20, evidence_quality="low")

        node_fn = make_risk_report_composer_node(MagicMock())
        state = {
            "account_risk_snapshot": _make_snapshot(),
            "concentration_card": conc,
            "sector_theme_card": sector,
            "correlation_card": None,
            "earnings_calendar_card": None,
            "stress_test_card": None,
            "node_traces": [],
        }
        result = node_fn(state)
        report = result["risk_report"]
        assert report["risk_level"] != RiskLevel.LOW
        assert report["confidence"] == "low"

    def test_high_concentration_drives_up_risk(self):
        from app.agents.risk_assessment_graph.nodes import make_risk_report_composer_node

        conc = ConcentrationRiskCard(score=20, max_score=25, risk_level=RiskLevel.HIGH,
                                     key_risks=["集中度高"])
        sector = SectorThemeExposureCard(score=4, max_score=20)
        corr = CorrelationRiskCard(score=4, max_score=20)
        earn = EarningsCalendarRiskCard(score=3, max_score=15)
        stress = StressTestCard(score=4, max_score=20)

        node_fn = make_risk_report_composer_node(MagicMock())
        state = {
            "account_risk_snapshot": _make_snapshot(),
            "concentration_card": conc,
            "sector_theme_card": sector,
            "correlation_card": corr,
            "earnings_calendar_card": earn,
            "stress_test_card": stress,
            "node_traces": [],
        }
        result = node_fn(state)
        report = result["risk_report"]
        assert report["overall_risk_score"] > 25


# === Test: Full execution semantics ===

class TestFanInExecutionSemantics:

    def test_parallel_nodes_each_run_once_and_stress_waits(self):
        """Run real graph with mocked sub-components, verify execution semantics."""
        from app.agents.risk_assessment_graph.runner import RiskAssessmentGraphRunner

        snapshot = _make_snapshot()
        mock_builder = MagicMock()
        mock_builder.build.return_value = snapshot

        captured_doc = {}
        def capture_save(doc):
            captured_doc.update(doc)
            doc["id"] = "risk-test-id"
            return doc
        mock_repo = MagicMock()
        mock_repo.save_assessment.side_effect = capture_save

        mock_adapter = MagicMock()
        mock_adapter.client = MagicMock()
        type(mock_adapter.client).enabled = PropertyMock(return_value=False)
        mock_llm = MagicMock()

        runner = RiskAssessmentGraphRunner(
            account_facts_builder=mock_builder,
            repository=mock_repo,
            llm_service=mock_llm,
            mcp_adapter=mock_adapter,
        )

        result = runner.analyze()

        # save called once
        assert mock_repo.save_assessment.call_count == 1

        # Not fallback
        assert captured_doc.get("fallback_used") is not True

        # Metadata
        assert captured_doc["metadata"]["agent_mode"] == "risk_assessment_langgraph_v1"
        assert captured_doc["metadata"]["graph_version"] == "risk_assessment_graph_v1"

        # run_trace has all 8 nodes
        run_trace = captured_doc["run_trace"]
        node_names = [x["node_name"] for x in run_trace]
        expected = [
            "build_account_risk_facts",
            "position_concentration", "sector_theme_exposure", "correlation", "earnings_calendar_risk",
            "stress_test",
            "risk_report_composer", "persist_risk_assessment",
        ]
        for name in expected:
            assert name in node_names, f"Missing node '{name}'"

        # stress_test and persist each appear once
        assert node_names.count("stress_test") == 1
        assert node_names.count("persist_risk_assessment") == 1

        # stress_test appears after all 4 parallel nodes
        stress_idx = node_names.index("stress_test")
        for name in ("position_concentration", "sector_theme_exposure", "correlation", "earnings_calendar_risk"):
            assert node_names.index(name) < stress_idx

        # risk_report has overall_risk_score and risk_level
        assert "overall_risk_score" in captured_doc
        assert "risk_level" in captured_doc

        # card_pack has all cards
        card_pack = captured_doc["card_pack"]
        assert card_pack["concentration_card"] is not None
        assert card_pack["stress_test_card"] is not None

    def test_fallback_on_graph_error(self):
        """Runner should return medium-risk fallback on graph failure."""
        from app.agents.risk_assessment_graph.runner import RiskAssessmentGraphRunner

        mock_builder = MagicMock()
        mock_builder.build.side_effect = RuntimeError("ES down")
        mock_repo = MagicMock()
        mock_repo.save_assessment.return_value = {"id": "fallback-1", "fallback_used": True, "risk_level": "medium"}

        runner = RiskAssessmentGraphRunner(
            account_facts_builder=mock_builder,
            repository=mock_repo,
            llm_service=MagicMock(),
        )

        result = runner.analyze()
        assert result is not None
        assert result.get("risk_level") == "medium"


# === Test: Version constants ===

class TestVersions:

    def test_risk_assessment_constants_exist(self):
        from app.agents.versions import (
            RISK_ASSESSMENT_AGENT_MODE_LANGGRAPH,
            RISK_ASSESSMENT_GRAPH_VERSION,
            RISK_ASSESSMENT_GRAPH_SCHEMA_VERSION,
            RISK_ASSESSMENT_CARD_SCHEMA_VERSION,
        )
        assert RISK_ASSESSMENT_AGENT_MODE_LANGGRAPH == "risk_assessment_langgraph_v1"
        assert RISK_ASSESSMENT_GRAPH_VERSION == "risk_assessment_graph_v1"
        assert RISK_ASSESSMENT_CARD_SCHEMA_VERSION == "risk_assessment_card_schema_v1"


# === Test: API schema ===

class TestAPISchema:

    def test_health_response_schema(self):
        from app.schemas.risk_assessment import RiskAssessmentHealthResponse
        resp = RiskAssessmentHealthResponse(
            enabled=True,
            llm_configured=True,
            mcp_available=True,
            public_data_mode="mcp",
            message="ready",
        )
        assert resp.mcp_available is True
        assert resp.public_data_mode == "mcp"

    def test_result_schema(self):
        from app.schemas.risk_assessment import RiskAssessmentResult
        result = RiskAssessmentResult(
            id="test-id",
            overall_risk_score=45.0,
            risk_level="medium",
            risk_summary="test",
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )
        assert result.overall_risk_score == 45.0
        assert result.fallback_used is False


# === Test: Card dataclasses ===

class TestCardDataclasses:

    def test_account_risk_snapshot_to_dict(self):
        snapshot = _make_snapshot()
        d = snapshot.to_dict()
        assert "positions" in d
        assert "net_liquidation" in d
        assert "largest_position_pct" in d

    def test_concentration_card_to_dict(self):
        card = ConcentrationRiskCard(score=10, risk_level=RiskLevel.MEDIUM)
        d = card.to_dict()
        assert d["card_type"] == "concentration_risk"
        assert d["score"] == 10

    def test_stress_test_card_to_dict(self):
        card = StressTestCard(scenarios=[{"scenario_name": "test"}])
        d = card.to_dict()
        assert len(d["scenarios"]) == 1

    def test_card_pack_to_dict(self):
        pack = RiskAssessmentCardPack(
            concentration_card=ConcentrationRiskCard(),
            stress_test_card=StressTestCard(),
        )
        d = pack.to_dict()
        assert "concentration_card" in d
        assert "stress_test_card" in d

    def test_fallback_cards(self):
        from app.agents.risk_assessment_graph.cards import (
            build_fallback_concentration_card,
            build_fallback_sector_theme_card,
            build_fallback_correlation_card,
            build_fallback_earnings_calendar_card,
            build_fallback_stress_test_card,
        )
        for builder in [
            build_fallback_concentration_card,
            build_fallback_sector_theme_card,
            build_fallback_correlation_card,
            build_fallback_earnings_calendar_card,
            build_fallback_stress_test_card,
        ]:
            card = builder("test reason")
            assert card.risk_level == RiskLevel.MEDIUM
            assert card.evidence_quality == "low"


# === Test: Node factories ===

class TestNodeFactories:

    def test_all_factories_return_callables(self):
        from app.agents.risk_assessment_graph.nodes import (
            make_build_account_risk_facts_node,
            make_position_concentration_node,
            make_sector_theme_exposure_node,
            make_correlation_node,
            make_earnings_calendar_risk_node,
            make_stress_test_node,
            make_risk_report_composer_node,
            make_persist_risk_assessment_node,
        )
        deps = MagicMock()
        for factory in [
            make_build_account_risk_facts_node,
            make_position_concentration_node,
            make_sector_theme_exposure_node,
            make_correlation_node,
            make_earnings_calendar_risk_node,
            make_stress_test_node,
            make_risk_report_composer_node,
            make_persist_risk_assessment_node,
        ]:
            assert callable(factory(deps))

    def test_nodes_do_not_read_state_deps(self):
        from app.agents.risk_assessment_graph import nodes
        source = inspect.getsource(nodes)
        assert "state[\"_deps\"]" not in source


class TestPersistTraceConsistency:

    def test_persist_trace_in_saved_document_and_final_state(self):
        """persist_risk_assessment must appear in both saved_document.run_trace and final_state.node_traces."""
        from app.agents.risk_assessment_graph.runner import RiskAssessmentGraphRunner

        snapshot = _make_snapshot()
        mock_builder = MagicMock()
        mock_builder.build.return_value = snapshot

        captured_doc = {}
        def capture_save(doc):
            captured_doc.update(doc)
            doc["id"] = "risk-trace-test"
            return doc
        mock_repo = MagicMock()
        mock_repo.save_assessment.side_effect = capture_save

        mock_adapter = MagicMock()
        mock_adapter.client = MagicMock()
        type(mock_adapter.client).enabled = PropertyMock(return_value=False)

        runner = RiskAssessmentGraphRunner(
            account_facts_builder=mock_builder,
            repository=mock_repo,
            llm_service=MagicMock(),
            mcp_adapter=mock_adapter,
        )

        final_state = runner.graph.invoke(runner._initial_state())

        saved_doc = final_state["saved_document"]
        saved_names = [t["node_name"] for t in saved_doc["run_trace"]]
        final_names = [t["node_name"] for t in final_state["node_traces"]]

        # persist_risk_assessment must appear exactly once in both
        assert "persist_risk_assessment" in saved_names
        assert "persist_risk_assessment" in final_names
        assert saved_names.count("persist_risk_assessment") == 1
        assert final_names.count("persist_risk_assessment") == 1

        # all 8 nodes must be present
        expected_nodes = [
            "build_account_risk_facts",
            "position_concentration",
            "sector_theme_exposure",
            "correlation",
            "earnings_calendar_risk",
            "stress_test",
            "risk_report_composer",
            "persist_risk_assessment",
        ]
        for name in expected_nodes:
            assert name in saved_names, f"{name} missing from saved_document.run_trace"
            assert name in final_names, f"{name} missing from final_state.node_traces"
