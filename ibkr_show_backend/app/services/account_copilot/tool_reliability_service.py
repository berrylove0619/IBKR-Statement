from __future__ import annotations

import json
import re
import time
from statistics import mean
from typing import Any
from uuid import uuid4

from app.agents.account_copilot.agent_eval_cases import AGENT_EVAL_CASES, FORBIDDEN_AGENT_TOOL_PATTERNS
from app.agents.account_copilot.skill_registry import AccountCopilotSkillRegistry
from app.agents.account_copilot.tool_probe_cases import IBKR_PROBE_ARGUMENTS, build_safe_longbridge_arguments
from app.agents.account_copilot.tool_registry import AccountCopilotToolRegistry
from app.services.account_copilot.tool_reliability_repository import AccountCopilotToolReliabilityRepository

SENSITIVE_KEY_RE = re.compile(r"(token|access_token|refresh_token|authorization|api_key|secret|password|cookie)", re.I)


def sanitize_text(value: Any, limit: int = 300) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = SENSITIVE_KEY_RE.sub("[redacted_key]", text)
    return text[:limit]


def data_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        return len(str(value))


def is_empty_data(value: Any) -> bool:
    if value in (None, "", [], {}):
        return True
    if isinstance(value, dict):
        data = value.get("data", value)
        return data in (None, "", [], {})
    return False


def percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * pct))))
    return ordered[index]


class AccountCopilotToolReliabilityService:
    def __init__(
        self,
        repository: AccountCopilotToolReliabilityRepository | None,
        tool_registry: AccountCopilotToolRegistry,
        skill_registry: AccountCopilotSkillRegistry,
        longbridge_adapter: object | None = None,
    ) -> None:
        self.repository = repository
        self.tool_registry = tool_registry
        self.skill_registry = skill_registry
        self.longbridge_adapter = longbridge_adapter

    def run_probe(
        self,
        *,
        include_ibkr_live: bool = False,
        include_longbridge_live: bool = False,
        include_agent_eval: bool = False,
        symbol: str = "AMD.US",
        keyword: str = "AMD",
        max_tools: int = 200,
        persist: bool = True,
    ) -> dict[str, Any]:
        probe_run_id = f"probe_run_{uuid4().hex[:12]}"
        results: list[dict[str, Any]] = []
        results.extend(self.probe_registry(probe_run_id))
        if include_ibkr_live:
            results.extend(self.probe_ibkr_tools(probe_run_id, symbol=symbol))
        if include_longbridge_live:
            results.extend(self.probe_longbridge_tools(probe_run_id, symbol=symbol, keyword=keyword, max_tools=max_tools))
        if include_agent_eval:
            results.extend(self.probe_agent_eval(probe_run_id))
        if persist and self.repository is not None:
            for result in results:
                self.repository.create_result(result)
        return {"probe_run_id": probe_run_id, "results": results, "summary": summarize_probe_results(results)}

    def probe_registry(self, probe_run_id: str) -> list[dict[str, Any]]:
        results = []
        for spec in self.tool_registry.list_exposed_specs():
            schema_ok = bool(spec.schema.get("name") and spec.schema.get("parameters"))
            results.append(
                make_result(
                    probe_run_id=probe_run_id,
                    tool_name=spec.name,
                    tool_domain=domain_for_tool(spec.name),
                    category=spec.category,
                    probe_type="schema",
                    status="pass" if schema_ok and spec.read_only else "fail",
                    ok=schema_ok and spec.read_only,
                    metadata={"read_only": spec.read_only, "approval_required": spec.approval_required},
                )
            )
        for skill in self.skill_registry.list_exposed_specs():
            schema_ok = bool(skill.input_schema)
            results.append(
                make_result(
                    probe_run_id=probe_run_id,
                    tool_name=skill.name,
                    tool_domain="skill",
                    category="skill",
                    probe_type="schema",
                    status="pass" if schema_ok and skill.read_only and skill.approval_required else "fail",
                    ok=schema_ok and skill.read_only and skill.approval_required,
                    metadata={"read_only": skill.read_only, "approval_required": skill.approval_required, "risk_level": skill.risk_level},
                )
            )
        return results

    def probe_ibkr_tools(self, probe_run_id: str, *, symbol: str = "AMD.US") -> list[dict[str, Any]]:
        results = []
        normalized_symbol = symbol.split(".")[0]
        for spec in [spec for spec in self.tool_registry.list_exposed_specs() if spec.name.startswith("ibkr_")]:
            args = dict(IBKR_PROBE_ARGUMENTS.get(spec.name, {}))
            if "symbol" in args:
                args["symbol"] = normalized_symbol
            results.append(self._invoke_spec(probe_run_id, spec, args, "invoke"))
        return results

    def probe_longbridge_tools(self, probe_run_id: str, *, symbol: str = "AMD.US", keyword: str = "AMD", max_tools: int = 200) -> list[dict[str, Any]]:
        if self.longbridge_adapter is None:
            return [
                make_result(
                    probe_run_id=probe_run_id,
                    tool_name="longbridge_catalog",
                    tool_domain="longbridge",
                    category="catalog",
                    probe_type="catalog",
                    status="fail",
                    ok=False,
                    error_code="LONGBRIDGE_ADAPTER_UNAVAILABLE",
                    error_message="Longbridge adapter is not configured",
                )
            ]
        started = time.perf_counter()
        try:
            catalog = self.longbridge_adapter.get_tool_catalog(force_refresh=True)
            latency = int((time.perf_counter() - started) * 1000)
        except Exception as exc:
            return [
                make_result(
                    probe_run_id=probe_run_id,
                    tool_name="longbridge_catalog",
                    tool_domain="longbridge",
                    category="catalog",
                    probe_type="catalog",
                    status="fail",
                    ok=False,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    error_code="CATALOG_ERROR",
                    error_message=str(exc)[:300],
                )
            ]
        tools = list(catalog.get("tools") or [])[:max_tools]
        public_tools = [tool for tool in tools if tool.get("classification") == "public_market_readonly" and tool.get("allowed")]
        results = [
            make_result(
                probe_run_id=probe_run_id,
                tool_name="longbridge_catalog",
                tool_domain="longbridge",
                category="catalog",
                probe_type="catalog",
                status="pass" if public_tools else "partial",
                ok=bool(public_tools),
                latency_ms=latency,
                data_empty=not bool(public_tools),
                data_size=len(public_tools),
                metadata={"source": catalog.get("source"), "blocked_count": len(catalog.get("blocked") or [])},
            )
        ]
        for tool in public_tools:
            schema = tool.get("input_schema") or {}
            schema_ok = isinstance(schema, dict)
            results.append(
                make_result(
                    probe_run_id=probe_run_id,
                    tool_name=tool["name"],
                    tool_domain="longbridge",
                    category=classify_longbridge_category(tool["name"], tool.get("description")),
                    probe_type="schema",
                    status="pass" if schema_ok else "partial",
                    ok=schema_ok,
                    metadata={"schema_empty": not bool(schema)},
                )
            )
            args, skip_code = build_safe_longbridge_arguments(tool["name"], schema, symbol=symbol, keyword=keyword)
            if skip_code:
                results.append(
                    make_result(
                        probe_run_id=probe_run_id,
                        tool_name=tool["name"],
                        tool_domain="longbridge",
                        category=classify_longbridge_category(tool["name"], tool.get("description")),
                        probe_type="invoke",
                        status="skipped",
                        ok=False,
                        error_code=skip_code,
                        error_message="Required arguments could not be constructed safely",
                    )
                )
                continue
            results.append(self._call_longbridge(probe_run_id, tool["name"], args or {}, classify_longbridge_category(tool["name"], tool.get("description"))))
        return results

    def probe_agent_eval(self, probe_run_id: str) -> list[dict[str, Any]]:
        results = []
        for case in AGENT_EVAL_CASES:
            forbidden_called = any(pattern in " ".join(case.get("expected_tools", [])) for pattern in FORBIDDEN_AGENT_TOOL_PATTERNS)
            results.append(
                make_result(
                    probe_run_id=probe_run_id,
                    tool_name=case["id"],
                    tool_domain="agent",
                    category="agent_eval",
                    probe_type="agent_eval",
                    status="fail" if forbidden_called else "skipped",
                    ok=not forbidden_called,
                    metadata={
                        "question": case["question"],
                        "expected_tools": case["expected_tools"],
                        "expected_behavior": case["expected_behavior"],
                        "forbidden_called": forbidden_called,
                        "evidence_based": None,
                    },
                )
            )
        return results

    def _invoke_spec(self, probe_run_id: str, spec: Any, args: dict[str, Any], probe_type: str) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            if spec.handler is None:
                raise RuntimeError("Tool handler is not configured")
            envelope = spec.handler(**args)
            latency = int((time.perf_counter() - started) * 1000)
            ok = bool(envelope.get("ok")) if isinstance(envelope, dict) else False
            return make_result(
                probe_run_id=probe_run_id,
                tool_name=spec.name,
                tool_domain=domain_for_tool(spec.name),
                category=spec.category,
                probe_type=probe_type,
                status="pass" if ok else "partial",
                ok=ok,
                latency_ms=latency,
                error_code=envelope.get("error_code") or (envelope.get("metadata") or {}).get("error_code") if isinstance(envelope, dict) else "INVALID_ENVELOPE",
                error_message=sanitize_text(envelope.get("message") or (envelope.get("metadata") or {}).get("message")) if isinstance(envelope, dict) else "Invalid envelope",
                arguments_preview=sanitize_arguments(args),
                data_empty=is_empty_data(envelope.get("data") if isinstance(envelope, dict) else None),
                data_size=data_size(envelope.get("data") if isinstance(envelope, dict) else None),
                data_limitations=envelope.get("data_limitations", []) if isinstance(envelope, dict) else [],
            )
        except Exception as exc:
            return make_result(
                probe_run_id=probe_run_id,
                tool_name=spec.name,
                tool_domain=domain_for_tool(spec.name),
                category=spec.category,
                probe_type=probe_type,
                status="fail",
                ok=False,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error_code="TOOL_EXCEPTION",
                error_message=str(exc)[:300],
                arguments_preview=sanitize_arguments(args),
            )

    def _call_longbridge(self, probe_run_id: str, tool_name: str, args: dict[str, Any], category: str) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            envelope = self.longbridge_adapter.call(tool_name, args)
            latency = int((time.perf_counter() - started) * 1000)
            ok = bool(envelope.get("ok"))
            return make_result(
                probe_run_id=probe_run_id,
                tool_name=tool_name,
                tool_domain="longbridge",
                category=category,
                probe_type="invoke",
                status="pass" if ok and not is_empty_data(envelope.get("data")) else "partial" if ok else "fail",
                ok=ok,
                latency_ms=latency,
                error_code=envelope.get("error_code"),
                error_message=sanitize_text(envelope.get("message")),
                arguments_preview=sanitize_arguments(args),
                data_empty=is_empty_data(envelope.get("data")),
                data_size=data_size(envelope.get("data")),
                data_limitations=envelope.get("data_limitations") or [],
            )
        except Exception as exc:
            return make_result(
                probe_run_id=probe_run_id,
                tool_name=tool_name,
                tool_domain="longbridge",
                category=category,
                probe_type="invoke",
                status="fail",
                ok=False,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error_code="LONGBRIDGE_EXCEPTION",
                error_message=str(exc)[:300],
                arguments_preview=sanitize_arguments(args),
            )


def make_result(**kwargs: Any) -> dict[str, Any]:
    return {
        "id": kwargs.get("id") or f"probe_{uuid4().hex[:12]}",
        "probe_run_id": kwargs["probe_run_id"],
        "tool_name": kwargs["tool_name"],
        "tool_domain": kwargs["tool_domain"],
        "category": kwargs.get("category") or "",
        "probe_type": kwargs["probe_type"],
        "status": kwargs.get("status") or ("pass" if kwargs.get("ok") else "fail"),
        "ok": bool(kwargs.get("ok")),
        "latency_ms": int(kwargs.get("latency_ms") or 0),
        "error_code": kwargs.get("error_code"),
        "error_message": sanitize_text(kwargs.get("error_message")),
        "arguments_preview": sanitize_arguments(kwargs.get("arguments_preview") or {}),
        "data_empty": bool(kwargs.get("data_empty", False)),
        "data_size": int(kwargs.get("data_size") or 0),
        "data_limitations": list(kwargs.get("data_limitations") or []),
        "metadata": kwargs.get("metadata") or {},
    }


def sanitize_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    safe = {}
    for key, value in (arguments or {}).items():
        if SENSITIVE_KEY_RE.search(str(key)):
            safe[key] = "***REDACTED***"
        else:
            safe[key] = value
    return safe


def domain_for_tool(name: str) -> str:
    if name.startswith("ibkr_"):
        return "ibkr"
    if name.startswith("longbridge_"):
        return "longbridge"
    return "agent"


def classify_longbridge_category(name: str, description: str | None = None) -> str:
    haystack = f"{name} {description or ''}".lower()
    for category, terms in {
        "quote": ["quote"],
        "candles": ["candle", "history"],
        "news": ["news"],
        "company": ["company", "static"],
        "financial": ["financial", "forecast", "eps"],
        "valuation": ["valuation", "peer"],
        "analyst": ["analyst", "rating", "consensus"],
        "calendar": ["calendar"],
        "market": ["market"],
    }.items():
        if any(term in haystack for term in terms):
            return category
    return "other_public"


def summarize_probe_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [int(result.get("latency_ms") or 0) for result in results if int(result.get("latency_ms") or 0) > 0]
    counts = {status: len([result for result in results if result.get("status") == status]) for status in ("pass", "fail", "partial", "skipped")}
    return {
        "total_tools": len({result.get("tool_name") for result in results}),
        "total_results": len(results),
        **{f"{status}_count": count for status, count in counts.items()},
        "avg_latency_ms": int(mean(latencies)) if latencies else 0,
        "p95_latency_ms": percentile(latencies, 0.95),
    }
