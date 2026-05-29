from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.schemas.admin_llm import LLMProviderCreateRequest, LLMProviderUpdateRequest
from app.services.llm_service import (
    CHINESE_OUTPUT_POLICY,
    CHINESE_OUTPUT_POLICY_MARKER,
    DEFAULT_CONTEXT_WINDOW_TOKENS,
    DEFAULT_INPUT_TOKEN_LIMIT,
    GenericOpenAICompatibleClient,
    LLMClientError,
    LLMConfigError,
    LLMProviderConfig,
    LLMProviderConfigStore,
    LLMService,
    apply_global_output_language_policy,
    build_provider_status_message,
    build_chat_completions_url,
    is_deepseek_provider,
    mask_api_key,
    sanitize_chat_messages,
)

client = TestClient(app)


@dataclass
class DummySettings:
    llm_enable: bool = True
    llm_default_provider_name: str = ""
    llm_default_base_url: str = ""
    llm_default_api_key: str = ""
    llm_default_model: str = ""
    llm_config_file: str = ""


def make_service(config_file: Path) -> LLMService:
    return LLMService(DummySettings(llm_config_file=str(config_file)), LLMProviderConfigStore(str(config_file)))


def create_provider(service: LLMService, name: str, enabled: bool = True):
    return service.create_provider(
        LLMProviderCreateRequest(
            name=name,
            provider_type="openai_compatible",
            base_url="https://example.com/v1",
            api_key=f"sk-{name}-1234567890",
            default_model=f"{name}-model",
            enabled=enabled,
        )
    )


def test_mask_api_key_never_exposes_plain_key() -> None:
    assert mask_api_key("sk-1234567890abcdef") == "sk-****cdef"
    assert mask_api_key("") == ""
    assert mask_api_key("short") == "****"


def test_build_chat_url_normalizes_trailing_slash() -> None:
    assert build_chat_completions_url("https://example.com/v1") == "https://example.com/v1/chat/completions"
    assert build_chat_completions_url("https://example.com/v1/") == "https://example.com/v1/chat/completions"


def test_provider_error_message_includes_response_detail() -> None:
    response = httpx.Response(
        400,
        json={
            "error": {
                "code": "400",
                "message": "max_tokens is too large: 200001",
                "param": "max_tokens",
            }
        },
    )

    message = build_provider_status_message(response, "LLM provider request failed with status 400")

    assert "max_tokens is too large" in message
    assert "param=max_tokens" in message


def test_provider_store_migrates_legacy_max_tokens_to_output_limit(tmp_path: Path) -> None:
    config_file = tmp_path / "llm.json"
    config_file.write_text(
        """
        {
          "providers": [
            {
              "id": "legacy",
              "name": "Legacy Provider",
              "provider_type": "openai_compatible",
              "base_url": "https://example.com/v1",
              "api_key": "sk-legacy-1234567890",
              "default_model": "legacy-model",
              "max_tokens": 4096,
              "enabled": true,
              "is_active": true
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    service = make_service(config_file)
    provider = service.store.list_providers()[0]
    public_provider = service.list_providers()[0]

    assert provider.context_window_tokens == DEFAULT_CONTEXT_WINDOW_TOKENS
    assert provider.input_token_limit == DEFAULT_INPUT_TOKEN_LIMIT
    assert provider.output_token_limit == 4096
    assert provider.max_tokens == 4096
    assert public_provider.context_window_tokens == DEFAULT_CONTEXT_WINDOW_TOKENS
    assert public_provider.input_token_limit == DEFAULT_INPUT_TOKEN_LIMIT
    assert public_provider.output_token_limit == 4096


def test_create_provider_rejects_token_profile_over_context(tmp_path: Path) -> None:
    service = make_service(tmp_path / "llm.json")

    with pytest.raises(LLMConfigError, match="input_token_limit \\+ output_token_limit"):
        service.create_provider(
            LLMProviderCreateRequest(
                name="too-small-context",
                provider_type="openai_compatible",
                base_url="https://example.com/v1",
                api_key="sk-too-small-1234567890",
                default_model="bad-model",
                context_window_tokens=10000,
                input_token_limit=9000,
                output_token_limit=2000,
            )
        )


def test_env_provider_rejects_token_profile_over_context(tmp_path: Path, monkeypatch) -> None:
    settings = DummySettings(
        llm_default_provider_name="Env Provider",
        llm_default_base_url="https://example.com/v1",
        llm_default_api_key="sk-env-1234567890",
        llm_default_model="env-model",
        llm_config_file=str(tmp_path / "llm.json"),
    )
    service = LLMService(settings, LLMProviderConfigStore(str(tmp_path / "llm.json")))
    monkeypatch.setenv("LLM_CONTEXT_WINDOW_TOKENS", "10000")
    monkeypatch.setenv("LLM_INPUT_TOKEN_LIMIT", "9000")
    monkeypatch.setenv("LLM_OUTPUT_TOKEN_LIMIT", "2000")

    with pytest.raises(LLMConfigError, match="input_token_limit \\+ output_token_limit"):
        service.get_active_provider()


def test_openai_compatible_client_sends_output_limit_as_max_tokens(monkeypatch) -> None:
    captured_payloads: list[dict] = []

    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            captured_payloads.append(json)
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok", "tool_calls": []}}]})

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    provider = LLMProviderConfig(
        id="provider-1",
        name="MiniMax",
        provider_type="openai_compatible",
        base_url="https://example.com/v1",
        api_key="sk-minimax-1234567890",
        default_model="minimax-text-2.7",
        context_window_tokens=200000,
        input_token_limit=150000,
        output_token_limit=10000,
    )
    client = GenericOpenAICompatibleClient(provider)

    assert client.chat([{"role": "user", "content": "hello"}]) == "ok"
    client.chat_with_tools(
        [{"role": "user", "content": "hello"}],
        tools=[{"type": "function", "function": {"name": "noop", "parameters": {"type": "object"}}}],
    )

    assert [payload["max_tokens"] for payload in captured_payloads] == [10000, 10000]
    assert all("context_window_tokens" not in payload for payload in captured_payloads)
    assert all("input_token_limit" not in payload for payload in captured_payloads)
    assert all("output_token_limit" not in payload for payload in captured_payloads)


def test_openai_compatible_client_chat_with_metadata_parses_usage(monkeypatch) -> None:
    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-1",
                    "created": 123,
                    "model": "model-a",
                    "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}],
                    "usage": {
                        "prompt_tokens": 11,
                        "completion_tokens": 7,
                        "total_tokens": 18,
                        "completion_tokens_details": {"reasoning_tokens": 3},
                        "prompt_tokens_details": {"cached_tokens": 5},
                    },
                },
            )

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    provider = LLMProviderConfig(
        id="provider-1",
        name="Provider",
        provider_type="openai_compatible",
        base_url="https://example.com/v1",
        api_key="sk-provider-1234567890",
        default_model="model-a",
        input_price_per_1m_tokens=1.0,
        output_price_per_1m_tokens=2.0,
    )

    result = GenericOpenAICompatibleClient(provider).chat_with_metadata(
        [{"role": "user", "content": "hello"}],
        call_type="planner",
        agent_name="account_copilot",
        node_name="planner",
        prompt_metadata={"prompt_key": "account_copilot_planner", "version": "v2", "content_hash": "abc", "source": "admin_active"},
    )

    assert result.content == "ok"
    assert result.call_metadata.usage.prompt_tokens == 11
    assert result.call_metadata.usage.completion_tokens == 7
    assert result.call_metadata.usage.reasoning_tokens == 3
    assert result.call_metadata.usage.cached_tokens == 5
    assert result.call_metadata.prompt_key == "account_copilot_planner"
    assert result.call_metadata.prompt_version == "v2"
    assert result.call_metadata.prompt_hash == "abc"
    assert result.call_metadata.prompt_source == "admin_active"
    assert result.raw_response_metadata["finish_reason"] == "stop"
    assert result.call_metadata.estimated_cost == pytest.approx(0.000025)


def test_openai_compatible_client_chat_with_tools_metadata_parses_usage(monkeypatch) -> None:
    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-tools",
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "noop", "arguments": "{}"}}],
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13},
                },
            )

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    provider = LLMProviderConfig(
        id="provider-1",
        name="Provider",
        provider_type="openai_compatible",
        base_url="https://example.com/v1",
        api_key="sk-provider-1234567890",
        default_model="model-a",
    )
    tools = [{"type": "function", "function": {"name": "noop", "parameters": {"type": "object"}}}]

    result = GenericOpenAICompatibleClient(provider).chat_with_tools_metadata([{"role": "user", "content": "hello"}], tools=tools)

    assert result.message["tool_calls"][0]["function"]["name"] == "noop"
    assert result.call_metadata.tool_calling is True
    assert result.call_metadata.tool_count == 1
    assert result.call_metadata.usage.total_tokens == 13


def test_openai_compatible_client_strips_provider_private_reasoning_fields(monkeypatch) -> None:
    captured_payloads: list[dict] = []

    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            captured_payloads.append(json)
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    provider = LLMProviderConfig(
        id="provider-1",
        name="Xiaomi",
        provider_type="openai_compatible",
        base_url="https://example.com/v1",
        api_key="sk-xiaomi-1234567890",
        default_model="mimo",
    )
    client = GenericOpenAICompatibleClient(provider)

    client.chat([
        {
            "role": "assistant",
            "content": None,
            "reasoning_content": "private chain of thought",
            "thinking": "provider private field",
        },
        {"role": "user", "content": "continue"},
    ])

    # Empty-content reasoning-only message should be dropped entirely.
    # Chinese output policy system message is prepended.
    messages = captured_payloads[0]["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "continue"


def test_llm_service_records_success_metric_with_prompt_metadata(tmp_path: Path, monkeypatch) -> None:
    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
                },
            )

    class FakeMetricsService:
        def __init__(self) -> None:
            self.calls = []

        def record_call_result(self, result, *, run_id=None, session_id=None) -> None:
            self.calls.append((result, run_id, session_id))

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    metrics = FakeMetricsService()
    service = make_service(tmp_path / "llm.json")
    service.metrics_service = metrics
    create_provider(service, "first")

    result = service.chat_with_metadata(
        [{"role": "user", "content": "hello"}],
        call_type="planner",
        agent_name="account_copilot",
        node_name="planner",
        prompt_metadata={"prompt_key": "account_copilot_planner", "version": "v2", "content_hash": "abc", "source": "admin_active"},
        run_id="run-1",
        session_id="session-1",
    )

    assert result.content == "ok"
    recorded, run_id, session_id = metrics.calls[0]
    assert run_id == "run-1"
    assert session_id == "session-1"
    assert recorded.call_metadata.ok is True
    assert recorded.call_metadata.prompt_key == "account_copilot_planner"
    assert recorded.call_metadata.usage.total_tokens == 5


def test_llm_service_records_failure_metric_and_reraises(tmp_path: Path, monkeypatch) -> None:
    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            return httpx.Response(429, json={"error": {"message": "slow down"}})

    class FakeMetricsService:
        def __init__(self) -> None:
            self.calls = []

        def record_call_result(self, result, *, run_id=None, session_id=None) -> None:
            self.calls.append(result)

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    metrics = FakeMetricsService()
    service = make_service(tmp_path / "llm.json")
    service.metrics_service = metrics
    create_provider(service, "first")

    with pytest.raises(LLMClientError, match="rate limit"):
        service.chat_with_metadata([{"role": "user", "content": "hello"}], prompt_metadata={"prompt_key": "trade_review_main"})

    recorded = metrics.calls[0]
    assert recorded.call_metadata.ok is False
    assert recorded.call_metadata.error_code == "RATE_LIMITED"
    assert recorded.call_metadata.prompt_key == "trade_review_main"


def test_activate_provider_keeps_only_one_active_and_rejects_disabled(tmp_path: Path) -> None:
    service = make_service(tmp_path / "llm.json")
    first = create_provider(service, "first")
    second = create_provider(service, "second")
    disabled = create_provider(service, "disabled", enabled=False)

    service.set_active_provider(second.id)
    providers = service.store.list_providers()

    assert [provider.id for provider in providers if provider.is_active] == [second.id]
    assert not next(provider for provider in providers if provider.id == first.id).is_active

    try:
        service.set_active_provider(disabled.id)
    except LLMConfigError as exc:
        assert "disabled provider cannot be active" in str(exc)
    else:
        raise AssertionError("disabled provider should not become active")


def test_update_provider_api_key_rules(tmp_path: Path) -> None:
    service = make_service(tmp_path / "llm.json")
    provider = create_provider(service, "first")
    original_key = service.store.list_providers()[0].api_key

    service.update_provider(provider.id, LLMProviderUpdateRequest(name="renamed"))
    assert service.store.list_providers()[0].api_key == original_key

    service.update_provider(provider.id, LLMProviderUpdateRequest(api_key=""))
    assert service.store.list_providers()[0].api_key == original_key

    service.update_provider(provider.id, LLMProviderUpdateRequest(api_key="sk-new-real-key"))
    assert service.store.list_providers()[0].api_key == "sk-new-real-key"


def test_admin_llm_routes_require_login(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LLM_CONFIG_FILE", str(tmp_path / "llm.json"))
    get_settings.cache_clear()

    try:
        response = client.get("/api/admin/llm/providers")
    finally:
        get_settings.cache_clear()

    assert response.status_code == 401
    assert response.json()["detail"] == "请先登录后查看该模块"


def test_sanitize_chat_messages_drops_empty_content_reasoning_only_message() -> None:
    """Messages with empty content and only reasoning fields are dropped."""
    messages = [
        {"role": "assistant", "content": "", "reasoning_content": "private chain of thought"},
        {"role": "user", "content": "continue"},
    ]
    result = sanitize_chat_messages(messages)
    assert len(result) == 1
    assert result[0]["role"] == "user"
    assert result[0]["content"] == "continue"


def test_sanitize_chat_messages_keeps_message_with_content_and_reasoning() -> None:
    """Messages with real content AND reasoning fields keep content, drop reasoning."""
    messages = [
        {"role": "assistant", "content": "Here is the answer", "reasoning_content": "thinking..."},
    ]
    result = sanitize_chat_messages(messages)
    assert len(result) == 1
    assert result[0]["content"] == "Here is the answer"
    assert "reasoning_content" not in result[0]


def test_sanitize_chat_messages_keeps_message_with_tool_calls_and_reasoning() -> None:
    """Messages with tool_calls are kept even if content is empty."""
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "test", "arguments": "{}"}}],
            "reasoning_content": "thinking...",
        },
    ]
    result = sanitize_chat_messages(messages)
    assert len(result) == 1
    assert "tool_calls" in result[0]
    assert "reasoning_content" not in result[0]
    assert result[0]["content"] == ""


def test_sanitize_chat_messages_can_preserve_reasoning_for_provider_roundtrip() -> None:
    """Tool-calling loops can keep provider reasoning fields for APIs that require round-tripping."""
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "test", "arguments": "{}"}}],
            "reasoning_content": "thinking...",
            "thinking": "private",
            "reasoning": "private",
        },
    ]
    result = sanitize_chat_messages(messages, preserve_provider_reasoning=True)
    assert len(result) == 1
    assert result[0]["reasoning_content"] == "thinking..."
    assert result[0]["thinking"] == "private"
    assert result[0]["reasoning"] == "private"
    assert result[0]["content"] == ""


def test_provider_enable_thinking_defaults_false(tmp_path: Path) -> None:
    """Newly created provider has enable_thinking=False by default."""
    service = make_service(tmp_path / "llm.json")
    provider = create_provider(service, "test-provider")

    stored = service.store.list_providers()[0]
    assert stored.enable_thinking is False

    public = service.list_providers()[0]
    assert public.enable_thinking is False


def test_provider_enable_thinking_can_be_updated(tmp_path: Path) -> None:
    """enable_thinking can be toggled via update."""
    service = make_service(tmp_path / "llm.json")
    provider = create_provider(service, "test-provider")

    service.update_provider(provider.id, LLMProviderUpdateRequest(enable_thinking=True))
    assert service.store.list_providers()[0].enable_thinking is True

    service.update_provider(provider.id, LLMProviderUpdateRequest(enable_thinking=False))
    assert service.store.list_providers()[0].enable_thinking is False


def test_legacy_provider_without_enable_thinking_defaults_false(tmp_path: Path) -> None:
    """Old JSON config without enable_thinking field defaults to False."""
    config_file = tmp_path / "llm.json"
    config_file.write_text(
        """
        {
          "providers": [
            {
              "id": "legacy",
              "name": "Legacy Provider",
              "provider_type": "openai_compatible",
              "base_url": "https://example.com/v1",
              "api_key": "sk-legacy-1234567890",
              "default_model": "legacy-model",
              "enabled": true,
              "is_active": true
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    service = make_service(config_file)
    provider = service.store.list_providers()[0]
    assert provider.enable_thinking is False

    public = service.list_providers()[0]
    assert public.enable_thinking is False


def test_openai_compatible_client_does_not_send_thinking_params_when_disabled(monkeypatch) -> None:
    """When enable_thinking=False, no thinking/reasoning params in request payload."""
    captured_payloads: list[dict] = []

    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            captured_payloads.append(json)
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    provider = LLMProviderConfig(
        id="provider-1",
        name="Test",
        provider_type="openai_compatible",
        base_url="https://example.com/v1",
        api_key="sk-test-1234567890",
        default_model="test-model",
        enable_thinking=False,
    )
    client = GenericOpenAICompatibleClient(provider)
    client.chat([{"role": "user", "content": "hello"}])

    payload = captured_payloads[0]
    assert "thinking" not in payload
    assert "reasoning_effort" not in payload
    assert "enable_thinking" not in payload
    assert "reasoning" not in payload


def test_provider_create_request_enable_thinking_defaults_false() -> None:
    """LLMProviderCreateRequest defaults enable_thinking to False."""
    req = LLMProviderCreateRequest(
        name="test",
        base_url="https://example.com/v1",
        api_key="sk-test-123",
        default_model="test-model",
    )
    assert req.enable_thinking is False


def test_provider_public_includes_enable_thinking(tmp_path: Path) -> None:
    """LLMProviderPublic response includes enable_thinking field."""
    service = make_service(tmp_path / "llm.json")
    create_provider(service, "test-provider")

    public = service.list_providers()[0]
    assert hasattr(public, "enable_thinking")
    assert public.enable_thinking is False


def test_deepseek_provider_thinking_enabled_sends_correct_payload(monkeypatch) -> None:
    """DeepSeek provider with enable_thinking=True sends thinking enabled and reasoning_effort."""
    captured_payloads: list[dict] = []

    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb) -> None:
            return None
        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            captured_payloads.append(json)
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    provider = LLMProviderConfig(
        id="ds-1",
        name="DeepSeek",
        provider_type="openai_compatible",
        base_url="https://api.deepseek.com/v1",
        api_key="sk-ds-1234567890",
        default_model="deepseek-chat",
        enable_thinking=True,
        reasoning_effort="max",
    )
    client = GenericOpenAICompatibleClient(provider)
    client.chat([{"role": "user", "content": "hello"}])

    payload = captured_payloads[0]
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "max"


def test_deepseek_provider_thinking_disabled_sends_thinking_disabled(monkeypatch) -> None:
    """DeepSeek provider with enable_thinking=False sends thinking disabled."""
    captured_payloads: list[dict] = []

    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb) -> None:
            return None
        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            captured_payloads.append(json)
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    provider = LLMProviderConfig(
        id="ds-1",
        name="DeepSeek",
        provider_type="openai_compatible",
        base_url="https://api.deepseek.com/v1",
        api_key="sk-ds-1234567890",
        default_model="deepseek-chat",
        enable_thinking=False,
    )
    client = GenericOpenAICompatibleClient(provider)
    client.chat([{"role": "user", "content": "hello"}])

    payload = captured_payloads[0]
    assert payload["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in payload


def test_non_deepseek_provider_does_not_send_thinking_params(monkeypatch) -> None:
    """Non-DeepSeek provider doesn't send thinking/reasoning_effort."""
    captured_payloads: list[dict] = []

    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb) -> None:
            return None
        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            captured_payloads.append(json)
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    provider = LLMProviderConfig(
        id="other-1",
        name="Other",
        provider_type="openai_compatible",
        base_url="https://api.openai.com/v1",
        api_key="sk-other-1234567890",
        default_model="gpt-4",
        enable_thinking=True,
    )
    client = GenericOpenAICompatibleClient(provider)
    client.chat([{"role": "user", "content": "hello"}])

    payload = captured_payloads[0]
    assert "thinking" not in payload
    assert "reasoning_effort" not in payload


def test_deepseek_thinking_enabled_removes_temperature_from_payload(monkeypatch) -> None:
    """When DeepSeek thinking is enabled, temperature/top_p/etc are removed."""
    captured_payloads: list[dict] = []

    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb) -> None:
            return None
        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            captured_payloads.append(json)
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    provider = LLMProviderConfig(
        id="ds-1",
        name="DeepSeek",
        provider_type="openai_compatible",
        base_url="https://api.deepseek.com/v1",
        api_key="sk-ds-1234567890",
        default_model="deepseek-chat",
        enable_thinking=True,
        reasoning_effort="high",
        temperature=0.5,
    )
    client = GenericOpenAICompatibleClient(provider)
    client.chat([{"role": "user", "content": "hello"}])

    payload = captured_payloads[0]
    assert "temperature" not in payload
    assert "top_p" not in payload
    assert "presence_penalty" not in payload
    assert "frequency_penalty" not in payload
    assert payload["thinking"] == {"type": "enabled"}


def test_deepseek_thinking_disabled_keeps_temperature(monkeypatch) -> None:
    """When DeepSeek thinking is disabled, temperature is kept."""
    captured_payloads: list[dict] = []

    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb) -> None:
            return None
        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            captured_payloads.append(json)
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    provider = LLMProviderConfig(
        id="ds-1",
        name="DeepSeek",
        provider_type="openai_compatible",
        base_url="https://api.deepseek.com/v1",
        api_key="sk-ds-1234567890",
        default_model="deepseek-chat",
        enable_thinking=False,
        temperature=0.5,
    )
    client = GenericOpenAICompatibleClient(provider)
    client.chat([{"role": "user", "content": "hello"}])

    payload = captured_payloads[0]
    assert payload["temperature"] == 0.5
    assert payload["thinking"] == {"type": "disabled"}


def test_chat_with_metadata_preserve_provider_reasoning_keeps_reasoning_content(monkeypatch) -> None:
    """chat_with_metadata(preserve_provider_reasoning=True) keeps reasoning_content in messages."""
    captured_payloads: list[dict] = []

    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb) -> None:
            return None
        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            captured_payloads.append(json)
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    provider = LLMProviderConfig(
        id="provider-1",
        name="Test",
        provider_type="openai_compatible",
        base_url="https://api.deepseek.com/v1",
        api_key="sk-test-1234567890",
        default_model="deepseek-chat",
    )
    client = GenericOpenAICompatibleClient(provider)
    client.chat_with_metadata(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "test", "arguments": "{}"}}],
                "reasoning_content": "thinking...",
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "result"},
            {"role": "user", "content": "continue"},
        ],
        preserve_provider_reasoning=True,
    )

    messages = captured_payloads[0]["messages"]
    # Chinese output policy system message is prepended
    assert messages[0]["role"] == "system"
    assistant_msg = messages[1]
    assert assistant_msg["reasoning_content"] == "thinking..."
    assert "tool_calls" in assistant_msg


def test_chat_with_metadata_default_strips_reasoning_content(monkeypatch) -> None:
    """chat_with_metadata default (preserve_provider_reasoning=False) strips reasoning_content."""
    captured_payloads: list[dict] = []

    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb) -> None:
            return None
        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            captured_payloads.append(json)
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    provider = LLMProviderConfig(
        id="provider-1",
        name="Test",
        provider_type="openai_compatible",
        base_url="https://api.deepseek.com/v1",
        api_key="sk-test-1234567890",
        default_model="deepseek-chat",
    )
    client = GenericOpenAICompatibleClient(provider)
    client.chat_with_metadata(
        [
            {
                "role": "assistant",
                "content": "answer",
                "reasoning_content": "thinking...",
            },
            {"role": "user", "content": "continue"},
        ],
    )

    messages = captured_payloads[0]["messages"]
    # Chinese output policy system message is prepended
    assert messages[0]["role"] == "system"
    assert messages[1]["content"] == "answer"
    assert "reasoning_content" not in messages[1]


def test_deepseek_model_name_detection(monkeypatch) -> None:
    """DeepSeek detection works via model name starting with 'deepseek'."""
    captured_payloads: list[dict] = []

    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb) -> None:
            return None
        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            captured_payloads.append(json)
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    provider = LLMProviderConfig(
        id="ds-1",
        name="Custom Proxy",
        provider_type="openai_compatible",
        base_url="https://custom-proxy.example.com/v1",
        api_key="sk-ds-1234567890",
        default_model="deepseek-r1",
        enable_thinking=True,
        reasoning_effort="max",
    )
    client = GenericOpenAICompatibleClient(provider)
    client.chat([{"role": "user", "content": "hello"}])

    payload = captured_payloads[0]
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "max"


def test_provider_reasoning_effort_defaults_high(tmp_path: Path) -> None:
    """Newly created provider has reasoning_effort='high' by default."""
    service = make_service(tmp_path / "llm.json")
    create_provider(service, "test-provider")

    stored = service.store.list_providers()[0]
    assert stored.reasoning_effort == "high"

    public = service.list_providers()[0]
    assert public.reasoning_effort == "high"


def test_provider_reasoning_effort_can_be_updated(tmp_path: Path) -> None:
    """reasoning_effort can be updated."""
    from app.schemas.admin_llm import LLMProviderUpdateRequest

    service = make_service(tmp_path / "llm.json")
    provider = create_provider(service, "test-provider")

    service.update_provider(provider.id, LLMProviderUpdateRequest(reasoning_effort="max"))
    assert service.store.list_providers()[0].reasoning_effort == "max"

    service.update_provider(provider.id, LLMProviderUpdateRequest(reasoning_effort="high"))
    assert service.store.list_providers()[0].reasoning_effort == "high"


def test_legacy_provider_without_reasoning_effort_defaults_high(tmp_path: Path) -> None:
    """Old JSON config without reasoning_effort field defaults to 'high'."""
    config_file = tmp_path / "llm.json"
    config_file.write_text(
        """
        {
          "providers": [
            {
              "id": "legacy",
              "name": "Legacy Provider",
              "provider_type": "openai_compatible",
              "base_url": "https://example.com/v1",
              "api_key": "sk-legacy-1234567890",
              "default_model": "legacy-model",
              "enabled": true,
              "is_active": true
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    service = make_service(config_file)
    provider = service.store.list_providers()[0]
    assert provider.reasoning_effort == "high"

    public = service.list_providers()[0]
    assert public.reasoning_effort == "high"


def test_chat_with_tools_metadata_deepseek_thinking_enabled(monkeypatch) -> None:
    """chat_with_tools_metadata applies DeepSeek thinking payload."""
    captured_payloads: list[dict] = []

    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb) -> None:
            return None
        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            captured_payloads.append(json)
            return httpx.Response(200, json={"choices": [{"message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "noop", "arguments": "{}"}}],
            }}]})

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    provider = LLMProviderConfig(
        id="ds-1",
        name="DeepSeek",
        provider_type="openai_compatible",
        base_url="https://api.deepseek.com/v1",
        api_key="sk-ds-1234567890",
        default_model="deepseek-chat",
        enable_thinking=True,
        reasoning_effort="high",
    )
    tools = [{"type": "function", "function": {"name": "noop", "parameters": {"type": "object"}}}]
    client = GenericOpenAICompatibleClient(provider)
    client.chat_with_tools_metadata([{"role": "user", "content": "hello"}], tools=tools)

    payload = captured_payloads[0]
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "high"
    assert "temperature" not in payload


def test_disable_provider_thinking_overrides_deepseek(monkeypatch) -> None:
    """disable_provider_thinking=True forces thinking disabled even for DeepSeek."""
    captured_payloads: list[dict] = []

    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb) -> None:
            return None
        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            captured_payloads.append(json)
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    provider = LLMProviderConfig(
        id="ds-1",
        name="DeepSeek",
        provider_type="openai_compatible",
        base_url="https://api.deepseek.com/v1",
        api_key="sk-ds-1234567890",
        default_model="deepseek-chat",
        enable_thinking=True,
        reasoning_effort="max",
    )
    client = GenericOpenAICompatibleClient(provider)
    client.chat_with_metadata(
        [{"role": "user", "content": "hello"}],
        disable_provider_thinking=True,
    )

    payload = captured_payloads[0]
    assert payload["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in payload


def test_is_deepseek_provider_detects_by_base_url() -> None:
    """is_deepseek_provider detects DeepSeek by base_url."""
    from app.services.llm_service import is_deepseek_provider

    ds = LLMProviderConfig(id="1", name="DS", provider_type="openai_compatible", base_url="https://api.deepseek.com/v1", api_key="sk-test", default_model="chat")
    assert is_deepseek_provider(ds) is True

    other = LLMProviderConfig(id="2", name="Other", provider_type="openai_compatible", base_url="https://api.openai.com/v1", api_key="sk-test", default_model="gpt-4")
    assert is_deepseek_provider(other) is False


def test_is_deepseek_provider_detects_by_model_name() -> None:
    """is_deepseek_provider detects DeepSeek by model name."""
    from app.services.llm_service import is_deepseek_provider

    ds = LLMProviderConfig(id="1", name="Proxy", provider_type="openai_compatible", base_url="https://proxy.example.com/v1", api_key="sk-test", default_model="deepseek-r1")
    assert is_deepseek_provider(ds) is True

    other = LLMProviderConfig(id="2", name="Proxy", provider_type="openai_compatible", base_url="https://proxy.example.com/v1", api_key="sk-test", default_model="qwen-max")
    assert is_deepseek_provider(other) is False


# --- Chinese output policy tests ---

def test_apply_global_output_language_policy_prepends_when_no_system_message() -> None:
    messages = [{"role": "user", "content": "hello"}]
    result = apply_global_output_language_policy(messages)
    assert len(result) == 2
    assert result[0]["role"] == "system"
    assert CHINESE_OUTPUT_POLICY_MARKER in result[0]["content"]
    assert result[1]["role"] == "user"
    assert result[1]["content"] == "hello"


def test_apply_global_output_language_policy_appends_to_existing_system_message() -> None:
    messages = [{"role": "system", "content": "You are a helpful assistant."}, {"role": "user", "content": "hello"}]
    result = apply_global_output_language_policy(messages)
    assert len(result) == 2
    assert result[0]["role"] == "system"
    assert "You are a helpful assistant." in result[0]["content"]
    assert CHINESE_OUTPUT_POLICY_MARKER in result[0]["content"]


def test_apply_global_output_language_policy_does_not_duplicate() -> None:
    messages = [{"role": "system", "content": CHINESE_OUTPUT_POLICY}, {"role": "user", "content": "hello"}]
    result = apply_global_output_language_policy(messages)
    assert len(result) == 2
    assert result[0]["content"].count(CHINESE_OUTPUT_POLICY_MARKER) == 1


def test_apply_global_output_language_policy_handles_empty_messages() -> None:
    result = apply_global_output_language_policy([])
    assert len(result) == 1
    assert result[0]["role"] == "system"
    assert CHINESE_OUTPUT_POLICY_MARKER in result[0]["content"]


def test_apply_global_output_language_policy_preserves_non_string_content() -> None:
    messages = [{"role": "system", "content": None}, {"role": "user", "content": "hello"}]
    result = apply_global_output_language_policy(messages)
    assert result[0]["role"] == "system"
    assert CHINESE_OUTPUT_POLICY_MARKER in result[0]["content"]


def test_apply_global_output_language_policy_does_not_mutate_original() -> None:
    original = [{"role": "system", "content": "original"}, {"role": "user", "content": "hello"}]
    result = apply_global_output_language_policy(original)
    assert original[0]["content"] == "original"
    assert CHINESE_OUTPUT_POLICY_MARKER in result[0]["content"]


def test_chat_with_metadata_injects_chinese_policy_without_system_message(monkeypatch) -> None:
    captured_payloads: list[dict] = []

    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb) -> None:
            return None
        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            captured_payloads.append(json)
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    provider = LLMProviderConfig(
        id="p1", name="Test", provider_type="openai_compatible",
        base_url="https://example.com/v1", api_key="sk-test-1234567890", default_model="test-model",
    )
    client = GenericOpenAICompatibleClient(provider)
    client.chat_with_metadata([{"role": "user", "content": "hello"}])

    messages = captured_payloads[0]["messages"]
    assert messages[0]["role"] == "system"
    assert CHINESE_OUTPUT_POLICY_MARKER in messages[0]["content"]


def test_chat_with_metadata_appends_chinese_policy_to_existing_system(monkeypatch) -> None:
    captured_payloads: list[dict] = []

    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb) -> None:
            return None
        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            captured_payloads.append(json)
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    provider = LLMProviderConfig(
        id="p1", name="Test", provider_type="openai_compatible",
        base_url="https://example.com/v1", api_key="sk-test-1234567890", default_model="test-model",
    )
    client = GenericOpenAICompatibleClient(provider)
    client.chat_with_metadata([
        {"role": "system", "content": "You are a trade analyst."},
        {"role": "user", "content": "analyze AAPL"},
    ])

    messages = captured_payloads[0]["messages"]
    assert "You are a trade analyst." in messages[0]["content"]
    assert CHINESE_OUTPUT_POLICY_MARKER in messages[0]["content"]


def test_chat_with_tools_metadata_injects_chinese_policy(monkeypatch) -> None:
    captured_payloads: list[dict] = []

    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb) -> None:
            return None
        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            captured_payloads.append(json)
            return httpx.Response(200, json={"choices": [{"message": {
                "role": "assistant", "content": None,
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "noop", "arguments": "{}"}}],
            }}]})

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    provider = LLMProviderConfig(
        id="p1", name="Test", provider_type="openai_compatible",
        base_url="https://example.com/v1", api_key="sk-test-1234567890", default_model="test-model",
    )
    tools = [{"type": "function", "function": {"name": "noop", "parameters": {"type": "object"}}}]
    client = GenericOpenAICompatibleClient(provider)
    client.chat_with_tools_metadata([{"role": "user", "content": "hello"}], tools=tools)

    messages = captured_payloads[0]["messages"]
    assert messages[0]["role"] == "system"
    assert CHINESE_OUTPUT_POLICY_MARKER in messages[0]["content"]


def test_chinese_policy_not_duplicated_in_multi_round_tool_calls(monkeypatch) -> None:
    captured_payloads: list[dict] = []

    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb) -> None:
            return None
        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            captured_payloads.append(json)
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    provider = LLMProviderConfig(
        id="p1", name="Test", provider_type="openai_compatible",
        base_url="https://example.com/v1", api_key="sk-test-1234567890", default_model="test-model",
    )
    client = GenericOpenAICompatibleClient(provider)
    # Simulate a multi-round call where the first system message already has the policy
    client.chat_with_metadata([
        {"role": "system", "content": "You are a trade analyst.\n\n" + CHINESE_OUTPUT_POLICY},
        {"role": "assistant", "content": "analysis"},
        {"role": "user", "content": "continue"},
    ])

    messages = captured_payloads[0]["messages"]
    assert messages[0]["content"].count(CHINESE_OUTPUT_POLICY_MARKER) == 1


def test_chinese_policy_preserves_reasoning_content_with_preserve_flag(monkeypatch) -> None:
    captured_payloads: list[dict] = []

    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb) -> None:
            return None
        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            captured_payloads.append(json)
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    provider = LLMProviderConfig(
        id="ds-1", name="DeepSeek", provider_type="openai_compatible",
        base_url="https://api.deepseek.com/v1", api_key="sk-ds-1234567890", default_model="deepseek-chat",
    )
    client = GenericOpenAICompatibleClient(provider)
    client.chat_with_metadata(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "test", "arguments": "{}"}}],
                "reasoning_content": "chain of thought",
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "result"},
            {"role": "user", "content": "continue"},
        ],
        preserve_provider_reasoning=True,
    )

    messages = captured_payloads[0]["messages"]
    # Policy should be prepended
    assert messages[0]["role"] == "system"
    assert CHINESE_OUTPUT_POLICY_MARKER in messages[0]["content"]
    # reasoning_content should be preserved on assistant message
    assistant_msg = messages[1]
    assert assistant_msg["reasoning_content"] == "chain of thought"


def test_chinese_policy_json_object_response_format_still_injected(monkeypatch) -> None:
    captured_payloads: list[dict] = []

    class FakeHttpClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb) -> None:
            return None
        def post(self, url: str, headers: dict, json: dict) -> httpx.Response:
            captured_payloads.append(json)
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": '{"key": "value"}'}}]})

    monkeypatch.setattr("app.services.llm_service.httpx.Client", FakeHttpClient)
    provider = LLMProviderConfig(
        id="p1", name="Test", provider_type="openai_compatible",
        base_url="https://example.com/v1", api_key="sk-test-1234567890", default_model="test-model",
    )
    client = GenericOpenAICompatibleClient(provider)
    client.chat_with_metadata(
        [{"role": "user", "content": "return json"}],
        response_format={"type": "json_object"},
    )

    messages = captured_payloads[0]["messages"]
    assert messages[0]["role"] == "system"
    assert CHINESE_OUTPUT_POLICY_MARKER in messages[0]["content"]
    assert captured_payloads[0]["response_format"] == {"type": "json_object"}
