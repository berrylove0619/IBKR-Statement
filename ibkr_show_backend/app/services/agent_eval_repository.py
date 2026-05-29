from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.agents.eval_cases import list_builtin_eval_cases
from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings


EVAL_CASE_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "case_id": {"type": "keyword"},
            "agent_name": {"type": "keyword"},
            "source": {"type": "keyword"},
            "tags": {"type": "keyword"},
            "created_at": {"type": "date"},
            "metadata": {"type": "object", "enabled": True},
        }
    },
}

EVAL_RUN_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "eval_run_id": {"type": "keyword"},
            "name": {"type": "keyword"},
            "agent_name": {"type": "keyword"},
            "case_ids": {"type": "keyword"},
            "started_at": {"type": "date"},
            "finished_at": {"type": "date"},
            "status": {"type": "keyword"},
            "summary": {"type": "object", "enabled": True},
            "results": {"type": "object", "enabled": True},
            "config": {"type": "object", "enabled": True},
        }
    },
}


def since_iso(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours)))).isoformat()


class EvalCaseRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    @property
    def index_name(self) -> str:
        return self.settings.es_agent_eval_case_index

    def save_case(self, case: dict) -> dict:
        self._ensure_index()
        self.es_client.index_document(index=self.index_name, id=case["case_id"], document=case)
        return case

    def get_case(self, case_id: str) -> dict | None:
        try:
            hit = self.es_client.get(index=self.index_name, id=case_id)
        except ESIndexNotFoundError:
            return None
        return hit.get("_source") if hit else None

    def list_cases(self, *, agent_name: str | None = None, source: str | None = None, limit: int = 100) -> list[dict]:
        filters: list[dict] = []
        if agent_name:
            filters.append({"term": {"agent_name": agent_name}})
        if source:
            filters.append({"term": {"source": source}})
        body = {
            "query": {"bool": {"filter": filters}} if filters else {"match_all": {}},
            "sort": [{"created_at": {"order": "desc"}}],
            "size": max(1, min(int(limit), 10000)),
            "_source": True,
        }
        try:
            response = self.es_client.search(index=self.index_name, body=body)
        except ESIndexNotFoundError:
            return []
        return [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]

    def seed_builtin_cases(self, *, force: bool = False) -> dict:
        created = []
        skipped = []
        for case in list_builtin_eval_cases():
            existing = self.get_case(case.case_id)
            if existing and not force:
                skipped.append(case.case_id)
                continue
            self.save_case(case.to_dict())
            created.append(case.case_id)
        return {"created": created, "skipped": skipped, "created_count": len(created), "skipped_count": len(skipped)}

    def _ensure_index(self) -> None:
        self.es_client.create_index_if_missing(self.index_name, EVAL_CASE_INDEX_BODY)


class EvalRunRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings

    @property
    def index_name(self) -> str:
        return self.settings.es_agent_eval_run_index

    def save_run(self, run: dict) -> dict:
        self._ensure_index()
        self.es_client.index_document(index=self.index_name, id=run["eval_run_id"], document=run)
        return run

    def get_run(self, eval_run_id: str) -> dict | None:
        try:
            hit = self.es_client.get(index=self.index_name, id=eval_run_id)
        except ESIndexNotFoundError:
            return None
        return hit.get("_source") if hit else None

    def list_runs(self, *, hours: int = 24, agent_name: str | None = None, limit: int = 100) -> list[dict]:
        filters: list[dict] = [{"range": {"started_at": {"gte": since_iso(hours)}}}]
        if agent_name:
            filters.append({"term": {"agent_name": agent_name}})
        try:
            response = self.es_client.search(
                index=self.index_name,
                body={
                    "query": {"bool": {"filter": filters}},
                    "sort": [{"started_at": {"order": "desc"}}],
                    "size": max(1, min(int(limit), 10000)),
                    "_source": True,
                },
            )
        except ESIndexNotFoundError:
            return []
        return [hit.get("_source", {}) for hit in response.get("hits", {}).get("hits", [])]

    def _ensure_index(self) -> None:
        self.es_client.create_index_if_missing(self.index_name, EVAL_RUN_INDEX_BODY)
