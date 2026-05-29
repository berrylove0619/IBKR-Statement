from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from uuid import uuid4

from app.agents.prompt_registry import PromptDefinitionRecord, list_prompt_definitions
from app.clients.es_client import ESIndexNotFoundError, ElasticsearchClient
from app.core.config import Settings

PROMPT_INDEX_BODY = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "prompt_key": {"type": "keyword"},
            "display_name": {"type": "keyword"},
            "module_name": {"type": "keyword"},
            "agent_name": {"type": "keyword"},
            "description": {"type": "text"},
            "content": {"type": "text", "index": False},
            "version": {"type": "keyword"},
            "status": {"type": "keyword"},
            "content_hash": {"type": "keyword"},
            "is_default": {"type": "boolean"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "created_by": {"type": "keyword"},
            "activated_at": {"type": "date"},
            "change_note": {"type": "text"},
        }
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class PromptVersionNotFoundError(ValueError):
    """Raised when a prompt version cannot be found."""


class AdminPromptRepository:
    def __init__(self, es_client: ElasticsearchClient, settings: Settings) -> None:
        self.es_client = es_client
        self.settings = settings
        self.index_name = settings.es_agent_prompt_index

    def list_prompt_versions(self, prompt_key: str) -> list[dict]:
        try:
            response = self.es_client.search(
                index=self.index_name,
                body={
                    "query": {"bool": {"filter": [{"term": {"prompt_key": prompt_key}}]}},
                    "sort": [{"created_at": {"order": "asc"}}],
                    "size": 100,
                    "_source": True,
                },
            )
        except ESIndexNotFoundError:
            return []
        versions = [hit["_source"] for hit in response.get("hits", {}).get("hits", [])]
        return sorted(versions, key=lambda item: _version_number(item.get("version")))

    def get_active_prompt(self, prompt_key: str) -> dict | None:
        try:
            response = self.es_client.search(
                index=self.index_name,
                body={
                    "query": {
                        "bool": {
                            "filter": [
                                {"term": {"prompt_key": prompt_key}},
                                {"term": {"status": "active"}},
                            ]
                        }
                    },
                    "sort": [{"updated_at": {"order": "desc"}}],
                    "size": 1,
                    "_source": True,
                },
            )
        except ESIndexNotFoundError:
            return None
        hits = response.get("hits", {}).get("hits", [])
        return hits[0]["_source"] if hits else None

    def get_prompt_version(self, prompt_key: str, version: str) -> dict | None:
        document_id = self._document_id(prompt_key, version)
        try:
            response = self.es_client.get(index=self.index_name, id=document_id)
        except ESIndexNotFoundError:
            return None
        return response.get("_source") if response else None

    def create_version(self, prompt_key: str, content: str, change_note: str | None, created_by: str | None) -> dict:
        definition = self._definition_for(prompt_key)
        versions = self.list_prompt_versions(prompt_key)
        next_version = f"v{max([_version_number(item.get('version')) for item in versions] or [0]) + 1}"
        return self._save_version(
            definition=definition,
            version=next_version,
            content=content,
            status="draft",
            is_default=False,
            created_by=created_by,
            change_note=change_note,
        )

    def activate_version(
        self,
        prompt_key: str,
        version: str,
        activated_by: str | None = None,
        change_note: str | None = None,
    ) -> dict:
        existing = self.get_prompt_version(prompt_key, version)
        if existing is None:
            raise PromptVersionNotFoundError(f"Prompt version not found: {prompt_key} {version}")

        now = utc_now_iso()
        self._ensure_index()
        self.es_client.update_by_query(
            index=self.index_name,
            body={
                "script": {
                    "source": "ctx._source.status = 'archived'; ctx._source.updated_at = params.updated_at",
                    "lang": "painless",
                    "params": {"updated_at": now},
                },
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"prompt_key": prompt_key}},
                            {"term": {"status": "active"}},
                        ]
                    }
                },
            },
        )
        activated = {
            **existing,
            "status": "active",
            "updated_at": now,
            "activated_at": now,
        }
        if change_note is not None:
            activated["change_note"] = change_note
        if activated_by and not activated.get("created_by"):
            activated["created_by"] = activated_by
        self.es_client.index_document(index=self.index_name, id=self._document_id(prompt_key, version), document=activated)
        return activated

    def archive_version(self, prompt_key: str, version: str) -> dict:
        existing = self.get_prompt_version(prompt_key, version)
        if existing is None:
            raise PromptVersionNotFoundError(f"Prompt version not found: {prompt_key} {version}")
        archived = {**existing, "status": "archived", "updated_at": utc_now_iso()}
        self._ensure_index()
        self.es_client.index_document(index=self.index_name, id=self._document_id(prompt_key, version), document=archived)
        return archived

    def ensure_default_versions(self) -> list[dict]:
        seeded: list[dict] = []
        for definition in list_prompt_definitions():
            active = self.get_active_prompt(definition.prompt_key)
            if active is not None:
                seeded.append(active)
                continue
            versions = self.list_prompt_versions(definition.prompt_key)
            version = "v1" if not versions else f"v{max(_version_number(item.get('version')) for item in versions) + 1}"
            seeded.append(
                self._save_version(
                    definition=definition,
                    version=version,
                    content=definition.default_content,
                    status="active",
                    is_default=True,
                    created_by="system",
                    change_note="Seed code default prompt",
                    activated_at=utc_now_iso(),
                )
            )
        return seeded

    def _save_version(
        self,
        *,
        definition: PromptDefinitionRecord,
        version: str,
        content: str,
        status: str,
        is_default: bool,
        created_by: str | None,
        change_note: str | None,
        activated_at: str | None = None,
    ) -> dict:
        self._ensure_index()
        now = utc_now_iso()
        document_id = self._document_id(definition.prompt_key, version)
        document = {
            "id": document_id,
            "prompt_key": definition.prompt_key,
            "display_name": definition.display_name,
            "module_name": definition.module_name,
            "agent_name": definition.agent_name,
            "description": definition.description,
            "content": content,
            "version": version,
            "status": status,
            "content_hash": content_sha256(content),
            "is_default": is_default,
            "created_at": now,
            "updated_at": now,
            "created_by": created_by,
            "activated_at": activated_at,
            "change_note": change_note,
        }
        self.es_client.index_document(index=self.index_name, id=document_id, document=document)
        return document

    def _ensure_index(self) -> None:
        self.es_client.create_index_if_missing(self.index_name, PROMPT_INDEX_BODY)

    def _definition_for(self, prompt_key: str) -> PromptDefinitionRecord:
        for definition in list_prompt_definitions():
            if definition.prompt_key == prompt_key:
                return definition
        raise ValueError(f"Unknown prompt_key: {prompt_key}")

    @staticmethod
    def _document_id(prompt_key: str, version: str) -> str:
        return f"{prompt_key}:{version}"


def _version_number(version: object) -> int:
    match = re.fullmatch(r"v(\d+)", str(version or ""))
    return int(match.group(1)) if match else 0
