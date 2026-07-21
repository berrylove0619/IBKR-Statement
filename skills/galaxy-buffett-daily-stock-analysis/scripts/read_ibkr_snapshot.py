#!/usr/bin/env python3
"""Read one sanitized, provably same-batch IBKR snapshot from local Elasticsearch."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


ACCOUNT_LIMIT = 1000
POSITION_LIMIT = 10000
MAX_TRANSFORM_SKEW = timedelta(minutes=5)
JOIN_FIELDS = ("account_id", "report_date", "source_query_type", "source_file_name")


class SnapshotError(RuntimeError):
    pass


def parse_bool(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise SnapshotError(f"{name} must be true or false")


def is_repo_root(path: Path) -> bool:
    return (path / "ibkr_show_backend").is_dir() and (path / "ibkr_show_worker").is_dir()


def discover_repo_root(explicit: str | None) -> Path:
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if is_repo_root(candidate):
            return candidate
        raise SnapshotError("--repo-root is not an IBKR-Statement checkout")
    checked: set[Path] = set()
    for start in (Path.cwd().resolve(), Path(__file__).resolve().parent):
        for candidate in (start, *start.parents):
            for possible in (candidate, candidate / "IBKR-Statement"):
                if possible not in checked and is_repo_root(possible):
                    return possible
                checked.add(possible)
    raise SnapshotError("IBKR-Statement root not found; pass --repo-root or run inside its parent tree")


class LocalElasticsearch:
    def __init__(self, base_url: str, username: str | None, password: str | None, verify_certs: bool) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise SnapshotError("Elasticsearch URL must be loopback HTTP(S); remote sources are refused")
        if parsed.username or parsed.password:
            raise SnapshotError("Elasticsearch credentials must come from the existing environment")
        if bool(username) != bool(password):
            raise SnapshotError("Elasticsearch credentials are incomplete")
        self.base_url = base_url.rstrip("/")
        self.authorization = None
        if username and password:
            token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
            self.authorization = f"Basic {token}"
        self.context = None
        if parsed.scheme == "https":
            self.context = ssl.create_default_context() if verify_certs else ssl._create_unverified_context()

    def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.authorization:
            headers["Authorization"] = self.authorization
        request = Request(
            f"{self.base_url}/{quote(index, safe='')}/_search",
            data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        kwargs: dict[str, Any] = {"timeout": 5}
        if self.context is not None:
            kwargs["context"] = self.context
        try:
            with urlopen(request, **kwargs) as response:
                return json.load(response)
        except HTTPError as exc:
            raise SnapshotError(f"Elasticsearch returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise SnapshotError("local Elasticsearch is unavailable or returned invalid JSON") from exc


def local_client(base_url: str) -> LocalElasticsearch:
    verify_certs = parse_bool(os.getenv("ES_VERIFY_CERTS", "false"), "ES_VERIFY_CERTS")
    return LocalElasticsearch(base_url, os.getenv("ES_USERNAME"), os.getenv("ES_PASSWORD"), verify_certs)


def _term_filters(body: dict[str, Any]) -> list[dict[str, Any]]:
    filters = body.get("query", {}).get("bool", {}).get("filter", [])
    return filters if isinstance(filters, list) else []


class FixtureElasticsearch:
    """Offline fake that applies exact term filters and sort/size semantics."""

    def __init__(self, fixture: Path) -> None:
        self.payload = json.loads(fixture.read_text(encoding="utf-8"))

    def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
        key = "account_search" if "account" in index else "position_search"
        configured = self.payload.get(key)
        if not isinstance(configured, dict):
            raise SnapshotError(f"fixture missing {key}")
        documents = all_sources(configured)
        for clause in _term_filters(body):
            term = clause.get("term") if isinstance(clause, dict) else None
            if isinstance(term, dict) and len(term) == 1:
                field, expected = next(iter(term.items()))
                documents = [item for item in documents if item.get(field) == expected]
        for spec in reversed(body.get("sort", [])):
            if isinstance(spec, dict) and len(spec) == 1:
                field, options = next(iter(spec.items()))
                reverse = isinstance(options, dict) and options.get("order") == "desc"
                documents.sort(key=lambda item: str(item.get(field) or ""), reverse=reverse)
        total = len(documents)
        fields = body.get("_source")
        hits = []
        for document in documents[: int(body.get("size", 10))]:
            source = {field: document[field] for field in fields if field in document} if isinstance(fields, list) else document
            hits.append({"_source": source})
        return {"hits": {"total": {"value": total, "relation": "eq"}, "hits": hits}}


def all_sources(response: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        hit["_source"]
        for hit in response.get("hits", {}).get("hits", [])
        if isinstance(hit, dict) and isinstance(hit.get("_source"), dict)
    ]


def total_hits(response: dict[str, Any]) -> int:
    total = response.get("hits", {}).get("total", 0)
    return int(total.get("value", 0)) if isinstance(total, dict) else int(total or 0)


def account_query(account_id: str | None) -> dict[str, Any]:
    query: dict[str, Any] = {"match_all": {}}
    if account_id:
        query = {"bool": {"filter": [{"term": {"account_id": account_id}}]}}
    return {
        "size": ACCOUNT_LIMIT,
        "track_total_hits": True,
        "query": query,
        "sort": [{"report_date": {"order": "desc", "missing": "_last"}}, {"ingested_at": {"order": "desc", "missing": "_last"}}],
        "_source": [*JOIN_FIELDS, "currency", "ingested_at"],
    }


def position_query(account: dict[str, Any]) -> dict[str, Any]:
    return {
        "size": POSITION_LIMIT,
        "track_total_hits": True,
        "query": {"bool": {"filter": [{"term": {field: account[field]}} for field in JOIN_FIELDS]}},
        "sort": [{"position_value": {"order": "desc", "missing": "_last"}}, {"symbol": {"order": "asc", "missing": "_last"}}],
        "_source": [
            *JOIN_FIELDS, "currency", "asset_class", "symbol", "description", "quantity", "mark_price",
            "position_value", "average_cost_price", "cost_basis_money", "percent_of_nav", "ingested_at",
        ],
    }


def _nonempty_join(account: dict[str, Any]) -> bool:
    return all(isinstance(account.get(field), str) and bool(account[field].strip()) for field in JOIN_FIELDS)


def _utc_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _batch_time(account: dict[str, Any], positions: list[dict[str, Any]]) -> str | None:
    account_time = _utc_time(account.get("ingested_at"))
    position_times = [_utc_time(item.get("ingested_at")) for item in positions]
    if account_time is None or any(item is None for item in position_times):
        return None
    concrete = [item for item in position_times if item is not None]
    if any(item < account_time or item - account_time > MAX_TRANSFORM_SKEW for item in concrete):
        return None
    return max([account_time, *concrete]).isoformat()


def _non_zero(position: dict[str, Any]) -> bool:
    quantity, market_value = position.get("quantity"), position.get("position_value")
    return (isinstance(quantity, (int, float)) and quantity != 0) or (isinstance(market_value, (int, float)) and market_value != 0)


def _holding(position: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": position.get("symbol"), "name": position.get("description"), "asset_class": position.get("asset_class"),
        "quantity": position.get("quantity"), "mark_price": position.get("mark_price"), "market_value": position.get("position_value"),
        "average_cost": position.get("average_cost_price"), "cost_basis": position.get("cost_basis_money"),
        "portfolio_weight": position.get("percent_of_nav"), "currency": position.get("currency"),
    }


def _result(base: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
    return {**base, "status": status, "reason": reason, "snapshot": None, "total_holdings": 0, "holdings": []}


def build_snapshot(client: Any, account_index: str, position_index: str, account_id: str | None = None) -> dict[str, Any]:
    base = {
        "contract_version": "ibkr_holdings_input_v2",
        "data_source": {"type": "elasticsearch", "account_index": account_index, "position_index": position_index},
        "selection": {
            "import_success_persisted": False,
            "rule": "latest usable account document with exact four-key join and transformer-order batch-time proof",
            "sort": ["report_date desc", "ingested_at desc"],
        },
    }
    response = client.search(account_index, account_query(account_id))
    accounts = all_sources(response)
    if total_hits(response) > ACCOUNT_LIMIT:
        return _result(base, "incomplete", "account candidate set is truncated")
    if not accounts:
        return _result(base, "empty", "no account snapshots")
    account_ids = {item.get("account_id") for item in accounts if item.get("account_id")}
    if not account_id and len(account_ids) != 1:
        return _result(base, "incomplete", "account selection is ambiguous; set --account-id or IBKR_ACCOUNT_ID")
    account = accounts[0]
    if not _nonempty_join(account):
        return _result(base, "incomplete", "latest account candidate lacks a required join key")

    position_response = client.search(position_index, position_query(account))
    positions = all_sources(position_response)
    if total_hits(position_response) > POSITION_LIMIT:
        return _result(base, "incomplete", "position candidate set is truncated")
    if not positions:
        return _result(base, "incomplete", "latest account candidate has no exact four-key position join")
    if any(any(item.get(field) != account[field] for field in JOIN_FIELDS) for item in positions):
        return _result(base, "incomplete", "position response failed exact four-key post-validation")
    document_batch_time = _batch_time(account, positions)
    if document_batch_time is None:
        return _result(base, "incomplete", "document timestamps cannot prove one transformer batch")

    non_zero = [item for item in positions if _non_zero(item)]
    non_zero.sort(key=lambda item: (-abs(float(item.get("position_value") or 0)), str(item.get("symbol") or "")))
    snapshot = {
        "document_batch_time": document_batch_time,
        "holdings_as_of": str(account["report_date"]),
        "base_currency": account.get("currency"),
        "source_query_type": account["source_query_type"],
        "source_identifier_present": bool(account["source_file_name"]),
    }
    if not non_zero:
        return {**base, "status": "empty", "reason": "same-batch snapshot has no non-zero positions", "snapshot": snapshot, "total_holdings": 0, "holdings": []}
    return {**base, "status": "ready", "snapshot": snapshot, "total_holdings": len(non_zero), "holdings": [_holding(item) for item in non_zero]}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root")
    parser.add_argument("--fixture", type=Path, help="Offline test fixture; never use for a real morning report")
    parser.add_argument("--es-url", default=os.getenv("ES_HOST", "http://127.0.0.1:9200"))
    parser.add_argument("--account-id", default=os.getenv("IBKR_ACCOUNT_ID"), help="Select one account; value is never output")
    parser.add_argument("--account-index", default=os.getenv("ES_ACCOUNT_INDEX", "ibkr_account_daily_snapshot_v1"))
    parser.add_argument("--position-index", default=os.getenv("ES_POSITION_INDEX", "ibkr_position_daily_snapshot_v1"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        discover_repo_root(args.repo_root)
        if args.fixture:
            client = FixtureElasticsearch(args.fixture)
        else:
            client = local_client(args.es_url)
        payload = build_snapshot(client, args.account_index, args.position_index, args.account_id)
    except (SnapshotError, FileNotFoundError, json.JSONDecodeError) as exc:
        payload = {"contract_version": "ibkr_holdings_input_v2", "status": "source_unavailable", "reason": str(exc)}
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["status"] == "ready" else 3


if __name__ == "__main__":
    raise SystemExit(main())
