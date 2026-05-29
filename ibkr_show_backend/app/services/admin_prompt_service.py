from __future__ import annotations

from app.agents.prompt_registry import get_prompt_definition, list_prompt_definitions
from app.schemas.admin_prompts import PromptCreateVersionRequest
from app.services.admin_prompt_repository import AdminPromptRepository, PromptVersionNotFoundError, content_sha256


class PromptNotFoundError(ValueError):
    """Raised when a prompt key is not registered in code."""


class PromptValidationError(ValueError):
    """Raised when a prompt mutation request is invalid."""


class AdminPromptService:
    def __init__(self, repository: AdminPromptRepository) -> None:
        self.repository = repository

    def list_prompts(self) -> list[dict]:
        items = []
        for definition in list_prompt_definitions():
            active = self.repository.get_active_prompt(definition.prompt_key)
            active_content_hash = active.get("content_hash") if active else None
            code_default_hash = content_sha256(definition.default_content)
            matches_code_default = bool(active_content_hash and active_content_hash == code_default_hash)
            items.append(
                {
                    "prompt_key": definition.prompt_key,
                    "display_name": definition.display_name,
                    "module_name": definition.module_name,
                    "agent_name": definition.agent_name,
                    "description": definition.description,
                    "active_version": active.get("version") if active else None,
                    "active_content_hash": active_content_hash,
                    "active_updated_at": active.get("updated_at") if active else None,
                    "has_active": active is not None,
                    "is_default_active": bool(active and active.get("is_default")),
                    "code_default_hash": code_default_hash,
                    "matches_code_default": matches_code_default,
                    "is_code_default_outdated": bool(active and active_content_hash != code_default_hash),
                }
            )
        return items

    def get_prompt_detail(self, prompt_key: str) -> dict:
        definition = self._require_definition(prompt_key)
        versions = self.repository.list_prompt_versions(prompt_key)
        active = next((item for item in versions if item.get("status") == "active"), None)
        return {"definition": definition.to_dict(), "versions": versions, "active": active}

    def create_version(self, prompt_key: str, payload: PromptCreateVersionRequest, created_by: str | None) -> dict:
        self._require_definition(prompt_key)
        content = payload.content.strip()
        if not content:
            raise PromptValidationError("Prompt content cannot be empty")
        return self.repository.create_version(prompt_key, content, payload.change_note, created_by)

    def activate_version(
        self,
        prompt_key: str,
        version: str,
        activated_by: str | None = None,
        change_note: str | None = None,
    ) -> dict:
        self._require_definition(prompt_key)
        return self.repository.activate_version(prompt_key, version, activated_by, change_note)

    def seed_default_versions(self) -> list[dict]:
        return self.repository.ensure_default_versions()

    def create_version_from_code_default(self, prompt_key: str, created_by: str | None) -> tuple[dict | None, str]:
        definition = self._require_definition(prompt_key)
        content = definition.default_content.strip()
        if not content:
            raise PromptValidationError("Code default prompt content cannot be empty")
        active = self.repository.get_active_prompt(prompt_key)
        code_hash = content_sha256(content)
        if active and active.get("content_hash") == code_hash:
            return None, "Active prompt already matches code default; no draft created"
        prompt = self.repository.create_version(
            prompt_key,
            content,
            "Sync from code default prompt",
            created_by,
        )
        return prompt, "Draft version created from code default prompt"

    def sync_code_default_versions(self, created_by: str | None) -> dict:
        created = []
        skipped = []
        for definition in list_prompt_definitions():
            prompt, message = self.create_version_from_code_default(definition.prompt_key, created_by)
            item = {
                "prompt_key": definition.prompt_key,
                "created": prompt is not None,
                "skipped": prompt is None,
                "message": message,
                "prompt": prompt,
            }
            if prompt is None:
                skipped.append(item)
            else:
                created.append(item)
        return {
            "created": created,
            "skipped": skipped,
            "message": f"Created {len(created)} draft prompt version(s); skipped {len(skipped)}",
        }

    def get_runtime_prompt(self, prompt_key: str, fallback: str | None = None) -> dict:
        definition = self._require_definition(prompt_key)
        try:
            active = self.repository.get_active_prompt(prompt_key)
        except Exception:
            active = None
        if active and active.get("content"):
            return {
                "content": active["content"],
                "metadata": {
                    "prompt_key": prompt_key,
                    "version": active.get("version"),
                    "content_hash": active.get("content_hash"),
                    "source": "admin_active",
                },
            }
        if definition.default_content:
            return {
                "content": definition.default_content,
                "metadata": {
                    "prompt_key": prompt_key,
                    "version": None,
                    "content_hash": content_sha256(definition.default_content),
                    "source": "code_default",
                },
            }
        return {
            "content": fallback or "",
            "metadata": {
                "prompt_key": prompt_key,
                "version": None,
                "content_hash": content_sha256(fallback or "") if fallback else None,
                "source": "fallback",
            },
        }

    def _require_definition(self, prompt_key: str):
        definition = get_prompt_definition(prompt_key)
        if definition is None:
            raise PromptNotFoundError(f"Unknown prompt_key: {prompt_key}")
        return definition


__all__ = [
    "AdminPromptService",
    "PromptNotFoundError",
    "PromptValidationError",
    "PromptVersionNotFoundError",
]
