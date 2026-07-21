#!/usr/bin/env python3
"""Deterministic checks for the Galaxy Buffett Skill and audit fixtures."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import sys


EXPECTED_SECTIONS = [
    "一分鐘結論",
    "數據與覆蓋",
    "重大市場事件",
    "科技重大事件",
    "重點持倉建議",
    "無重大變化",
    "事件日曆",
    "證據與風險",
]
HOLDING_FIELDS = [
    "數量／市值／權重",
    "影響類別",
    "建議動作",
    "觸發條件",
    "反證條件",
    "時間範圍／主要風險",
    "證據狀態／連結",
    "判斷理由",
]
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class StrictHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        return

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack[-1] != tag:
            expected = self.stack[-1] if self.stack else "none"
            raise AssertionError(f"HTML close mismatch: expected </{expected}>, got </{tag}>")
        self.stack.pop()

    def close_and_assert(self) -> None:
        self.close()
        if self.stack:
            raise AssertionError(f"HTML has unclosed tags: {self.stack}")


def extract_html(fixture: Path) -> str:
    text = fixture.read_text(encoding="utf-8")
    matches = re.findall(r"```html\s*(<!doctype html>.*?</html>)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if len(matches) != 1:
        raise AssertionError(f"expected one complete HTML fence, found {len(matches)}")
    return matches[0]


def section_bodies(html: str) -> dict[str, str]:
    headings = list(re.finditer(r"<h2>\s*(\d+)\.\s*([^<]+?)\s*</h2>", html, flags=re.IGNORECASE))
    numbers = [int(match.group(1)) for match in headings]
    names = [match.group(2).strip() for match in headings]
    if numbers != list(range(1, 9)) or names != EXPECTED_SECTIONS:
        raise AssertionError(f"eight ordered sections required, got {list(zip(numbers, names))}")

    result: dict[str, str] = {}
    for index, match in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(html)
        result[match.group(2).strip()] = html[match.end() : end]
    return result


def validate_report_fixture(fixture: Path) -> dict[str, int]:
    html = extract_html(fixture)
    parser = StrictHTMLParser()
    parser.feed(html)
    parser.close_and_assert()
    if not html.lower().startswith("<!doctype html>") or not html.lower().endswith("</html>"):
        raise AssertionError("HTML must be complete from doctype through closing html tag")

    sections = section_bodies(html)
    counts = {
        "market_events": len(re.findall(r"<article\b", sections["重大市場事件"], flags=re.IGNORECASE)),
        "technology_events": len(re.findall(r"<article\b", sections["科技重大事件"], flags=re.IGNORECASE)),
        "focus_holdings": len(re.findall(r"<article\b", sections["重點持倉建議"], flags=re.IGNORECASE)),
    }
    limits = {"market_events": 5, "technology_events": 4, "focus_holdings": 6}
    for key, limit in limits.items():
        if counts[key] > limit:
            raise AssertionError(f"{key} exceeds {limit}: {counts[key]}")

    coverage = sections["數據與覆蓋"]
    if "正式覆蓋</th><td>未驗證" not in coverage:
        raise AssertionError("formal coverage must be explicitly unverified")
    if "用戶提供的臨時範圍" not in coverage:
        raise AssertionError("temporary user-provided scope must be separate")
    if "evidence_gap" not in html or "驗證狀態：不適用" not in html:
        raise AssertionError("zero-source events must expose evidence_gap and N/A verification")

    holding_cards = re.findall(r"<article\b[^>]*>(.*?)</article>", sections["重點持倉建議"], flags=re.IGNORECASE | re.DOTALL)
    if not holding_cards:
        raise AssertionError("at least one holding card is required")
    for position, card in enumerate(holding_cards, start=1):
        if not re.search(r"<h3>[^<]+</h3>", card, flags=re.IGNORECASE):
            raise AssertionError(f"holding card {position} is missing code/name")
        missing = [field for field in HOLDING_FIELDS if field not in card]
        if missing:
            raise AssertionError(f"holding card {position} missing fields: {missing}")
    return counts


def assert_expected_fixture_result(fixture: Path, expect_valid: bool) -> None:
    try:
        counts = validate_report_fixture(fixture)
    except AssertionError as exc:
        if expect_valid:
            raise
        text = fixture.read_text(encoding="utf-8")
        expected_failures = {
            "complete_html": "<!doctype html>" not in text or "</html>" not in text,
            "eight_sections": not all(f"{index}. {name}" in text for index, name in enumerate(EXPECTED_SECTIONS, 1)),
            "coverage_separation": "共 4/4" in text
            and ("正式覆蓋" not in text or "用戶提供的臨時範圍" not in text),
            "evidence_gap": "evidence_gap" not in text,
            "holding_fields": any(field not in text for field in HOLDING_FIELDS),
        }
        missing_failures = [name for name, failed in expected_failures.items() if not failed]
        if missing_failures:
            raise AssertionError(f"known failed fixture no longer fails: {missing_failures}") from exc
        print(f"EXPECTED_INVALID {fixture.name}: {exc}; failures={','.join(expected_failures)}")
        return
    if not expect_valid:
        raise AssertionError(f"fixture unexpectedly passed: {fixture}")
    print(f"VALID {fixture.name}: {json.dumps(counts, sort_keys=True)}")


def validate_skill_contract(skill_root: Path) -> None:
    skill_text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    expected_description = (
        "description: Use when the user asks for a daily US stock morning briefing or portfolio-specific "
        "analysis of major market, technology, or earnings events based on the user's IBKR holdings."
    )
    required_skill_text = [
        expected_description,
        "references/ibkr-input-contract.md",
        "scripts/read_ibkr_snapshot.py",
    ]
    missing = [item for item in required_skill_text if item not in skill_text]
    if missing:
        raise AssertionError(f"SKILL.md missing fixed input contract items: {missing}")

    news_text = (skill_root / "references" / "news-evidence.md").read_text(encoding="utf-8")
    required_news_text = [
        "时间窗起点优先使用上一份成功生成晨报所记录的新闻截止时间",
        "正常连续交易日回看 36 小时",
        "星期一或 NYSE 休市后的首份晨报可回看最多 96 小时",
        "两次晨报间隔超过 96 小时",
        "候选元数据最多 120 条",
        "去重后事件簇最多 40 个",
        "深读事件簇最多 12 个",
        "每个事件簇最多打开 3 个来源",
        "每个来源最多保留 600 个中文字符或 1,200 个英文字符",
        "达到双源门槛后停止",
        "冲突升级最多额外打开 2 个来源",
        "溢出披露",
    ]
    missing = [item for item in required_news_text if item not in news_text]
    if missing:
        raise AssertionError(f"news token contract missing: {missing}")


def validate_ibkr_reader(repo_root: Path, skill_root: Path) -> None:
    reader = skill_root / "scripts" / "read_ibkr_snapshot.py"
    fixture = repo_root / "tests" / "fixtures" / "galaxy-buffett-forward" / "ibkr-es-responses.json"
    completed = subprocess.run(
        [sys.executable, str(reader), "--repo-root", str(repo_root), "--fixture", str(fixture)],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(f"IBKR fixture integration failed ({completed.returncode}): {completed.stderr.strip()}")
    payload = json.loads(completed.stdout)
    assert payload["status"] == "ready"
    assert payload["snapshot"]["holdings_as_of"] == "2026-04-18"
    assert payload["snapshot"]["document_batch_time"] == "2026-04-19T01:02:03.300000+00:00"
    assert payload["snapshot"]["base_currency"] == "USD"
    assert payload["snapshot"]["source_identifier_present"] is True
    assert payload["selection"]["import_success_persisted"] is False
    assert "success_status" not in payload["selection"]
    assert payload["total_holdings"] == 2
    assert [item["symbol"] for item in payload["holdings"]] == ["MSFT", "AAPL"]
    assert set(payload["holdings"][0]) == {
        "symbol",
        "name",
        "asset_class",
        "quantity",
        "mark_price",
        "market_value",
        "average_cost",
        "cost_basis",
        "portfolio_weight",
        "currency",
    }
    forbidden = [
        "account_id",
        "source_file_name",
        "source_file_fingerprint",
        "flex_token",
        "password",
        "ACCOUNT_A",
    ]
    output_lower = completed.stdout.lower()
    leaked = [item for item in forbidden if item.lower() in output_lower]
    if leaked:
        raise AssertionError(f"IBKR reader leaked forbidden fields: {leaked}")
    print("VALID ibkr-es-responses.json: ready, 2 non-zero holdings, sensitive fields omitted")

    empty_fixture = fixture.with_name("ibkr-es-empty.json")
    empty = subprocess.run(
        [sys.executable, str(reader), "--repo-root", str(repo_root), "--fixture", str(empty_fixture)],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    empty_payload = json.loads(empty.stdout)
    if empty.returncode != 3 or empty_payload.get("status") != "empty" or empty_payload.get("holdings") != []:
        raise AssertionError(f"IBKR empty branch mismatch: exit={empty.returncode}, payload={empty_payload}")

    unavailable = subprocess.run(
        [sys.executable, str(reader), "--repo-root", str(repo_root / "missing"), "--fixture", str(fixture)],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    unavailable_payload = json.loads(unavailable.stdout)
    if unavailable.returncode != 2 or unavailable_payload.get("status") != "source_unavailable":
        raise AssertionError(
            f"IBKR unavailable branch mismatch: exit={unavailable.returncode}, payload={unavailable_payload}"
        )
    print("VALID IBKR empty/source_unavailable branches: exits 3/2")


def command_all(repo_root: Path) -> None:
    skill_root = repo_root / "skills" / "galaxy-buffett-daily-stock-analysis"
    fixture_root = repo_root / "tests" / "fixtures" / "galaxy-buffett-forward"
    assert_expected_fixture_result(fixture_root / "forward_relevance_failed.md", expect_valid=False)
    assert_expected_fixture_result(fixture_root / "forward_relevance_fixed.md", expect_valid=True)
    for name in ("forward_breadth.md", "forward_conflict.md"):
        text = (fixture_root / name).read_text(encoding="utf-8")
        if "## Prompt" not in text or "## Output" not in text:
            raise AssertionError(f"{name} must preserve prompt and output")
    validate_skill_contract(skill_root)
    validate_ibkr_reader(repo_root, skill_root)
    print("ALL GALAXY BUFFETT ARTIFACT ASSERTIONS PASSED")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    report = subparsers.add_parser("report")
    report.add_argument("fixture", type=Path)
    report.add_argument("--expect", choices=("valid", "invalid"), required=True)
    all_checks = subparsers.add_parser("all")
    all_checks.add_argument("repo_root", type=Path)
    skill_checks = subparsers.add_parser("skill")
    skill_checks.add_argument("skill_root", type=Path)
    skill_checks.add_argument("repo_root", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "report":
            assert_expected_fixture_result(args.fixture, expect_valid=args.expect == "valid")
        elif args.command == "all":
            command_all(args.repo_root.resolve())
        else:
            skill_root = args.skill_root.resolve()
            repo_root = args.repo_root.resolve()
            validate_skill_contract(skill_root)
            validate_ibkr_reader(repo_root, skill_root)
            print(f"SKILL ASSERTIONS PASSED: {skill_root}")
    except (AssertionError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"VALIDATION FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
