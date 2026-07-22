from pathlib import Path
import unittest

from scripts.validate_galaxy_buffett_artifacts import validate_html


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills/galaxy-buffett-daily-stock-analysis"

PORTFOLIO_FIELDS_FOR_TEST = (
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
DEEP_FIELDS_FOR_TEST = (
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


def read(relative: str) -> str:
    return (SKILL_ROOT / relative).read_text(encoding="utf-8")


def minimal_holding_report(card_body: str, depth: str = "deep") -> str:
    news = "".join(
        f'<article class="news-item"><p class="fact-summary">新闻{i}</p></article>'
        for i in range(10)
    )
    return f'''<!doctype html><html><body>
    <button id="market-tab" data-panel="market-panel" aria-selected="true"></button>
    <button id="portfolio-tab" data-panel="portfolio-panel" aria-selected="false"></button>
    <main id="market-panel" role="tabpanel">{news}
      <section id="month-end-calendar"><h2>月底前重点财报与重大事件</h2><p>★</p></section>
    </main>
    <main id="portfolio-panel" role="tabpanel" hidden data-account-status="ready"
      data-total-holdings="1" data-major-event-day="false">
      Interactive Brokers (IBKR) plugin
      <article class="holding-card" data-analysis-depth="{depth}">{card_body}</article>
    </main>
    <script>setAttribute('aria-selected', 'true')</script></body></html>'''


def holding_card_with_summary(
    summary_length: int,
    *,
    depth: str = "deep",
    include_sell_label: bool = True,
    details_open: bool = False,
) -> str:
    labels = "当前动作 继续持有 买入建议 暂不加仓"
    if include_sell_label:
        labels += " 卖出建议 暂不主动卖出"
    summary = (
        '<section class="plain-language-summary">'
        f"{labels}<p class=\"plain-summary-text\">{'好' * summary_length}</p></section>"
    )
    fields = " ".join(PORTFOLIO_FIELDS_FOR_TEST)
    if depth == "brief":
        return f"{summary} {fields}"
    open_attr = " open" if details_open else ""
    details = (
        f'<details class="committee-details"{open_attr}><summary>展开八角色详细分析与证据</summary>'
        f"{' '.join(DEEP_FIELDS_FOR_TEST)}</details>"
    )
    return f"{summary} {fields} {details}"


class GalaxyBuffettHtmlSummaryTests(unittest.TestCase):
    def test_validator_rejects_holding_without_plain_language_summary(self) -> None:
        card = " ".join((*PORTFOLIO_FIELDS_FOR_TEST, *DEEP_FIELDS_FOR_TEST))
        with self.assertRaisesRegex(AssertionError, "plain-language-summary"):
            validate_html(minimal_holding_report(card))

    def test_validator_rejects_plain_summary_outside_length_bounds(self) -> None:
        for length in (99, 201):
            with self.subTest(length=length):
                card = holding_card_with_summary(length)
                with self.assertRaisesRegex(AssertionError, "100-200"):
                    validate_html(minimal_holding_report(card))

    def test_validator_requires_all_three_action_labels(self) -> None:
        card = holding_card_with_summary(120, include_sell_label=False)
        with self.assertRaisesRegex(AssertionError, "卖出建议"):
            validate_html(minimal_holding_report(card))

    def test_validator_rejects_open_committee_details(self) -> None:
        card = holding_card_with_summary(120, details_open=True)
        with self.assertRaisesRegex(AssertionError, "closed committee-details"):
            validate_html(minimal_holding_report(card))

    def test_validator_accepts_summary_boundaries_and_brief_card(self) -> None:
        for length in (100, 200):
            with self.subTest(length=length):
                card = holding_card_with_summary(length)
                result = validate_html(minimal_holding_report(card))
                self.assertEqual(result["holding_cards"], 1)
        brief = holding_card_with_summary(120, depth="brief")
        result = validate_html(minimal_holding_report(brief, depth="brief"))
        self.assertEqual(result["deep_holdings"], 0)


class GalaxyBuffettSkillContractTests(unittest.TestCase):
    def test_main_flow_reads_ibkr_plugin_before_news(self) -> None:
        text = read("SKILL.md")
        self.assertIn("Interactive Brokers (IBKR) 插件", text)
        plugin_step = text.index("Interactive Brokers (IBKR) 插件")
        news_step = text.index("建立共享新闻池")
        self.assertLess(plugin_step, news_step)
        self.assertNotIn("scripts/read_ibkr_snapshot.py", text)

    def test_input_contract_requires_balanced_three_call_mode(self) -> None:
        text = read("references/ibkr-input-contract.md")
        for phrase in ("全部未平仓持仓", "账户财务指标", "分币种余额", "每项一次"):
            self.assertIn(phrase, text)

    def test_input_contract_forbids_local_fallback_and_writes(self) -> None:
        text = read("references/ibkr-input-contract.md")
        for phrase in (
            "不得回退 Elasticsearch",
            "不得读取 Flex CSV",
            "不得创建交易指令",
            "不得提交订单",
        ):
            self.assertIn(phrase, text)

    def test_plugin_states_and_partial_action_gate_are_documented(self) -> None:
        combined = read("references/ibkr-input-contract.md") + read("references/portfolio-analysis.md")
        for status in ("`ready`", "`partial`", "`empty`", "`source_unavailable`"):
            self.assertIn(status, combined)
        self.assertIn("禁止条件式加仓", combined)
        self.assertIn("禁止条件式减仓", combined)

    def test_report_contract_uses_plugin_query_time(self) -> None:
        text = read("references/morning-report-contract.md")
        self.assertIn("Interactive Brokers (IBKR) plugin", text)
        self.assertIn("插件查询时间", text)
        self.assertNotIn("文档批次时间", text)

    def test_deep_analysis_uses_eight_role_investment_committee(self) -> None:
        committee = read("references/analysis-committee.md")
        for role in (
            "事实与新闻分析师",
            "财务与基本面分析师",
            "行业与竞争分析师",
            "估值与市场预期分析师",
            "Bull Analyst",
            "Bear Analyst",
            "Portfolio Risk Manager",
            "Investment Committee Chair",
        ):
            self.assertIn(role, committee)
        self.assertIn("共享证据、独立判断、一次裁决", committee)

    def test_deep_holding_cards_show_expanded_committee_conclusions(self) -> None:
        report = read("references/morning-report-contract.md")
        for label in (
            "基本面变化",
            "行业与竞争",
            "市场预期差",
            "最强看多理由",
            "最强看空理由",
            "对实际仓位的影响",
            "未来观察指标",
        ):
            self.assertIn(label, report)
        self.assertIn("正常日深度卡片最多 5 张", report)
        self.assertIn("重大事件日硬上限 8 张", report)

    def test_holding_cards_lead_with_plain_language_actions(self) -> None:
        report = read("references/morning-report-contract.md")
        portfolio = read("references/portfolio-analysis.md")
        for phrase in (
            "持仓建议·大白话总结",
            "plain-language-summary",
            "plain-summary-text",
            "100–200",
            "当前动作",
            "买入建议",
            "卖出建议",
            "details.committee-details",
            "默认折叠",
        ):
            self.assertIn(phrase, report + portfolio)

    def test_committee_closes_role_isolation_and_evidence_gaps(self) -> None:
        portfolio = read("references/portfolio-analysis.md")
        committee = read("references/analysis-committee.md")
        report = read("references/morning-report-contract.md")
        self.assertIn("已交叉验证且传导路径清晰的重大二阶事件", portfolio)
        self.assertIn("前四个研究角色的草稿彼此不可见", committee)
        self.assertIn("先独立形成账户风险基线", committee)
        self.assertIn("evidence_refs", committee)
        for label in (
            "影响类别",
            "数据缺口与待确认问题",
            "已计价假设",
            "催化剂与成立条件",
            "尾部风险与逻辑失效点",
            "集中度、情景损失与风险预算",
        ):
            self.assertIn(label, report)

    def test_audit_contract_exposes_source_and_risk_validation(self) -> None:
        ibkr = read("references/ibkr-input-contract.md")
        news = read("references/news-evidence.md")
        portfolio = read("references/portfolio-analysis.md")
        report = read("references/morning-report-contract.md")
        self.assertIn("最早一次固定调用", ibkr)
        self.assertIn("三项调用时间跨度", ibkr)
        self.assertIn("独立采编或额外核实", news)
        self.assertIn("组合风险动作不要求公司新闻达到双源门槛", portfolio)
        for field in (
            "evidence-audit",
            "canonical_domain",
            "underlying_source",
            "published_at",
            "fetched_at",
            "supports",
            "conflicts_with",
        ):
            self.assertIn(field, report)

    def test_account_and_public_evidence_have_distinct_audit_refs(self) -> None:
        ibkr = read("references/ibkr-input-contract.md")
        news = read("references/news-evidence.md")
        committee = read("references/analysis-committee.md")
        report = read("references/morning-report-contract.md")
        for phrase in ("market_value_base", "fx_to_base", "base_currency", "market_value_basis"):
            self.assertIn(phrase, ibkr)
        self.assertIn("同一个最小 claim", news)
        self.assertIn("primary_only_pending", committee)
        self.assertIn("优先控制组合风险", committee)
        for ref in ("ACCT-POSITIONS", "ACCT-METRICS", "ACCT-BALANCES", "evidence_ref"):
            self.assertIn(ref, report + committee)

    def test_ready_and_account_audit_are_reproducible(self) -> None:
        ibkr = read("references/ibkr-input-contract.md")
        portfolio = read("references/portfolio-analysis.md")
        committee = read("references/analysis-committee.md")
        report = read("references/morning-report-contract.md")
        self.assertIn("三项调用成功且动作关键字段完整", ibkr)
        self.assertIn("net_liquidation_base", ibkr + portfolio + report)
        self.assertIn("gross_exposure", portfolio)
        self.assertIn("net_exposure", portfolio)
        self.assertIn("primary_confirmed_facts", committee)
        self.assertIn("cross_verified_facts", committee)
        self.assertIn("脱敏规范化数值", report)


if __name__ == "__main__":
    unittest.main()
