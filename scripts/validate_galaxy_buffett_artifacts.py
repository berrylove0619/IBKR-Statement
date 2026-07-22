#!/usr/bin/env python3
"""Deterministic checks for the Galaxy Buffett Skill and audit fixtures."""

from __future__ import annotations

import argparse
import html as html_lib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import sys


TAB_IDS = ("market-tab", "portfolio-tab")
PANEL_IDS = ("market-panel", "portfolio-panel")
PUBLIC_PACKAGE_RELATIVE = Path("github-release/galaxy-buffett-daily-stock-analysis")
PORTFOLIO_FIELDS = (
    "持仓事实",
    "当日关联事件",
    "影响类别",
    "影响路径",
    "组合风险",
    "综合判断",
    "触发条件",
    "反证条件",
    "时间范围",
    "证据链接",
)
DEEP_ONLY_FIELDS = (
    "今日确认事实",
    "数据缺口与待确认问题",
    "基本面变化",
    "财务与盈利驱动",
    "行业与竞争",
    "二阶传导链",
    "已计价假设",
    "市场预期差",
    "最强看多理由",
    "催化剂与成立条件",
    "最强看空理由",
    "尾部风险与逻辑失效点",
    "对实际仓位的影响",
    "集中度、情景损失与风险预算",
    "投委会共识",
    "关键分歧",
    "未来观察指标",
)
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


def element_html(source: str, tag: str, element_id: str) -> tuple[str, str]:
    match = re.search(
        rf'<{tag}\b(?P<attrs>[^>]*\bid=["\']{re.escape(element_id)}["\'][^>]*)>'
        rf'(?P<body>.*?)</{tag}>',
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        raise AssertionError(f"missing {tag}#{element_id}")
    return match.group("attrs"), match.group("body")


def visible_text(fragment: str) -> str:
    without_tags = re.sub(r"<[^>]+>", "", fragment)
    return html_lib.unescape(re.sub(r"\s+", "", without_tags))


def class_blocks(source: str, tag: str, class_name: str) -> list[tuple[str, str]]:
    pattern = (
        rf'<{tag}\b(?P<attrs>[^>]*\bclass=["\'][^"\']*\b{re.escape(class_name)}\b[^"\']*["\'][^>]*)>'
        rf'(?P<body>.*?)</{tag}>'
    )
    return [(m.group("attrs"), m.group("body")) for m in re.finditer(pattern, source, re.IGNORECASE | re.DOTALL)]


def validate_html(html: str) -> dict[str, int]:
    html = html.strip()
    parser = StrictHTMLParser()
    parser.feed(html)
    parser.close_and_assert()
    if not html.lower().startswith("<!doctype html>") or not html.lower().endswith("</html>"):
        raise AssertionError("HTML must be complete from doctype through closing html tag")

    for tab_id in TAB_IDS:
        attrs, _ = element_html(html, "button", tab_id)
        expected_panel = "market-panel" if tab_id == "market-tab" else "portfolio-panel"
        if f'data-panel="{expected_panel}"' not in attrs:
            raise AssertionError(f"{tab_id} must target {expected_panel}")
    market_tab_attrs, _ = element_html(html, "button", "market-tab")
    if 'aria-selected="true"' not in market_tab_attrs:
        raise AssertionError("market-tab must be selected by default")

    market_attrs, market_html = element_html(html, "main", "market-panel")
    portfolio_attrs, portfolio_html = element_html(html, "main", "portfolio-panel")
    if 'role="tabpanel"' not in market_attrs or 'role="tabpanel"' not in portfolio_attrs:
        raise AssertionError("both content panels must use role=tabpanel")
    if "hidden" not in portfolio_attrs:
        raise AssertionError("portfolio-panel must be hidden by default")
    if "setAttribute" not in html or "aria-selected" not in html:
        raise AssertionError("HTML must update accessible tab state")

    news_items = class_blocks(market_html, "article", "news-item")
    news_count = len(news_items)
    if news_count > 15:
        raise AssertionError(f"news_items exceeds 15: {news_count}")
    if news_count < 10:
        if 'data-news-shortfall="true"' not in market_attrs:
            raise AssertionError(f"news_items must be between 10 and 15: {news_count}")
        if "达到证据门槛的重要事件不足 10 条" not in market_html:
            raise AssertionError("news shortfall must be disclosed visibly")
    for position, (_, item_html) in enumerate(news_items, start=1):
        summaries = class_blocks(item_html, "p", "fact-summary")
        if len(summaries) != 1:
            raise AssertionError(f"news item {position} must contain one fact-summary")
        summary_length = len(visible_text(summaries[0][1]))
        if summary_length > 100:
            raise AssertionError(f"news item {position} fact-summary exceeds 100 characters: {summary_length}")

    _, calendar_html = element_html(market_html, "section", "month-end-calendar")
    if "月底前重点财报与重大事件" not in calendar_html:
        raise AssertionError("month-end calendar heading is required")

    if "Interactive Brokers (IBKR) plugin" not in portfolio_html:
        raise AssertionError("portfolio panel must identify the IBKR plugin source")
    if any(term in market_html for term in ("当前数量", "未实现盈亏", "条件式减仓")):
        raise AssertionError("public market panel must not expose personal portfolio facts or actions")

    holding_cards = class_blocks(portfolio_html, "article", "holding-card")
    account_unavailable = "source_unavailable" in portfolio_html
    if not holding_cards and not account_unavailable:
        raise AssertionError("portfolio panel must contain holding cards unless the account source is unavailable")
    account_status = re.search(r'data-account-status="(ready|partial|empty|source_unavailable)"', portfolio_attrs)
    if account_status and account_status.group(1) in {"ready", "partial"}:
        total_match = re.search(r'data-total-holdings="(\d+)"', portfolio_attrs)
        if not total_match:
            raise AssertionError("ready/partial portfolio panel must declare data-total-holdings")
        if int(total_match.group(1)) != len(holding_cards):
            raise AssertionError(
                f"holding card coverage mismatch: declared {total_match.group(1)}, rendered {len(holding_cards)}"
            )
    deep_count = sum('data-analysis-depth="deep"' in attrs for attrs, _ in holding_cards)
    major_event_day = 'data-major-event-day="true"' in portfolio_attrs
    deep_limit = 8 if major_event_day else 5
    if deep_count > deep_limit:
        raise AssertionError(f"deep holding cards exceed {deep_limit}: {deep_count}")
    for position, (attrs, card) in enumerate(holding_cards, start=1):
        if not re.search(r'data-analysis-depth="(?:brief|deep)"', attrs):
            raise AssertionError(f"holding card {position} must declare analysis depth")
        plain_summaries = class_blocks(card, "section", "plain-language-summary")
        if len(plain_summaries) != 1:
            raise AssertionError(f"holding card {position} must contain one plain-language-summary")
        summary_body = plain_summaries[0][1]
        for label in ("当前动作", "买入建议", "卖出建议"):
            if label not in summary_body:
                raise AssertionError(f"holding card {position} plain summary missing {label}")
        summary_texts = class_blocks(summary_body, "p", "plain-summary-text")
        if len(summary_texts) != 1:
            raise AssertionError(f"holding card {position} must contain one plain-summary-text")
        summary_length = len(visible_text(summary_texts[0][1]))
        if not 100 <= summary_length <= 200:
            raise AssertionError(
                f"holding card {position} plain-summary-text must be 100-200 characters: {summary_length}"
            )
        missing = [field for field in PORTFOLIO_FIELDS if field not in card]
        if missing:
            raise AssertionError(f"holding card {position} missing fields: {missing}")
        if 'data-analysis-depth="brief"' not in attrs:
            committee_details = class_blocks(card, "details", "committee-details")
            if len(committee_details) != 1 or re.search(
                r"\bopen(?:\s|=|$)", committee_details[0][0], flags=re.IGNORECASE
            ):
                raise AssertionError(f"deep holding card {position} must contain one closed committee-details")
            missing_deep = [field for field in DEEP_ONLY_FIELDS if field not in card]
            if missing_deep:
                raise AssertionError(f"deep holding card {position} missing fields: {missing_deep}")

    if not account_unavailable and "★" not in calendar_html:
        raise AssertionError("calendar must mark at least one current holding with ★")
    return {"news_items": news_count, "holding_cards": len(holding_cards), "deep_holdings": deep_count}


def validate_report_fixture(fixture: Path) -> dict[str, int]:
    html = extract_html(fixture)
    return validate_html(html)


def assert_expected_fixture_result(fixture: Path, expect_valid: bool) -> None:
    try:
        counts = validate_report_fixture(fixture)
    except AssertionError as exc:
        if expect_valid:
            raise
        text = fixture.read_text(encoding="utf-8")
        expected_failures = []
        if "<!doctype html>" not in text or "</html>" not in text:
            expected_failures.append("complete_html")
        if not all(f'id="{tab_id}"' in text for tab_id in TAB_IDS):
            expected_failures.append("two_tabs")
        if not re.search(r'<article\b[^>]*class="[^"]*news-item', text, flags=re.IGNORECASE):
            expected_failures.append("news_contract")
        if "共 4/4" in text and "正式覆盖" not in text:
            expected_failures.append("coverage_separation")
        if not expected_failures:
            raise AssertionError("known failed fixture no longer has a V2 failure marker") from exc
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
        "references/analysis-committee.md",
        "Interactive Brokers (IBKR) 插件",
        "10-15",
        "每日市场",
        "我的持仓",
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
        "深读事件簇最多 15 个",
        "每个事件簇最多打开 3 个来源",
        "每个来源最多保留 600 个中文字符或 1,200 个英文字符",
        "达到双源门槛后停止",
        "冲突升级最多额外打开 2 个来源",
        "溢出披露",
        "正常晨报显示 10-15 条新闻，目标 12 条",
        "每天正常使用 3-6 个英文专业来源域名",
    ]
    missing = [item for item in required_news_text if item not in news_text]
    if missing:
        raise AssertionError(f"news token contract missing: {missing}")

    portfolio_text = (skill_root / "references" / "portfolio-analysis.md").read_text(encoding="utf-8")
    committee_text = (skill_root / "references" / "analysis-committee.md").read_text(encoding="utf-8")
    report_text = (skill_root / "references" / "morning-report-contract.md").read_text(encoding="utf-8")
    required_v3_text = {
        "portfolio-analysis.md": ["正常日选择 4-5 个深度分析持仓", "重大事件日才可增加到 8 个", "每个非零持仓都输出独立卡片"],
        "analysis-committee.md": [
            "共享证据、独立判断、一次裁决",
            "事实与新闻分析师",
            "财务与基本面分析师",
            "行业与竞争分析师",
            "估值与市场预期分析师",
            "Bull Analyst",
            "Bear Analyst",
            "Portfolio Risk Manager",
            "Investment Committee Chair",
        ],
        "morning-report-contract.md": [
            "market-tab",
            "portfolio-tab",
            "article.news-item",
            "article.holding-card",
            "data-news-shortfall",
            "正常日深度卡片最多 5 张",
            "重大事件日硬上限 8 张",
            "持仓建议·大白话总结",
            "plain-language-summary",
            "plain-summary-text",
            "100–200",
            "当前动作",
            "买入建议",
            "卖出建议",
            "details.committee-details",
            "默认折叠",
            *DEEP_ONLY_FIELDS,
        ],
    }
    bodies = {
        "portfolio-analysis.md": portfolio_text,
        "analysis-committee.md": committee_text,
        "morning-report-contract.md": report_text,
    }
    missing_v3 = [
        f"{name}:{item}"
        for name, items in required_v3_text.items()
        for item in items
        if item not in bodies[name]
    ]
    if missing_v3:
        raise AssertionError(f"V3 contract missing: {missing_v3}")

    active_text = "\n".join((skill_text, news_text, portfolio_text, committee_text, report_text))
    forbidden_active = [
        "scripts/read_ibkr_snapshot.py",
        "八个固定章节",
        "重大市场事件最多 5 条",
        "科技事件最多 4 条",
        "重点持仓最多 6 个",
        "最多展开 6 个重点持仓",
    ]
    found = [item for item in forbidden_active if item in active_text]
    if found:
        raise AssertionError(f"obsolete active contract found: {found}")


def validate_public_package(repo_root: Path) -> None:
    package_root = repo_root / PUBLIC_PACKAGE_RELATIVE
    readme = package_root / "README.md"
    methodology = package_root / "docs" / "DATA-AND-ANALYSIS.md"
    security = package_root / "SECURITY.md"
    public_skill = package_root / "skill" / "galaxy-buffett-daily-stock-analysis"
    required_files = [
        readme,
        methodology,
        security,
        package_root / ".gitignore",
        public_skill / "SKILL.md",
        public_skill / "agents" / "openai.yaml",
    ]
    missing_files = [str(path.relative_to(repo_root)) for path in required_files if not path.is_file()]
    if missing_files:
        raise AssertionError(f"public GitHub package missing files: {missing_files}")

    readme_text = readme.read_text(encoding="utf-8")
    methodology_text = methodology.read_text(encoding="utf-8")
    security_text = security.read_text(encoding="utf-8")
    required_readme = [
        "# Galaxy Buffett - Daily Stock Analysis",
        "Interactive Brokers (IBKR) plugin",
        "安装",
        "使用方法",
        "一个 HTML、两个标签",
        "不自动交易",
        "不使用中国新闻网站",
        "数据与分析方法",
        "八角色如何分工",
        "如何验证一条投资结论",
        "共享证据、独立判断、一次裁决",
        "100–200 字大白话总结",
        "买入建议",
        "卖出建议",
        "10-14 分钟",
    ]
    missing_readme = [item for item in required_readme if item not in readme_text]
    if missing_readme:
        raise AssertionError(f"public README missing content: {missing_readme}")

    required_methodology = [
        "全部未平仓持仓",
        "账户财务指标",
        "分币种余额",
        "120",
        "40",
        "15",
        "10-15",
        "3-6",
        "SEC EDGAR",
        "Federal Reserve",
        "Reuters",
        "verified_primary_plus_independent",
        "verified_two_independent",
        "primary_only_pending",
        "unverified_single_source",
        "事实与新闻分析师",
        "财务与基本面分析师",
        "行业与竞争分析师",
        "估值与市场预期分析师",
        "Bull Analyst",
        "Bear Analyst",
        "Portfolio Risk Manager",
        "Investment Committee Chair",
        "角色与数据依据矩阵",
        "逐结论验证流程",
        "用户如何审计一条结论",
        "数据来源与用途边界",
        "canonical_domain",
        "underlying_source",
        "evidence_id",
        "独立性判定",
        "数字与日期核对",
        "缺失数据不推算",
        "独立采编或额外核实",
        "最早一次固定调用",
        "毛敞口",
        "净敞口",
        "组合风险动作",
        "证据审计区",
        "EV-01",
        "不可视为永久存档",
        "Token",
        "partial",
        "source_unavailable",
        "plain-language-summary",
        "plain-summary-text",
        "details.committee-details",
        "暂不主动卖出",
    ]
    missing_methodology = [item for item in required_methodology if item not in methodology_text]
    if missing_methodology:
        raise AssertionError(f"public methodology missing content: {missing_methodology}")

    required_security = ["账户号码", "授权信息", "原始插件响应", ".env", "只读"]
    missing_security = [item for item in required_security if item not in security_text]
    if missing_security:
        raise AssertionError(f"public security guide missing content: {missing_security}")

    forbidden_paths = [
        public_skill / "scripts" / "read_ibkr_snapshot.py",
        public_skill / "scripts" / "__pycache__",
    ]
    found_forbidden_paths = [str(path.relative_to(repo_root)) for path in forbidden_paths if path.exists()]
    found_forbidden_paths.extend(str(path.relative_to(repo_root)) for path in public_skill.rglob("*.pyc"))
    if found_forbidden_paths:
        raise AssertionError(f"public package contains private/obsolete artifacts: {found_forbidden_paths}")

    combined_public = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in package_root.rglob("*")
        if path.is_file()
    )
    forbidden_content = [
        "142,768.92",
        "127,118.11",
        "mcp__codex_apps__interactive_brokers",
        "contract_id 870556708",
        "contract_id 890493863",
    ]
    found_sensitive = [item for item in forbidden_content if item in combined_public]
    if found_sensitive:
        raise AssertionError(f"public package contains account-specific content: {found_sensitive}")

    source_skill = repo_root / "skills" / "galaxy-buffett-daily-stock-analysis"
    comparable_paths = [Path("SKILL.md"), Path("agents/openai.yaml")]
    comparable_paths.extend(
        path.relative_to(source_skill)
        for path in sorted((source_skill / "references").glob("*.md"))
    )
    drifted = [
        str(path)
        for path in comparable_paths
        if not (public_skill / path).is_file()
        or (source_skill / path).read_bytes() != (public_skill / path).read_bytes()
    ]
    if drifted:
        raise AssertionError(f"public skill copy is missing or stale: {drifted}")
    print(f"VALID public GitHub package: {package_root}")


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
    assert_expected_fixture_result(fixture_root / "v2_baseline_failed.md", expect_valid=False)
    assert_expected_fixture_result(fixture_root / "forward_relevance_fixed.md", expect_valid=True)
    assert_expected_fixture_result(fixture_root / "v2_forward_green.md", expect_valid=True)
    for name in ("forward_breadth.md", "forward_conflict.md"):
        text = (fixture_root / name).read_text(encoding="utf-8")
        if "## Prompt" not in text or "## Output" not in text:
            raise AssertionError(f"{name} must preserve prompt and output")
    validate_skill_contract(skill_root)
    validate_public_package(repo_root)
    print("ALL GALAXY BUFFETT ARTIFACT ASSERTIONS PASSED")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    report = subparsers.add_parser("report")
    report.add_argument("fixture", type=Path)
    report.add_argument("--expect", choices=("valid", "invalid"), required=True)
    html_report = subparsers.add_parser("html")
    html_report.add_argument("path", type=Path)
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
        elif args.command == "html":
            counts = validate_html(args.path.read_text(encoding="utf-8"))
            print(f"VALID HTML {args.path}: {json.dumps(counts, sort_keys=True)}")
        elif args.command == "all":
            command_all(args.repo_root.resolve())
        else:
            skill_root = args.skill_root.resolve()
            validate_skill_contract(skill_root)
            print(f"SKILL ASSERTIONS PASSED: {skill_root}")
    except (AssertionError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"VALIDATION FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
