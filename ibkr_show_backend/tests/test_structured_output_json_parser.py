import pytest

from app.agents.structured_output.errors import (
    LLM_JSON_PARSE_FAILED,
    LLM_OUTPUT_EMPTY,
    LLM_OUTPUT_NOT_OBJECT,
    StructuredOutputError,
)
from app.agents.structured_output.json_parser import extract_json_object, extract_json_object_lenient


def test_extract_standard_json_object() -> None:
    assert extract_json_object('{"summary": "ok", "score": 1}') == {"summary": "ok", "score": 1}


def test_extract_markdown_json_code_fence() -> None:
    raw = """```json
{"summary": "ok", "score": 1}
```"""
    assert extract_json_object(raw)["summary"] == "ok"


def test_extract_json_from_mixed_markdown_text() -> None:
    raw = """下面是结果：

```json
{"summary": "ok", "confidence": "high"}
```

请查收。"""
    assert extract_json_object(raw) == {"summary": "ok", "confidence": "high"}


def test_extract_json_after_plain_text() -> None:
    raw = '解释文字在前。 {"summary": "ok", "confidence": "medium"} trailing text'
    assert extract_json_object(raw)["confidence"] == "medium"


def test_extract_first_valid_json_object_when_multiple_objects() -> None:
    raw = 'bad {not valid} then {"summary": "first"} and {"summary": "second"}'
    assert extract_json_object(raw) == {"summary": "first"}


def test_array_raises_output_not_object() -> None:
    with pytest.raises(StructuredOutputError) as exc_info:
        extract_json_object('[{"summary": "ok"}]')
    assert exc_info.value.error_code == LLM_OUTPUT_NOT_OBJECT


def test_empty_response_raises_output_empty() -> None:
    with pytest.raises(StructuredOutputError) as exc_info:
        extract_json_object("  ")
    assert exc_info.value.error_code == LLM_OUTPUT_EMPTY


def test_non_json_raises_parse_failed() -> None:
    with pytest.raises(StructuredOutputError) as exc_info:
        extract_json_object("not json at all")
    assert exc_info.value.error_code == LLM_JSON_PARSE_FAILED


def test_truncated_json_raises_parse_failed() -> None:
    with pytest.raises(StructuredOutputError) as exc_info:
        extract_json_object('{"summary": "missing end"')
    assert exc_info.value.error_code == LLM_JSON_PARSE_FAILED


def test_lenient_parser_returns_none_on_error() -> None:
    assert extract_json_object_lenient("not json") is None
