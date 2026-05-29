from __future__ import annotations

import json
import re
from json import JSONDecodeError
from typing import Any

from app.agents.structured_output.errors import (
    LLM_JSON_PARSE_FAILED,
    LLM_OUTPUT_EMPTY,
    LLM_OUTPUT_NOT_OBJECT,
    StructuredOutputError,
)


_FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*(.*?)\s*```\s*$", re.DOTALL)


def extract_json_object(raw: str | None) -> dict[str, Any]:
    if raw is None or not str(raw).strip():
        raise StructuredOutputError(
            LLM_OUTPUT_EMPTY,
            "LLM output is empty; expected a JSON object.",
            raw_response_preview=raw,
        )

    text = str(raw).strip()
    candidates = [text]
    unfenced = _strip_markdown_fence(text)
    if unfenced != text:
        candidates.insert(0, unfenced)

    direct_non_object_error: StructuredOutputError | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        direct_non_object_error = StructuredOutputError(
            LLM_OUTPUT_NOT_OBJECT,
            f"LLM output parsed as {type(parsed).__name__}, expected JSON object.",
            raw_response_preview=raw,
        )
        break

    if direct_non_object_error is not None:
        raise direct_non_object_error

    decoder = json.JSONDecoder()
    for candidate in candidates:
        for match in re.finditer(r"\{", candidate):
            try:
                parsed, _end = decoder.raw_decode(candidate, match.start())
            except JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
            raise StructuredOutputError(
                LLM_OUTPUT_NOT_OBJECT,
                f"Extracted JSON value is {type(parsed).__name__}, expected object.",
                raw_response_preview=raw,
            )

    raise StructuredOutputError(
        LLM_JSON_PARSE_FAILED,
        "Failed to parse a JSON object from LLM output.",
        raw_response_preview=raw,
    )


def extract_json_object_lenient(raw: str | None) -> dict[str, Any] | None:
    try:
        return extract_json_object(raw)
    except StructuredOutputError:
        return None


def _strip_markdown_fence(text: str) -> str:
    match = _FENCE_RE.match(text)
    if match:
        return match.group(1).strip()
    return text
