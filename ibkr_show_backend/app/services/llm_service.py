from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.core.config import Settings
from app.schemas.admin_llm import LLMProviderCreateRequest, LLMProviderPublic, LLMProviderUpdateRequest
from app.services.llm_observability import (
    LLMCallMetadata,
    LLMCallResult,
    LLMUsage,
    estimate_llm_cost,
    extract_prompt_metadata,
    new_call_id,
    safe_response_metadata,
    utc_now_iso as observability_utc_now_iso,
)

logger = logging.getLogger(__name__)

OPENAI_COMPATIBLE_PROVIDER_TYPE = "openai_compatible"
MASKED_API_KEY_MARKER = "****"
DEFAULT_CONTEXT_WINDOW_TOKENS = 200000
DEFAULT_INPUT_TOKEN_LIMIT = 150000
DEFAULT_OUTPUT_TOKEN_LIMIT = 10000


class LLMConfigError(ValueError):
    """Raised when an LLM provider configuration is invalid."""


class LLMProviderNotFoundError(ValueError):
    """Raised when an LLM provider cannot be found."""


class LLMClientError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


PRIVATE_MESSAGE_FIELDS = {
    "debug",
    "_debug",
    "private",
}

CHINESE_OUTPUT_POLICY_MARKER = "全局输出语言要求"

CHINESE_OUTPUT_POLICY = """
全局输出语言要求：
除股票代码（如 MSTR、AMD、XIACY、QQQ、SPY、SMH）、公司英文名（如 Strategy Inc、Advanced Micro Devices）、
交易所代码、API 字段名、工具名、财务缩写（如 PE、TTM、EPS、ROE、PB、EBITDA）和枚举值外，
所有面向用户展示的自然语言内容必须使用简体中文。
如果工具、新闻、财报或市场数据返回英文，不要原样照抄英文句子，必须翻译或改写为中文。
JSON 的 key、schema 字段名、enum / Literal 枚举值保持原样，不要翻译。
只翻译自然语言 value，不要翻译结构化字段名或枚举值。
""".strip()

# Provider-private reasoning fields must never be forwarded to the next request.
# Some OpenAI-compatible providers reject these fields with HTTP 400, and they
# should not be shown as normal assistant content.
PROVIDER_PRIVATE_REASONING_FIELDS = {
    "reasoning",
    "reasoning_content",
    "thinking",
}


def sanitize_chat_messages(
    messages: list[dict[str, Any]],
    *,
    preserve_provider_reasoning: bool = False,
) -> list[dict[str, Any]]:
    """Remove private debug and provider reasoning fields before sending messages.

    Messages whose only meaningful content was reasoning fields (empty content,
    no tool_calls) are dropped entirely so they don't trigger thinking-mode
    requirements on providers that enforce reasoning_content round-tripping.
    """
    sanitized: list[dict[str, Any]] = []
    allowed_fields = {"role", "content", "name", "tool_call_id", "tool_calls"}
    if preserve_provider_reasoning:
        allowed_fields = allowed_fields | PROVIDER_PRIVATE_REASONING_FIELDS
    for message in messages:
        if not isinstance(message, dict):
            continue
        has_reasoning = any(
            key in message
            for key in PROVIDER_PRIVATE_REASONING_FIELDS
        )
        cleaned = {
            key: value
            for key, value in message.items()
            if key in allowed_fields
            and key not in PRIVATE_MESSAGE_FIELDS
            and (preserve_provider_reasoning or key not in PROVIDER_PRIVATE_REASONING_FIELDS)
        }
        content = cleaned.get("content")
        tool_calls = cleaned.get("tool_calls")
        if content in (None, "") and not tool_calls and has_reasoning:
            continue
        if content is None:
            cleaned["content"] = ""
        sanitized.append(cleaned)
    return sanitized


def apply_global_output_language_policy(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Inject CHINESE_OUTPUT_POLICY into system message so the LLM outputs Chinese by default."""
    if not messages:
        return [{"role": "system", "content": CHINESE_OUTPUT_POLICY}]
    result = [dict(msg) for msg in messages]
    first = result[0]
    if not isinstance(first, dict):
        result.insert(0, {"role": "system", "content": CHINESE_OUTPUT_POLICY})
        return result
    if first.get("role") == "system":
        existing_content = first.get("content") or ""
        if isinstance(existing_content, str) and CHINESE_OUTPUT_POLICY_MARKER in existing_content:
            return result
        if isinstance(existing_content, str):
            result[0] = {**first, "content": existing_content + "\n\n" + CHINESE_OUTPUT_POLICY}
        else:
            result[0] = {**first, "content": CHINESE_OUTPUT_POLICY}
    else:
        result.insert(0, {"role": "system", "content": CHINESE_OUTPUT_POLICY})
    return result


@dataclass
class LLMProviderConfig:
    id: str
    name: str
    provider_type: str
    base_url: str
    api_key: str
    default_model: str
    available_models: list[str] = field(default_factory=list)
    is_active: bool = False
    enabled: bool = True
    enable_thinking: bool = False
    reasoning_effort: str = "high"
    timeout_seconds: int = 60
    temperature: float = 0.2
    context_window_tokens: int = DEFAULT_CONTEXT_WINDOW_TOKENS
    input_token_limit: int = DEFAULT_INPUT_TOKEN_LIMIT
    output_token_limit: int = DEFAULT_OUTPUT_TOKEN_LIMIT
    input_price_per_1m_tokens: float = 0
    output_price_per_1m_tokens: float = 0
    created_at: str = ""
    updated_at: str = ""

    @property
    def max_tokens(self) -> int:
        """Backward-compatible alias for output_token_limit."""
        return self.output_token_limit


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def mask_api_key(api_key: str | None) -> str:
    if not api_key:
        return ""

    value = api_key.strip()
    if len(value) <= 8:
        return MASKED_API_KEY_MARKER

    if "-" in value:
        prefix = value.split("-", 1)[0]
        if 1 <= len(prefix) <= 8:
            return f"{prefix}-{MASKED_API_KEY_MARKER}{value[-4:]}"

    return f"{MASKED_API_KEY_MARKER}{value[-4:]}"


def is_masked_api_key(value: str | None) -> bool:
    return bool(value and MASKED_API_KEY_MARKER in value)


def normalize_available_models(values: list[str] | None) -> list[str]:
    if not values:
        return []
    normalized = []
    for value in values:
        for item in str(value).split(","):
            model = item.strip()
            if model and model not in normalized:
                normalized.append(model)
    return normalized


def is_deepseek_provider(provider: LLMProviderConfig) -> bool:
    base = (provider.base_url or "").lower()
    model = (provider.default_model or "").lower()
    return "deepseek" in base or model.startswith("deepseek")


def _apply_deepseek_thinking_payload(
    payload: dict[str, Any],
    provider: LLMProviderConfig,
) -> None:
    if provider.enable_thinking:
        payload["thinking"] = {"type": "enabled"}
        payload["reasoning_effort"] = provider.reasoning_effort
        for key in ("temperature", "top_p", "presence_penalty", "frequency_penalty"):
            payload.pop(key, None)
    else:
        payload["thinking"] = {"type": "disabled"}


def build_chat_completions_url(base_url: str) -> str:
    return f"{base_url.strip().rstrip('/')}/chat/completions"


def format_provider_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip()[:500]

    if not isinstance(payload, dict):
        return ""

    error = payload.get("error")
    if isinstance(error, dict):
        parts = []
        for key in ("message", "param", "code", "type"):
            value = error.get(key)
            if value:
                parts.append(f"{key}={value}")
        return "; ".join(parts)[:500]

    message = payload.get("message") or payload.get("detail")
    return str(message).strip()[:500] if message else ""


def build_provider_status_message(response: httpx.Response, fallback: str) -> str:
    detail = format_provider_error_detail(response)
    return f"{fallback}: {detail}" if detail else fallback


class LLMProviderConfigStore:
    def __init__(self, config_file: str) -> None:
        self.config_file = Path(config_file).expanduser()

    def list_providers(self) -> list[LLMProviderConfig]:
        raw_payload = self._read_payload()
        providers = []
        for item in raw_payload.get("providers", []):
            if isinstance(item, dict):
                providers.append(self._provider_from_dict(item))
        return providers

    def save_providers(self, providers: list[LLMProviderConfig]) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {"providers": [asdict(provider) for provider in providers]}
        fd, temp_path = tempfile.mkstemp(prefix=f".{self.config_file.name}.", suffix=".tmp", dir=self.config_file.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                json.dump(payload, temp_file, ensure_ascii=False, indent=2)
                temp_file.write("\n")
            os.replace(temp_path, self.config_file)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def _read_payload(self) -> dict:
        if not self.config_file.exists():
            return {"providers": []}
        try:
            with self.config_file.open("r", encoding="utf-8") as config_file:
                payload = json.load(config_file)
        except json.JSONDecodeError as exc:
            raise LLMConfigError("LLM config file is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise LLMConfigError("LLM config file must contain a JSON object")
        return payload

    def _provider_from_dict(self, item: dict[str, Any]) -> LLMProviderConfig:
        output_token_limit = int(item.get("output_token_limit") or item.get("max_tokens") or DEFAULT_OUTPUT_TOKEN_LIMIT)
        context_window_tokens = int(item.get("context_window_tokens") or DEFAULT_CONTEXT_WINDOW_TOKENS)
        fallback_input_limit = max(1, min(DEFAULT_INPUT_TOKEN_LIMIT, context_window_tokens - output_token_limit))
        input_token_limit = int(item.get("input_token_limit") or fallback_input_limit)
        return LLMProviderConfig(
            id=str(item.get("id") or uuid4()),
            name=str(item.get("name") or ""),
            provider_type=str(item.get("provider_type") or OPENAI_COMPATIBLE_PROVIDER_TYPE),
            base_url=str(item.get("base_url") or ""),
            api_key=str(item.get("api_key") or ""),
            default_model=str(item.get("default_model") or ""),
            available_models=normalize_available_models(item.get("available_models") or []),
            is_active=bool(item.get("is_active", False)),
            enabled=bool(item.get("enabled", True)),
            enable_thinking=bool(item.get("enable_thinking", False)),
            reasoning_effort=str(item.get("reasoning_effort") or "high"),
            timeout_seconds=int(item.get("timeout_seconds") or 60),
            temperature=float(item.get("temperature", 0.2)),
            context_window_tokens=context_window_tokens,
            input_token_limit=input_token_limit,
            output_token_limit=output_token_limit,
            input_price_per_1m_tokens=float(item.get("input_price_per_1m_tokens") or 0),
            output_price_per_1m_tokens=float(item.get("output_price_per_1m_tokens") or 0),
            created_at=str(item.get("created_at") or utc_now_iso()),
            updated_at=str(item.get("updated_at") or utc_now_iso()),
        )


class GenericOpenAICompatibleClient:
    def __init__(self, provider: LLMProviderConfig) -> None:
        self.provider = provider

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> str:
        result = self.chat_with_metadata(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        return str(result.content or "")

    def chat_with_metadata(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        call_type: str = "chat",
        agent_name: str | None = None,
        node_name: str | None = None,
        prompt_metadata: dict | None = None,
        preserve_provider_reasoning: bool = False,
        disable_provider_thinking: bool = False,
    ) -> LLMCallResult:
        payload = {
            "model": model or self.provider.default_model,
            "messages": apply_global_output_language_policy(
                sanitize_chat_messages(messages, preserve_provider_reasoning=preserve_provider_reasoning)
            ),
            "temperature": self.provider.temperature if temperature is None else temperature,
            "max_tokens": self.provider.output_token_limit if max_tokens is None else max_tokens,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if is_deepseek_provider(self.provider):
            if disable_provider_thinking:
                payload["thinking"] = {"type": "disabled"}
            else:
                _apply_deepseek_thinking_payload(payload, self.provider)
        data, latency_ms = self._post_chat_payload(payload)

        try:
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMClientError("PROVIDER_ERROR", "LLM provider returned an unexpected response") from exc

        usage = LLMUsage.from_response_usage(data.get("usage"))
        metadata = self._build_call_metadata(
            payload=payload,
            response_format=response_format,
            call_type=call_type,
            agent_name=agent_name,
            node_name=node_name,
            prompt_metadata=prompt_metadata,
            tool_calling=False,
            tool_count=0,
            usage=usage,
            latency_ms=latency_ms,
        )
        return LLMCallResult(
            content=str(content),
            message=None,
            raw_response_metadata=safe_response_metadata(data),
            call_metadata=metadata,
        )

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        tool_choice: str | dict = "auto",
        preserve_provider_reasoning: bool = False,
    ) -> dict[str, Any]:
        result = self.chat_with_tools_metadata(
            messages,
            tools=tools,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            tool_choice=tool_choice,
            preserve_provider_reasoning=preserve_provider_reasoning,
        )
        return result.message or {}

    def chat_with_tools_metadata(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        tool_choice: str | dict = "auto",
        preserve_provider_reasoning: bool = False,
        call_type: str = "chat_with_tools",
        agent_name: str | None = None,
        node_name: str | None = None,
        prompt_metadata: dict | None = None,
    ) -> LLMCallResult:
        payload = {
            "model": model or self.provider.default_model,
            "messages": apply_global_output_language_policy(
                sanitize_chat_messages(messages, preserve_provider_reasoning=preserve_provider_reasoning)
            ),
            "temperature": self.provider.temperature if temperature is None else temperature,
            "max_tokens": self.provider.output_token_limit if max_tokens is None else max_tokens,
            "tools": tools,
            "tool_choice": tool_choice,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if is_deepseek_provider(self.provider):
            _apply_deepseek_thinking_payload(payload, self.provider)
        data, latency_ms = self._post_chat_payload(payload)

        try:
            message = data["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMClientError("PROVIDER_ERROR", "LLM provider returned an unexpected response") from exc
        if not isinstance(message, dict):
            raise LLMClientError("PROVIDER_ERROR", "LLM provider returned an unexpected message")
        usage = LLMUsage.from_response_usage(data.get("usage"))
        metadata = self._build_call_metadata(
            payload=payload,
            response_format=response_format,
            call_type=call_type,
            agent_name=agent_name,
            node_name=node_name,
            prompt_metadata=prompt_metadata,
            tool_calling=True,
            tool_count=len(tools),
            usage=usage,
            latency_ms=latency_ms,
        )
        return LLMCallResult(
            content=str(message.get("content") or "") if message.get("content") is not None else None,
            message=message,
            raw_response_metadata=safe_response_metadata(data),
            call_metadata=metadata,
        )

    def _post_chat_payload(self, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        headers = {
            "Authorization": f"Bearer {self.provider.api_key}",
            "Content-Type": "application/json",
        }
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=self.provider.timeout_seconds) as client:
                response = client.post(build_chat_completions_url(self.provider.base_url), headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMClientError("TIMEOUT", "LLM provider request timed out") from exc
        except httpx.HTTPError as exc:
            raise LLMClientError("PROVIDER_ERROR", "Failed to call LLM provider") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        if response.status_code in {401, 403}:
            raise LLMClientError("AUTH_FAILED", build_provider_status_message(response, "LLM provider authentication failed"))
        if response.status_code == 404:
            raise LLMClientError("MODEL_NOT_FOUND", build_provider_status_message(response, "LLM base_url or model may be incorrect"))
        if response.status_code == 429:
            raise LLMClientError("RATE_LIMITED", build_provider_status_message(response, "LLM provider rate limit exceeded"))
        if response.status_code >= 500:
            raise LLMClientError("PROVIDER_ERROR", build_provider_status_message(response, "LLM provider returned a server error"))
        if response.status_code >= 400:
            raise LLMClientError(
                "PROVIDER_ERROR",
                build_provider_status_message(response, f"LLM provider request failed with status {response.status_code}"),
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMClientError("PROVIDER_ERROR", "LLM provider returned an unexpected response") from exc
        if not isinstance(data, dict):
            raise LLMClientError("PROVIDER_ERROR", "LLM provider returned an unexpected response")
        return data, latency_ms

    def _build_call_metadata(
        self,
        *,
        payload: dict[str, Any],
        response_format: dict | None,
        call_type: str,
        agent_name: str | None,
        node_name: str | None,
        prompt_metadata: dict | None,
        tool_calling: bool,
        tool_count: int,
        usage: LLMUsage,
        latency_ms: int,
    ) -> LLMCallMetadata:
        prompt_fields = extract_prompt_metadata(prompt_metadata)
        return LLMCallMetadata(
            call_id=new_call_id(),
            provider_id=self.provider.id,
            provider_name=self.provider.name,
            provider_type=self.provider.provider_type,
            model=str(payload.get("model") or self.provider.default_model),
            call_type=call_type,
            agent_name=agent_name,
            node_name=node_name,
            response_format=response_format,
            tool_calling=tool_calling,
            tool_count=tool_count,
            temperature=payload.get("temperature"),
            max_tokens=payload.get("max_tokens"),
            latency_ms=latency_ms,
            ok=True,
            usage=usage,
            estimated_cost=estimate_llm_cost(self.provider, usage),
            **prompt_fields,
        )


class LLMService:
    def __init__(self, settings: Settings, store: LLMProviderConfigStore | None = None, metrics_service: Any | None = None) -> None:
        self.settings = settings
        self.store = store or LLMProviderConfigStore(settings.llm_config_file)
        self.metrics_service = metrics_service

    def health(self) -> dict[str, Any]:
        active_provider = self.get_active_provider()
        return {
            "enabled": self.settings.llm_enable,
            "has_active_provider": active_provider is not None,
            "active_provider": self.to_public_provider(active_provider) if active_provider else None,
        }

    def list_providers(self, mask_api_key: bool = True) -> list[LLMProviderPublic | LLMProviderConfig]:
        providers = self._list_providers_with_env_fallback()
        if not mask_api_key:
            return providers
        return [self.to_public_provider(provider) for provider in providers]

    def get_active_provider(self) -> LLMProviderConfig | None:
        if not self.settings.llm_enable:
            return None
        providers = self._list_providers_with_env_fallback()
        active_provider = next((provider for provider in providers if provider.is_active and provider.enabled), None)
        if active_provider:
            return active_provider
        return next((provider for provider in providers if provider.enabled), None)

    def create_provider(self, payload: LLMProviderCreateRequest) -> LLMProviderPublic:
        self._validate_provider_values(
            provider_type=payload.provider_type,
            name=payload.name,
            base_url=payload.base_url,
            api_key=payload.api_key,
            default_model=payload.default_model,
            timeout_seconds=payload.timeout_seconds,
            temperature=payload.temperature,
            context_window_tokens=payload.context_window_tokens,
            input_token_limit=payload.input_token_limit,
            output_token_limit=payload.output_token_limit if payload.max_tokens is None else payload.max_tokens,
            enable_thinking=payload.enable_thinking,
            reasoning_effort=payload.reasoning_effort,
        )
        providers = self.store.list_providers()
        now = utc_now_iso()
        output_token_limit = payload.output_token_limit if payload.max_tokens is None else payload.max_tokens
        provider = LLMProviderConfig(
            id=str(uuid4()),
            name=payload.name.strip(),
            provider_type=payload.provider_type,
            base_url=payload.base_url.strip(),
            api_key=payload.api_key.strip(),
            default_model=payload.default_model.strip(),
            available_models=normalize_available_models(payload.available_models),
            is_active=payload.enabled and not any(item.is_active for item in providers),
            enabled=payload.enabled,
            enable_thinking=payload.enable_thinking,
            reasoning_effort=payload.reasoning_effort,
            timeout_seconds=payload.timeout_seconds,
            temperature=payload.temperature,
            context_window_tokens=payload.context_window_tokens,
            input_token_limit=payload.input_token_limit,
            output_token_limit=output_token_limit,
            created_at=now,
            updated_at=now,
        )
        if provider.is_active:
            providers = [self._replace_active(item, False) for item in providers]
        providers.append(provider)
        self.store.save_providers(providers)
        return self.to_public_provider(provider)

    def update_provider(self, provider_id: str, payload: LLMProviderUpdateRequest) -> LLMProviderPublic:
        providers = self.store.list_providers()
        index = self._find_provider_index(providers, provider_id)
        provider = providers[index]

        updates = payload.model_dump(exclude_unset=True)
        api_key_update = updates.pop("api_key", None)
        legacy_max_tokens = updates.pop("max_tokens", None)
        if legacy_max_tokens is not None and updates.get("output_token_limit") is None:
            updates["output_token_limit"] = legacy_max_tokens
        for key, value in updates.items():
            if value is None:
                continue
            if key == "available_models":
                setattr(provider, key, normalize_available_models(value))
            elif isinstance(value, str):
                setattr(provider, key, value.strip())
            else:
                setattr(provider, key, value)
        if api_key_update and not is_masked_api_key(api_key_update):
            provider.api_key = api_key_update.strip()

        self._validate_provider_values(
            provider_type=provider.provider_type,
            name=provider.name,
            base_url=provider.base_url,
            api_key=provider.api_key,
            default_model=provider.default_model,
            timeout_seconds=provider.timeout_seconds,
            temperature=provider.temperature,
            context_window_tokens=provider.context_window_tokens,
            input_token_limit=provider.input_token_limit,
            output_token_limit=provider.output_token_limit,
            enable_thinking=provider.enable_thinking,
            reasoning_effort=provider.reasoning_effort,
        )
        if not provider.enabled and provider.is_active:
            provider.is_active = False

        provider.updated_at = utc_now_iso()
        providers[index] = provider
        self.store.save_providers(providers)
        return self.to_public_provider(provider)

    def delete_provider(self, provider_id: str) -> tuple[LLMProviderPublic | None, str]:
        providers = self.store.list_providers()
        index = self._find_provider_index(providers, provider_id)
        removed = providers.pop(index)
        message = "Provider deleted"
        if removed.is_active:
            replacement = next((provider for provider in providers if provider.enabled), None)
            if replacement:
                for provider in providers:
                    provider.is_active = provider.id == replacement.id
                message = f"Provider deleted; active provider switched to {replacement.name}"
            else:
                message = "Provider deleted; no enabled provider remains active"
        self.store.save_providers(providers)
        active_provider = next((provider for provider in providers if provider.is_active), None)
        return self.to_public_provider(active_provider) if active_provider else None, message

    def set_active_provider(self, provider_id: str) -> LLMProviderPublic:
        providers = self.store.list_providers()
        index = self._find_provider_index(providers, provider_id)
        if not providers[index].enabled:
            raise LLMConfigError("disabled provider cannot be active")
        for provider in providers:
            provider.is_active = provider.id == provider_id
            if provider.is_active:
                provider.updated_at = utc_now_iso()
        self.store.save_providers(providers)
        return self.to_public_provider(providers[index])

    def test_provider(self, provider_id: str, prompt: str | None = None) -> dict[str, Any]:
        provider = self._get_provider_by_id(provider_id)
        started_at = time.perf_counter()
        try:
            content = self.chat(
                [
                    {"role": "system", "content": "You are a concise assistant."},
                    {"role": "user", "content": prompt or "请只回复 OK"},
                ],
                provider_id=provider.id,
            )
            return {
                "success": True,
                "provider_id": provider.id,
                "model": provider.default_model,
                "latency_ms": int((time.perf_counter() - started_at) * 1000),
                "content": content,
            }
        except LLMClientError as exc:
            return {
                "success": False,
                "provider_id": provider.id,
                "model": provider.default_model,
                "latency_ms": int((time.perf_counter() - started_at) * 1000),
                "error_code": exc.error_code,
                "message": exc.message,
            }

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        provider_id: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> str:
        result = self.chat_with_metadata(
            messages,
            provider_id=provider_id,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        return str(result.content or "")

    def chat_with_metadata(
        self,
        messages: list[dict[str, Any]],
        *,
        provider_id: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        call_type: str = "chat",
        agent_name: str | None = None,
        node_name: str | None = None,
        prompt_metadata: dict | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
        record_observability: bool = True,
        preserve_provider_reasoning: bool = False,
        disable_provider_thinking: bool = False,
    ) -> LLMCallResult:
        started = time.perf_counter()
        provider = self._get_provider_by_id(provider_id) if provider_id else self.get_active_provider()
        try:
            self._validate_runtime_provider(provider)
            result = GenericOpenAICompatibleClient(provider).chat_with_metadata(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                call_type=call_type,
                agent_name=agent_name,
                node_name=node_name,
                prompt_metadata=prompt_metadata,
                preserve_provider_reasoning=preserve_provider_reasoning,
                disable_provider_thinking=disable_provider_thinking,
            )
            self._record_call_result(result, run_id=run_id, session_id=session_id, enabled=record_observability)
            return result
        except Exception as exc:
            self._record_call_error(
                exc,
                provider=provider,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                call_type=call_type,
                agent_name=agent_name,
                node_name=node_name,
                prompt_metadata=prompt_metadata,
                run_id=run_id,
                session_id=session_id,
                tool_calling=False,
                tool_count=0,
                latency_ms=int((time.perf_counter() - started) * 1000),
                enabled=record_observability,
            )
            raise

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]],
        provider_id: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        tool_choice: str | dict = "auto",
        preserve_provider_reasoning: bool = False,
    ) -> dict[str, Any]:
        result = self.chat_with_tools_metadata(
            messages,
            tools=tools,
            provider_id=provider_id,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            tool_choice=tool_choice,
            preserve_provider_reasoning=preserve_provider_reasoning,
        )
        return result.message or {}

    def chat_with_tools_metadata(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]],
        provider_id: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        tool_choice: str | dict = "auto",
        preserve_provider_reasoning: bool = False,
        call_type: str = "chat_with_tools",
        agent_name: str | None = None,
        node_name: str | None = None,
        prompt_metadata: dict | None = None,
        run_id: str | None = None,
        session_id: str | None = None,
        record_observability: bool = True,
    ) -> LLMCallResult:
        started = time.perf_counter()
        provider = self._get_provider_by_id(provider_id) if provider_id else self.get_active_provider()
        try:
            self._validate_runtime_provider(provider)
            result = GenericOpenAICompatibleClient(provider).chat_with_tools_metadata(
                messages,
                tools=tools,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                tool_choice=tool_choice,
                preserve_provider_reasoning=preserve_provider_reasoning,
                call_type=call_type,
                agent_name=agent_name,
                node_name=node_name,
                prompt_metadata=prompt_metadata,
            )
            self._record_call_result(result, run_id=run_id, session_id=session_id, enabled=record_observability)
            return result
        except Exception as exc:
            self._record_call_error(
                exc,
                provider=provider,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                call_type=call_type,
                agent_name=agent_name,
                node_name=node_name,
                prompt_metadata=prompt_metadata,
                run_id=run_id,
                session_id=session_id,
                tool_calling=True,
                tool_count=len(tools),
                latency_ms=int((time.perf_counter() - started) * 1000),
                enabled=record_observability,
            )
            raise

    def _validate_runtime_provider(self, provider: LLMProviderConfig | None) -> None:
        if provider is None:
            raise LLMConfigError("No active LLM provider is configured")
        if not provider.enabled:
            raise LLMConfigError("LLM provider is disabled")
        if provider.provider_type != OPENAI_COMPATIBLE_PROVIDER_TYPE:
            raise LLMConfigError("Only openai_compatible provider_type is supported")

    def _record_call_result(
        self,
        result: LLMCallResult,
        *,
        run_id: str | None,
        session_id: str | None,
        enabled: bool,
    ) -> None:
        if not enabled or self.metrics_service is None:
            return
        try:
            self.metrics_service.record_call_result(result, run_id=run_id, session_id=session_id)
        except Exception as exc:  # defensive; metrics must not affect agents
            logger.warning("Failed to record LLM call result: %s", exc)

    def _record_call_error(
        self,
        exc: Exception,
        *,
        provider: LLMProviderConfig | None,
        model: str | None,
        temperature: float | None,
        max_tokens: int | None,
        response_format: dict | None,
        call_type: str,
        agent_name: str | None,
        node_name: str | None,
        prompt_metadata: dict | None,
        run_id: str | None,
        session_id: str | None,
        tool_calling: bool,
        tool_count: int,
        latency_ms: int,
        enabled: bool,
    ) -> None:
        if not enabled or self.metrics_service is None:
            return
        prompt_fields = extract_prompt_metadata(prompt_metadata)
        resolved_model = model or (provider.default_model if provider else "")
        usage = LLMUsage()
        metadata = LLMCallMetadata(
            call_id=new_call_id(),
            provider_id=provider.id if provider else None,
            provider_name=provider.name if provider else None,
            provider_type=provider.provider_type if provider else None,
            model=resolved_model,
            call_type=call_type,
            agent_name=agent_name,
            node_name=node_name,
            response_format=response_format,
            tool_calling=tool_calling,
            tool_count=tool_count,
            temperature=temperature if temperature is not None else (provider.temperature if provider else None),
            max_tokens=max_tokens if max_tokens is not None else (provider.output_token_limit if provider else None),
            latency_ms=latency_ms,
            ok=False,
            error_code=getattr(exc, "error_code", exc.__class__.__name__),
            error_message=str(exc),
            usage=usage,
            estimated_cost=estimate_llm_cost(provider, usage) if provider else None,
            created_at=observability_utc_now_iso(),
            **prompt_fields,
        )
        result = LLMCallResult(content=None, message=None, raw_response_metadata={}, call_metadata=metadata)
        self._record_call_result(result, run_id=run_id, session_id=session_id, enabled=True)

    def to_public_provider(self, provider: LLMProviderConfig) -> LLMProviderPublic:
        return LLMProviderPublic(
            id=provider.id,
            name=provider.name,
            provider_type=provider.provider_type,
            base_url=provider.base_url,
            default_model=provider.default_model,
            available_models=provider.available_models,
            api_key_masked=mask_api_key(provider.api_key),
            is_active=provider.is_active,
            enabled=provider.enabled,
            enable_thinking=provider.enable_thinking,
            reasoning_effort=provider.reasoning_effort,
            timeout_seconds=provider.timeout_seconds,
            temperature=provider.temperature,
            context_window_tokens=provider.context_window_tokens,
            input_token_limit=provider.input_token_limit,
            output_token_limit=provider.output_token_limit,
            created_at=provider.created_at,
            updated_at=provider.updated_at,
        )

    def _list_providers_with_env_fallback(self) -> list[LLMProviderConfig]:
        providers = self.store.list_providers()
        if providers:
            return providers
        env_provider = self._build_env_provider()
        return [env_provider] if env_provider else []

    def _build_env_provider(self) -> LLMProviderConfig | None:
        if not all(
            value.strip()
            for value in (
                self.settings.llm_default_base_url,
                self.settings.llm_default_api_key,
                self.settings.llm_default_model,
            )
        ):
            return None
        now = utc_now_iso()
        context_window_tokens = int(os.getenv("LLM_CONTEXT_WINDOW_TOKENS", str(DEFAULT_CONTEXT_WINDOW_TOKENS)))
        input_token_limit = int(os.getenv("LLM_INPUT_TOKEN_LIMIT", str(DEFAULT_INPUT_TOKEN_LIMIT)))
        output_token_limit = int(
            os.getenv(
                "LLM_OUTPUT_TOKEN_LIMIT",
                os.getenv("LLM_MAX_TOKENS", str(DEFAULT_OUTPUT_TOKEN_LIMIT)),
            )
        )
        self._validate_provider_values(
            provider_type=OPENAI_COMPATIBLE_PROVIDER_TYPE,
            name=self.settings.llm_default_provider_name.strip() or "Environment Default",
            base_url=self.settings.llm_default_base_url.strip(),
            api_key=self.settings.llm_default_api_key.strip(),
            default_model=self.settings.llm_default_model.strip(),
            timeout_seconds=60,
            temperature=0.2,
            context_window_tokens=context_window_tokens,
            input_token_limit=input_token_limit,
            output_token_limit=output_token_limit,
        )
        return LLMProviderConfig(
            id="env-default",
            name=self.settings.llm_default_provider_name.strip() or "Environment Default",
            provider_type=OPENAI_COMPATIBLE_PROVIDER_TYPE,
            base_url=self.settings.llm_default_base_url.strip(),
            api_key=self.settings.llm_default_api_key.strip(),
            default_model=self.settings.llm_default_model.strip(),
            context_window_tokens=context_window_tokens,
            input_token_limit=input_token_limit,
            output_token_limit=output_token_limit,
            is_active=True,
            enabled=True,
            created_at=now,
            updated_at=now,
        )

    def _get_provider_by_id(self, provider_id: str | None) -> LLMProviderConfig:
        if not provider_id:
            raise LLMProviderNotFoundError("provider_id is required")
        provider = next((item for item in self._list_providers_with_env_fallback() if item.id == provider_id), None)
        if provider is None:
            raise LLMProviderNotFoundError("LLM provider not found")
        return provider

    def _find_provider_index(self, providers: list[LLMProviderConfig], provider_id: str) -> int:
        for index, provider in enumerate(providers):
            if provider.id == provider_id:
                return index
        raise LLMProviderNotFoundError("LLM provider not found")

    def _replace_active(self, provider: LLMProviderConfig, is_active: bool) -> LLMProviderConfig:
        provider.is_active = is_active
        return provider

    def _validate_provider_values(
        self,
        *,
        provider_type: str,
        name: str,
        base_url: str,
        api_key: str,
        default_model: str,
        timeout_seconds: int,
        temperature: float,
        context_window_tokens: int,
        input_token_limit: int,
        output_token_limit: int,
        enable_thinking: bool = False,
        reasoning_effort: str = "high",
    ) -> None:
        if provider_type != OPENAI_COMPATIBLE_PROVIDER_TYPE:
            raise LLMConfigError("provider_type must be openai_compatible")
        if not name.strip():
            raise LLMConfigError("name is required")
        if not base_url.strip().startswith(("http://", "https://")):
            raise LLMConfigError("base_url must start with http:// or https://")
        if not api_key.strip():
            raise LLMConfigError("api_key is required")
        if not default_model.strip():
            raise LLMConfigError("default_model is required")
        if timeout_seconds < 1 or timeout_seconds > 300:
            raise LLMConfigError("timeout_seconds must be between 1 and 300")
        if temperature < 0 or temperature > 2:
            raise LLMConfigError("temperature must be between 0 and 2")
        if context_window_tokens < 1:
            raise LLMConfigError("context_window_tokens must be greater than 0")
        if input_token_limit < 1:
            raise LLMConfigError("input_token_limit must be greater than 0")
        if output_token_limit < 1:
            raise LLMConfigError("output_token_limit must be greater than 0")
        if input_token_limit + output_token_limit > context_window_tokens:
            raise LLMConfigError("input_token_limit + output_token_limit must be less than or equal to context_window_tokens")
        if enable_thinking and reasoning_effort not in ("high", "max"):
            raise LLMConfigError("reasoning_effort must be 'high' or 'max' when enable_thinking is true")
