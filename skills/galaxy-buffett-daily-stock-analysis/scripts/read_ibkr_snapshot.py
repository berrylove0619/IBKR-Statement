#!/usr/bin/env python3
"""Read one sanitized, deterministic IBKR holdings snapshot from local Elasticsearch."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


class SnapshotError(RuntimeError):
    pass


def is_repo_root(path: Path) -> bool:
    return (path / "ibkr_show_backend").is_dir() and (path / "ibkr_show_worker").is_dir()


def discover_repo_root(explicit: str | None) -> Path:
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if is_repo_root(candidate):
            return candidate
        raise SnapshotError("--repo-root is not an IBKR-Statement checkout")

    starts = [Path.cwd().resolve(), Path(__file__).resolve().parent]
    checked: set[Path] = set()
    for start in starts:
        for candidate in (start, *start.parents):
            for possible in (candidate, candidate / "IBKR-Statement"):
                if possible in checked:
                    continue
                checked.add(possible)
                if is_repo_root(possible):
                    return possible
    raise SnapshotError("IBKR-Statement root not found; pass --repo-root or run inside its parent tree")


class LocalElasticsearch:
    def __init__(self, base_url: str) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise SnapshotError("Elasticsearch URL must be loopback HTTP(S); remote sources are refused")
        self.base_url = base_url.rstrip("/")

    def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{quote(index, safe='')}/_search"
        request = Request(
            url,
            data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=5) as response:
                return json.load(response)
        except HTTPError as exc:
            raise SnapshotError(f"Elasticsearch returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise SnapshotError("local Elasticsearch is unavailable or returned invalid JSON") from exc


class FixtureElasticsearch:
    def __init__(self, fixture: Path) -> None:
        self.payload = json.loads(fixture.read_text(encoding="utf-8"))

    def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
        key = "account_search" if "account" in index else "position_search"
        response = self.payload.get(key)
        if not isinstance(response, dict):
            raise SnapshotError(f"fixture missing {key}")
        return response


def first_source(response: dict[str, Any]) -> dict[str, Any] | None:
    hits = response.get("hits", {}).get("hits", [])
    if not hits:
        return None
    source = hits[0].get("_source")
    return source if isinstance(source, dict) else None


def all_sources(response: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        hit["_source"]
        for hit in response.get("hits", {}).get("hits", [])
        if isinstance(hit, dict) and isinstance(hit.get("_source"), dict)
    ]


def account_query() -> dict[str, Any]:
    return {
        "size": 1,
        "sort": [
            {"report_date": {"order": "desc", "missing": "_last"}},
            {"ingested_at": {"order": "desc", "missing": "_last"}},
        ],
        "_source": ["report_date", "currency", "ingested_at", "source_file_name", "source_query_type"],
    }


def position_query(account: dict[str, Any]) -> dict[str, Any]:
    filters: list[dict[str, Any]] = [{"term": {"report_date": account["report_date"]}}]
    for field in ("source_query_type", "source_file_name"):
        if account.get(field):
            filters.append({"term": {field: account[field]}})
    return {
        "size": 10000,
        "query": {"bool": {"filter": filters}},
        "sort": [
            {"position_value": {"order": "desc", "missing": "_last"}},
            {"symbol": {"order": "asc", "missing": "_last"}},
        ],
        "_source": [
            "report_date",
            "currency",
            "asset_class",
            "symbol",
            "description",
            "quantity",
            "mark_price",
            "position_value",
            "average_cost_price",
            "cost_basis_money",
            "percent_of_nav",
            "ingested_at",
            "source_file_name",
            "source_query_type",
        ],
    }


def non_zero(position: dict[str, Any]) -> bool:
    quantity = position.get("quantity")
    market_value = position.get("position_value")
    return (isinstance(quantity, (int, float)) and quantity != 0) or (
        isinstance(market_value, (int, float)) and market_value != 0
    )


def sanitized_holding(position: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": position.get("symbol"),
        "name": position.get("description"),
        "asset_class": position.get("asset_class"),
        "quantity": position.get("quantity"),
        "mark_price": position.get("mark_price"),
        "market_value": position.get("position_value"),
        "average_cost": position.get("average_cost_price"),
        "cost_basis": position.get("cost_basis_money"),
        "portfolio_weight": position.get("percent_of_nav"),
        "currency": position.get("currency"),
    }


def source_fingerprint(source_file_name: Any) -> str | None:
    if not isinstance(source_file_name, str) or not source_file_name:
        return None
    return hashlib.sha256(source_file_name.encode("utf-8")).hexdigest()[:12]


def build_snapshot(client: Any, account_index: str, position_index: str) -> dict[str, Any]:
    account = first_source(client.search(account_index, account_query()))
    base = {
        "contract_version": "ibkr_holdings_input_v1",
        "data_source": {"type": "elasticsearch", "account_index": account_index, "position_index": position_index},
        "selection": {
            "success_status": "not_persisted",
            "rule": "newest account document joined to positions from the same report_date and source import",
            "sort": ["report_date desc", "ingested_at desc"],
        },
    }
    if account is None:
        return {**base, "status": "empty", "reason": "no account snapshots", "snapshot": None, "total_holdings": 0, "holdings": []}
    if not account.get("report_date"):
        return {**base, "status": "incomplete", "reason": "newest account snapshot has no report_date", "snapshot": None, "total_holdings": 0, "holdings": []}

    positions = all_sources(client.search(position_index, position_query(account)))
    positions = [item for item in positions if non_zero(item)]
    positions.sort(key=lambda item: (-abs(float(item.get("position_value") or 0)), str(item.get("symbol") or "")))
    ingested_values = [str(item.get("ingested_at")) for item in [account, *positions] if item.get("ingested_at")]
    snapshot = {
        "imported_at": max(ingested_values) if ingested_values else None,
        "holdings_as_of": str(account["report_date"]),
        "base_currency": account.get("currency"),
        "source_query_type": account.get("source_query_type"),
        "source_file_fingerprint": source_fingerprint(account.get("source_file_name")),
    }
    if not positions:
        return {
            **base,
            "status": "empty",
            "reason": "newest joined snapshot has no non-zero positions",
            "snapshot": snapshot,
            "total_holdings": 0,
            "holdings": [],
        }
    return {
        **base,
        "status": "ready",
        "snapshot": snapshot,
        "total_holdings": len(positions),
        "holdings": [sanitized_holding(item) for item in positions],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root")
    parser.add_argument("--fixture", type=Path, help="Offline test fixture; never use for a real morning report")
    parser.add_argument("--es-url", default=os.getenv("ES_HOST", "http://127.0.0.1:9200"))
    parser.add_argument("--account-index", default=os.getenv("ES_ACCOUNT_INDEX", "ibkr_account_daily_snapshot_v1"))
    parser.add_argument("--position-index", default=os.getenv("ES_POSITION_INDEX", "ibkr_position_daily_snapshot_v1"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        discover_repo_root(args.repo_root)
        client = FixtureElasticsearch(args.fixture) if args.fixture else LocalElasticsearch(args.es_url)
        payload = build_snapshot(client, args.account_index, args.position_index)
    except (SnapshotError, FileNotFoundError, json.JSONDecodeError) as exc:
        payload = {"contract_version": "ibkr_holdings_input_v1", "status": "source_unavailable", "reason": str(exc)}
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["status"] == "ready" else 3


if __name__ == "__main__":
    raise SystemExit(main())
