from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
READER_PATH = Path(
    os.environ.get(
        "GALAXY_IBKR_READER_PATH",
        REPO_ROOT / "skills/galaxy-buffett-daily-stock-analysis/scripts/read_ibkr_snapshot.py",
    )
)
SPEC = importlib.util.spec_from_file_location("galaxy_ibkr_reader", READER_PATH)
assert SPEC and SPEC.loader
reader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reader)


def account(account_id: str = "ACCOUNT_A", **overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "account_id": account_id,
        "report_date": "2026-07-18",
        "currency": "USD",
        "source_query_type": "daily_snapshot",
        "source_file_name": "batch-a.csv",
        "ingested_at": "2026-07-19T12:00:00.000000+00:00",
    }
    document.update(overrides)
    return document


def position(account_id: str = "ACCOUNT_A", **overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "account_id": account_id,
        "report_date": "2026-07-18",
        "source_query_type": "daily_snapshot",
        "source_file_name": "batch-a.csv",
        "ingested_at": "2026-07-19T12:00:00.100000+00:00",
        "currency": "USD",
        "asset_class": "STK",
        "symbol": "AAPL",
        "description": "APPLE INC",
        "quantity": 10.0,
        "position_value": 2000.0,
    }
    document.update(overrides)
    return document


class QueryAwareElasticsearch:
    """Small Elasticsearch fake that applies the query instead of returning canned hits."""

    def __init__(self, accounts: list[dict[str, object]], positions: list[dict[str, object]]) -> None:
        self.accounts = accounts
        self.positions = positions
        self.queries: list[tuple[str, dict[str, object]]] = []

    @staticmethod
    def _filters(body: dict[str, object]) -> list[dict[str, object]]:
        query = body.get("query", {})
        if not isinstance(query, dict):
            return []
        bool_query = query.get("bool", {})
        if not isinstance(bool_query, dict):
            return []
        filters = bool_query.get("filter", [])
        return filters if isinstance(filters, list) else []

    def search(self, index: str, body: dict[str, object]) -> dict[str, object]:
        self.queries.append((index, body))
        documents = self.accounts if "account" in index else self.positions
        matches = list(documents)
        for clause in self._filters(body):
            term = clause.get("term") if isinstance(clause, dict) else None
            if isinstance(term, dict) and len(term) == 1:
                field, expected = next(iter(term.items()))
                matches = [item for item in matches if item.get(field) == expected]

        for sort_spec in reversed(body.get("sort", [])):
            if not isinstance(sort_spec, dict) or len(sort_spec) != 1:
                continue
            field, options = next(iter(sort_spec.items()))
            descending = isinstance(options, dict) and options.get("order") == "desc"
            matches.sort(key=lambda item: str(item.get(field) or ""), reverse=descending)

        total = len(matches)
        size = int(body.get("size", 10))
        source_fields = body.get("_source")
        hits = []
        for document in matches[:size]:
            if isinstance(source_fields, list):
                source = {field: document[field] for field in source_fields if field in document}
            else:
                source = dict(document)
            hits.append({"_source": source})
        return {"hits": {"total": {"value": total, "relation": "eq"}, "hits": hits}}


class Response(io.BytesIO):
    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class ReaderJoinTests(unittest.TestCase):
    def build(
        self,
        accounts: list[dict[str, object]],
        positions: list[dict[str, object]],
        account_id: str | None = None,
    ) -> tuple[dict[str, object], QueryAwareElasticsearch]:
        client = QueryAwareElasticsearch(accounts, positions)
        payload = reader.build_snapshot(client, "account-index", "position-index", account_id)
        return payload, client

    def test_position_query_requires_all_four_exact_join_keys(self) -> None:
        payload, client = self.build([account()], [position()])
        self.assertEqual(payload["status"], "ready")
        filters = client.queries[1][1]["query"]["bool"]["filter"]
        terms = {key: value for item in filters for key, value in item["term"].items()}
        self.assertEqual(
            terms,
            {
                "account_id": "ACCOUNT_A",
                "report_date": "2026-07-18",
                "source_query_type": "daily_snapshot",
                "source_file_name": "batch-a.csv",
            },
        )

    def test_missing_join_key_is_incomplete_and_never_reduces_filters(self) -> None:
        payload, client = self.build([account(source_query_type="")], [position()])
        self.assertEqual(payload["status"], "incomplete")
        self.assertEqual(len(client.queries), 1)

    def test_wrong_account_file_or_query_type_is_incomplete(self) -> None:
        cases = [
            position(account_id="ACCOUNT_B"),
            position(source_file_name="batch-b.csv"),
            position(source_query_type="activity_statement"),
        ]
        for mismatched in cases:
            with self.subTest(mismatched=mismatched):
                payload, _ = self.build([account()], [mismatched])
                self.assertEqual(payload["status"], "incomplete")

    def test_old_positions_cannot_complete_new_account_partial_import(self) -> None:
        old = position(ingested_at="2026-07-18T12:00:00.100000+00:00")
        payload, _ = self.build([account()], [old])
        self.assertEqual(payload["status"], "incomplete")

    def test_multi_account_latest_date_requires_explicit_selector(self) -> None:
        accounts = [account("ACCOUNT_A"), account("ACCOUNT_B")]
        positions = [position("ACCOUNT_A"), position("ACCOUNT_B")]
        payload, _ = self.build(accounts, positions)
        self.assertEqual(payload["status"], "incomplete")

        selected, client = self.build(accounts, positions, "ACCOUNT_B")
        self.assertEqual(selected["status"], "ready")
        account_terms = client.queries[0][1]["query"]["bool"]["filter"]
        self.assertIn({"term": {"account_id": "ACCOUNT_B"}}, account_terms)
        serialized = json.dumps(selected, sort_keys=True)
        self.assertNotIn("ACCOUNT_A", serialized)
        self.assertNotIn("ACCOUNT_B", serialized)

    def test_output_discloses_only_source_identifier_presence(self) -> None:
        payload, _ = self.build([account()], [position()])
        snapshot = payload["snapshot"]
        self.assertEqual(snapshot["source_identifier_present"], True)
        self.assertNotIn("source_file_fingerprint", snapshot)
        self.assertNotIn("batch-a.csv", json.dumps(payload, sort_keys=True))


class ReaderConnectionTests(unittest.TestCase):
    def test_loopback_basic_auth_uses_existing_env_values_without_output(self) -> None:
        expected = "Basic " + base64.b64encode(b"reader-user:reader-pass").decode("ascii")
        captured: dict[str, object] = {}

        def fake_urlopen(request: object, **kwargs: object) -> Response:
            captured["authorization"] = request.get_header("Authorization")
            captured["url"] = request.full_url
            captured["kwargs"] = kwargs
            return Response(b'{"hits":{"total":{"value":0,"relation":"eq"},"hits":[]}}')

        env = {"ES_USERNAME": "reader-user", "ES_PASSWORD": "reader-pass", "ES_VERIFY_CERTS": "false"}
        with patch.dict(reader.os.environ, env, clear=True), patch.object(reader, "urlopen", fake_urlopen):
            reader.local_client("http://127.0.0.1:9200").search("account-index", {"size": 1})

        self.assertEqual(captured["authorization"], expected)
        self.assertTrue(str(captured["url"]).startswith("http://127.0.0.1:9200/"))
        self.assertNotIn("reader-user", str(captured["url"]))

    def test_partial_credentials_are_rejected_without_secret_values(self) -> None:
        with patch.dict(reader.os.environ, {"ES_USERNAME": "reader-user"}, clear=True):
            with self.assertRaisesRegex(reader.SnapshotError, "credentials are incomplete") as raised:
                reader.local_client("http://127.0.0.1:9200")
        self.assertNotIn("reader-user", str(raised.exception))

    def test_verify_certs_parser_is_strict(self) -> None:
        self.assertTrue(reader.parse_bool("true", "ES_VERIFY_CERTS"))
        self.assertFalse(reader.parse_bool("0", "ES_VERIFY_CERTS"))
        with self.assertRaises(reader.SnapshotError):
            reader.parse_bool("sometimes", "ES_VERIFY_CERTS")

    def test_auth_and_tls_options_do_not_relax_loopback_only_rule(self) -> None:
        env = {"ES_USERNAME": "reader-user", "ES_PASSWORD": "reader-pass", "ES_VERIFY_CERTS": "true"}
        with patch.dict(reader.os.environ, env, clear=True):
            local = reader.local_client("https://localhost:9200")
            self.assertIsNotNone(local.context)
            with self.assertRaisesRegex(reader.SnapshotError, "loopback"):
                reader.local_client("https://elasticsearch.example.invalid:9200")


if __name__ == "__main__":
    unittest.main()
