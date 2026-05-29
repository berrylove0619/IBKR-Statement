from __future__ import annotations

import hashlib
from typing import Any


def resolve_runtime_prompt(prompt_service: Any, prompt_key: str, fallback: str) -> tuple[str, dict]:
    """Resolve an admin-managed prompt without letting prompt storage break agents."""
    fallback_content = str(fallback or "").strip()
    metadata = {
        "prompt_key": prompt_key,
        "version": None,
        "content_hash": _sha256(fallback_content),
        "source": "fallback",
    }
    if not fallback_content:
        raise ValueError(f"Fallback prompt is empty for {prompt_key}")

    if prompt_service is None:
        return fallback_content, metadata

    try:
        resolved = prompt_service.get_runtime_prompt(prompt_key, fallback=fallback_content)
        content = str((resolved or {}).get("content") or "").strip()
        raw_metadata = dict((resolved or {}).get("metadata") or {})
        if content:
            return content, {
                "prompt_key": raw_metadata.get("prompt_key") or prompt_key,
                "version": raw_metadata.get("version"),
                "content_hash": raw_metadata.get("content_hash") or _sha256(content),
                "source": raw_metadata.get("source") or "admin_active",
            }
    except Exception as exc:
        metadata["error"] = str(exc)[:200]

    metadata["content_hash"] = _sha256(fallback_content)
    return fallback_content, metadata


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
