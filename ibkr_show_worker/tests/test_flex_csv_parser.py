from pathlib import Path

from worker.parsers.flex_csv_parser import parse_flex_csv

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "worker" / "fixtures"


def test_parse_flex_csv_extracts_sections_and_metadata() -> None:
    fixture = FIXTURES_DIR / "daily_sample.csv"
    statement = parse_flex_csv(fixture)

    assert statement.metadata.query_name == "Daily Snapshot"
    assert statement.metadata.from_date == "2026-04-17"
    assert statement.metadata.to_date == "2026-04-18"
    assert statement.metadata.account_ids == ["U1234567"]
    assert "POST" in statement.sections
    assert statement.get_section("TRNT") is not None
    assert len(statement.get_section("POST").rows) == 2
    assert statement.record_counts["DATA"] >= 1
