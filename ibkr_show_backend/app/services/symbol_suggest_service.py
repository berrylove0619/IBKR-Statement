from __future__ import annotations

import json
import logging
from difflib import SequenceMatcher

from app.clients.es_client import ElasticsearchClient
from app.core.config import Settings
from app.services.llm_service import LLMConfigError, LLMClientError, LLMService
from app.services.longbridge_service import LongbridgeExternalDataClient, normalize_longbridge_symbol
from app.services.trade_review_evidence import normalize_ibkr_symbol

logger = logging.getLogger(__name__)

MAX_DISTANCE_FOR_AUTO_CORRECT = 2
MAX_DISTANCE_FOR_SUGGESTION = 4


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[len(b)]


class SymbolSuggestService:
    def __init__(
        self,
        es_client: ElasticsearchClient,
        settings: Settings,
        llm_service: LLMService,
        longbridge_client: LongbridgeExternalDataClient,
    ) -> None:
        self.es_client = es_client
        self.settings = settings
        self.llm_service = llm_service
        self.longbridge_client = longbridge_client

    def _fetch_all_symbols(self) -> list[str]:
        symbols: set[str] = set()
        for index in (self.settings.es_trade_index, self.settings.es_position_index):
            try:
                response = self.es_client.search(
                    index=index,
                    body={
                        "size": 0,
                        "aggs": {
                            "unique_symbols": {
                                "terms": {"field": "symbol", "size": 500},
                            }
                        },
                    },
                )
                for bucket in response.get("aggregations", {}).get("unique_symbols", {}).get("buckets", []):
                    raw = str(bucket.get("key", "")).strip()
                    if raw:
                        symbols.add(normalize_ibkr_symbol(raw).upper())
            except Exception:
                logger.warning("Failed to aggregate symbols from index %s", index, exc_info=True)
        return sorted(s for s in symbols if s)

    def suggest(self, q: str, limit: int = 5) -> list[dict]:
        query = normalize_ibkr_symbol(q).upper()
        if not query:
            return []

        all_symbols = self._fetch_all_symbols()
        scored = []
        for sym in all_symbols:
            dist = _levenshtein(query, sym.upper())
            if dist <= MAX_DISTANCE_FOR_SUGGESTION:
                ratio = SequenceMatcher(None, query, sym.upper()).ratio()
                scored.append({"symbol": sym, "distance": dist, "similarity": round(ratio, 3)})
        scored.sort(key=lambda x: (x["distance"], -x["similarity"]))
        return scored[:limit]

    def correct_symbol(self, q: str) -> dict | None:
        query = normalize_ibkr_symbol(q).upper()
        if not query:
            return None

        suggestions = self.suggest(query, limit=1)
        if suggestions and suggestions[0]["distance"] <= MAX_DISTANCE_FOR_AUTO_CORRECT:
            return {"symbol": suggestions[0]["symbol"], "source": "fuzzy", "reason": f"与 {query} 拼写最接近的历史标的"}

        llm_result = self._llm_correct(query)
        if not llm_result:
            return None

        corrected = llm_result.get("symbol", "").strip().upper()
        if not corrected or corrected == query:
            return None

        if not self._validate_with_longbridge(corrected):
            return None

        return {"symbol": corrected, "source": "llm", "reason": llm_result.get("reason", "")}

    def _llm_correct(self, query: str) -> dict | None:
        provider = self.llm_service.get_active_provider()
        if not provider:
            return None
        try:
            raw = self.llm_service.chat(
                [
                    {"role": "system", "content": "你是股票代码纠错助手。用户可能拼错了美股股票代码，请给出最可能的正确代码。只输出 JSON。"},
                    {
                        "role": "user",
                        "content": (
                            f"用户输入的代码是 `{query}`，这可能是一个拼写错误。"
                            "请判断最可能的正确美股股票代码是什么。\n\n"
                            '输出格式：{"symbol": "正确代码", "reason": "简短理由"}\n'
                            "如果无法确定，输出 {\"symbol\": \"\", \"reason\": \"无法识别\"}"
                        ),
                    },
                ],
                temperature=0.1,
                max_tokens=200,
                response_format={"type": "json_object"},
            )
            return json.loads(raw)
        except (LLMConfigError, LLMClientError, json.JSONDecodeError):
            logger.warning("LLM symbol correction failed for %s", query, exc_info=True)
            return None

    def _validate_with_longbridge(self, symbol: str) -> bool:
        try:
            normalized = normalize_longbridge_symbol(symbol)
            result = self.longbridge_client.get_quote_snapshot(normalized)
            return bool(result)
        except Exception:
            return False
