from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills/galaxy-buffett-daily-stock-analysis"


def read(relative: str) -> str:
    return (SKILL_ROOT / relative).read_text(encoding="utf-8")


class GalaxyBuffettSkillContractTests(unittest.TestCase):
    def test_main_flow_reads_ibkr_plugin_before_news(self) -> None:
        text = read("SKILL.md")
        self.assertIn("Interactive Brokers (IBKR) 插件", text)
        plugin_step = text.index("Interactive Brokers (IBKR) 插件")
        news_step = text.index("执行新闻证据门槛")
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


if __name__ == "__main__":
    unittest.main()
