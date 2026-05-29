from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel

from app.agents.structured_output.errors import StructuredOutputError, preview_text


DEFAULT_REPAIR_SYSTEM_PROMPT = """你是结构化 JSON 修复器。
你的任务不是重新分析业务，而是把已有模型输出修复为符合指定 schema 的严格 JSON object。
只能使用原始输出和上下文中已经出现的信息。
不能编造事实、数字、新闻、财报、账户数据或交易建议。
如果某字段缺失且无法从原始输出或上下文确定，请填 null、空字符串、空数组或在 data_limitations 中说明。
只输出 JSON object，不要 Markdown，不要解释，不要代码块。"""


FallbackBuilder = Callable[[dict[str, Any] | None, StructuredOutputError, str], dict[str, Any] | BaseModel]
RepairPromptBuilder = Callable[["StructuredOutputContract", str, StructuredOutputError, dict[str, Any] | None], list[dict[str, str]]]


@dataclass
class StructuredOutputContract:
    name: str
    agent_name: str
    node_name: str
    output_model: type[BaseModel] | None = None
    schema_hint: dict[str, Any] | str | None = None
    examples: list[dict[str, Any] | str] = field(default_factory=list)
    max_repair_attempts: int = 1
    response_format: dict[str, str] = field(default_factory=lambda: {"type": "json_object"})
    repair_enabled: bool = True
    fallback_enabled: bool = True
    fallback_builder: FallbackBuilder | None = None
    repair_system_prompt: str | None = None
    repair_user_prompt_builder: RepairPromptBuilder | None = None
    user_visible_error_message: str | None = None

    def build_repair_messages(
        self,
        *,
        raw_response: str,
        error: StructuredOutputError,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        if self.repair_user_prompt_builder is not None:
            return self.repair_user_prompt_builder(self, raw_response, error, context)
        return build_default_repair_messages(self, raw_response=raw_response, error=error, context=context)


def build_default_repair_messages(
    contract: StructuredOutputContract,
    *,
    raw_response: str,
    error: StructuredOutputError,
    context: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    user_prompt = "\n".join(
        [
            f"contract_name: {contract.name}",
            f"agent_name: {contract.agent_name}",
            f"node_name: {contract.node_name}",
            "schema_hint:",
            _format_jsonish(contract.schema_hint),
            "examples:",
            _format_jsonish(contract.examples),
            f"error_code: {error.error_code}",
            "validation_error:",
            error.validation_error or error.message,
            "raw_response:",
            preview_text(raw_response, max_chars=8000) or "",
            "context_preview:",
            _context_preview(context),
            "",
            "请只修复格式和 schema，不要新增事实。只输出严格 JSON object。",
        ]
    )
    return [
        {"role": "system", "content": contract.repair_system_prompt or DEFAULT_REPAIR_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def _format_jsonish(value: Any) -> str:
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except TypeError:
        return str(value)


def _context_preview(context: dict[str, Any] | None) -> str:
    if not context:
        return "{}"
    try:
        text = json.dumps(context, ensure_ascii=False, default=str)
    except TypeError:
        text = str(context)
    return preview_text(text, max_chars=8000) or "{}"
