from dataclasses import dataclass
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

from app.services.agent_task_repository import AgentTaskRepository


@dataclass
class DummySettings:
    es_agent_task_index: str = "agent-task-index"


class StubESClient:
    def __init__(self) -> None:
        self.documents: dict[str, dict] = {}

    def create_index_if_missing(self, index: str, body: dict) -> None:
        return None

    def index_document(self, index: str, id: str, document: dict) -> dict:
        self.documents[id] = deepcopy(document)
        return {"result": "created"}

    def get(self, index: str, id: str) -> dict | None:
        document = self.documents.get(id)
        return {"_source": deepcopy(document)} if document else None

    def search(self, index: str, body: dict) -> dict:
        agent_filter = None
        for item in body.get("query", {}).get("bool", {}).get("filter", []):
            if "term" in item and "agent" in item["term"]:
                agent_filter = item["term"]["agent"]
        values = list(self.documents.values())
        if agent_filter:
            values = [item for item in values if item.get("agent") == agent_filter]
        values.sort(key=lambda item: item["created_at"], reverse=True)
        return {"hits": {"hits": [{"_source": dict(item)} for item in values[: body.get("size", 20)]]}}


def test_agent_task_repository_lifecycle() -> None:
    repository = AgentTaskRepository(StubESClient(), DummySettings())

    task = repository.create_task(agent="trade_decision", task_type="entry_decision", label="AAPL.US 建仓建议", payload={"symbol": "AAPL.US"})
    assert task["status"] == "queued"

    running = repository.mark_running(task["id"])
    assert running is not None
    assert running["status"] == "running"
    assert running["started_at"]

    completed = repository.mark_completed(task["id"], result_id="decision-1")
    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["result_id"] == "decision-1"

    listed = repository.list_tasks(agent="trade_decision", limit=10)
    assert [item["id"] for item in listed] == [task["id"]]


def test_agent_task_graph_progress_lifecycle() -> None:
    repository = AgentTaskRepository(StubESClient(), DummySettings())
    task = repository.create_task(agent="trade_decision", task_type="entry_decision", label="AAPL.US 建仓建议", payload={"symbol": "AAPL.US"})

    repository.init_graph_progress(
        task["id"],
        graph_version="trade_decision_graph_v1",
        nodes=[{"id": "build_account_facts", "label": "账户事实"}, {"id": "market_trend", "label": "市场趋势"}],
        edges=[{"source": "build_account_facts", "target": "market_trend"}],
    )
    running = repository.mark_node_running(task["id"], "build_account_facts")
    assert running is not None
    assert running["graph_snapshot"]["nodes"][0]["status"] == "running"
    assert running["graph_snapshot"]["current_nodes"] == ["build_account_facts"]

    finished = repository.mark_node_finished(
        task["id"],
        "build_account_facts",
        {
            "node_name": "build_account_facts",
            "status": "success",
            "elapsed_ms": 123,
            "tools_called": [{"name": "quote"}],
            "data_limitations": ["market closed"],
        },
    )
    assert finished is not None
    node = finished["graph_snapshot"]["nodes"][0]
    assert node["status"] == "success"
    assert node["tool_call_count"] == 1
    assert node["data_limitations_count"] == 1
    events = repository.list_graph_events(task["id"], after_seq=0)
    assert events
    assert repository.list_graph_events(task["id"], after_seq=events[-1]["seq"]) == []


def test_agent_task_graph_sync_from_run_trace_marks_final_status() -> None:
    repository = AgentTaskRepository(StubESClient(), DummySettings())
    task = repository.create_task(agent="trade_review", task_type="symbol_level_review", label="AMD.US 标的级复盘", payload={"symbol": "AMD.US"})
    repository.init_graph_progress(
        task["id"],
        graph_version="trade_review_graph_v1",
        nodes=[{"id": "load_trade_facts"}, {"id": "persist_trade_review"}],
        edges=[{"source": "load_trade_facts", "target": "persist_trade_review"}],
    )

    synced = repository.sync_graph_from_run_trace(
        task["id"],
        [
            {"node_name": "load_trade_facts", "status": "success", "elapsed_ms": 10},
            {"node_name": "persist_trade_review", "status": "fallback", "fallback_used": True, "fallback_reason": "save degraded", "elapsed_ms": 20},
        ],
        final_status="fallback",
    )

    assert synced is not None
    assert synced["graph_snapshot"]["status"] == "fallback"
    assert synced["graph_snapshot"]["nodes"][1]["fallback_used"] is True
    assert synced["graph_progress_summary"]["fallback_nodes"] == 1


def test_agent_task_parallel_node_updates_do_not_overwrite_each_other() -> None:
    repository = AgentTaskRepository(StubESClient(), DummySettings())
    task = repository.create_task(agent="trade_review", task_type="symbol_level_review", label="AMD.US 标的级复盘", payload={"symbol": "AMD.US"})
    repository.init_graph_progress(
        task["id"],
        graph_version="trade_review_graph_v1",
        nodes=[{"id": "market_evidence"}, {"id": "benchmark_evidence"}],
        edges=[{"source": "market_evidence", "target": "benchmark_evidence"}],
    )
    repository.mark_node_running(task["id"], "market_evidence")
    repository.mark_node_running(task["id"], "benchmark_evidence")

    def finish(node_id: str, elapsed_ms: int) -> None:
        repository.mark_node_finished(
            task["id"],
            node_id,
            {
                "node_name": node_id,
                "status": "success",
                "elapsed_ms": elapsed_ms,
                "runtime_trace": [{"event": "tool_finish", "tool": f"{node_id}_tool", "ok": True}],
            },
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(finish, "market_evidence", 100),
            executor.submit(finish, "benchmark_evidence", 200),
        ]
        for future in futures:
            future.result()

    latest = repository.get_task(task["id"])
    assert latest is not None
    nodes = {node["id"]: node for node in latest["graph_snapshot"]["nodes"]}
    assert nodes["market_evidence"]["status"] == "success"
    assert nodes["benchmark_evidence"]["status"] == "success"
    assert latest["graph_snapshot"]["current_nodes"] == []
    assert latest["graph_progress_summary"]["completed_nodes"] == 2
