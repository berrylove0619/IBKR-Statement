from app.core.config import get_settings
from app.services.llm_service import LLMService


class LLMClient:
    """Compatibility wrapper that routes AI calls through LLMService."""

    def __init__(self, llm_service: LLMService | None = None) -> None:
        self.llm_service = llm_service or LLMService(get_settings())

    def generate(self, prompt: str) -> str:
        return self.llm_service.chat(
            [
                {"role": "system", "content": "You are a concise assistant."},
                {"role": "user", "content": prompt},
            ]
        )
