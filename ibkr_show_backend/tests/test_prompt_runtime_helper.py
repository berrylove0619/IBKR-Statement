from app.agents.prompt_runtime import resolve_runtime_prompt


class FakePromptService:
    def __init__(self, *, content: str = "CUSTOM", fail: bool = False) -> None:
        self.content = content
        self.fail = fail

    def get_runtime_prompt(self, prompt_key: str, fallback: str | None = None) -> dict:
        if self.fail:
            raise RuntimeError("prompt service unavailable")
        return {
            "content": self.content,
            "metadata": {
                "prompt_key": prompt_key,
                "version": "v2",
                "content_hash": "abc123",
                "source": "admin_active",
            },
        }


def test_resolve_runtime_prompt_without_service_returns_fallback() -> None:
    content, metadata = resolve_runtime_prompt(None, "demo_prompt", "DEFAULT")

    assert content == "DEFAULT"
    assert metadata["source"] == "fallback"
    assert metadata["prompt_key"] == "demo_prompt"


def test_resolve_runtime_prompt_uses_admin_active_content() -> None:
    content, metadata = resolve_runtime_prompt(FakePromptService(content="CUSTOM"), "demo_prompt", "DEFAULT")

    assert content == "CUSTOM"
    assert metadata["source"] == "admin_active"
    assert metadata["version"] == "v2"
    assert metadata["content_hash"] == "abc123"


def test_resolve_runtime_prompt_records_error_and_falls_back() -> None:
    content, metadata = resolve_runtime_prompt(FakePromptService(fail=True), "demo_prompt", "DEFAULT")

    assert content == "DEFAULT"
    assert metadata["source"] == "fallback"
    assert "prompt service unavailable" in metadata["error"]
