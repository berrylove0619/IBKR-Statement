# Galaxy Buffett IBKR Plugin Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the authorized Interactive Brokers plugin the only formal holdings source for Galaxy Buffett, then scan holdings, collect verified English news, analyze portfolio impact, and generate the Chinese HTML report.

**Architecture:** Keep the skill documentation-driven. Replace the Elasticsearch reader contract with a plugin-only, three-call in-memory snapshot contract: open positions, account financial metrics, and currency balances. Preserve the existing news evidence and report contracts while adapting coverage, freshness, and action gates to `ready / partial / empty / source_unavailable` plugin states.

**Tech Stack:** Markdown skill contracts, Python `unittest` contract tests, Codex Interactive Brokers app connector, skill-creator validation scripts.

## Global Constraints

- Formal IBKR holdings come only from the authorized `Interactive Brokers (IBKR)` plugin.
- Never fall back to Elasticsearch, Flex CSV, local cache, prior reports, memory, or user statements.
- Fixed daily account reads are open positions, account financial metrics, and currency balances, once each per report.
- Do not call trades, live orders, watchlists, performance history, instruction creation, or order submission unless a separate user request explicitly requires a read-only dataset; this skill never uses write tools.
- Additional market data is conditional and limited to the final six expanded holdings.
- Keep the existing six-source English-news whitelist, evidence thresholds, 5/4/6 output caps, eight-section HTML contract, and no-auto-trading rule.
- Preserve `scripts/read_ibkr_snapshot.py` and its existing tests as inactive legacy artifacts; do not call or reference the reader from the active skill flow.
- Keep the project skill and `~/.codex/skills/galaxy-buffett-daily-stock-analysis` byte-equivalent after deployment.

---

### Task 1: Add the failing plugin-only skill contract

**Files:**
- Create: `tests/test_galaxy_buffett_skill_contract.py`
- Read: `skills/galaxy-buffett-daily-stock-analysis/SKILL.md`
- Read: `skills/galaxy-buffett-daily-stock-analysis/references/ibkr-input-contract.md`
- Read: `skills/galaxy-buffett-daily-stock-analysis/references/portfolio-analysis.md`
- Read: `skills/galaxy-buffett-daily-stock-analysis/references/morning-report-contract.md`

**Interfaces:**
- Consumes: UTF-8 Markdown contracts under `skills/galaxy-buffett-daily-stock-analysis`.
- Produces: `GalaxyBuffettSkillContractTests`, a deterministic static contract gate for source priority, call budget, failure handling, report fields, and no-write behavior.

- [ ] **Step 1: Create the failing contract test**

```python
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills/galaxy-buffett-daily-stock-analysis"


def read(relative: str) -> str:
    return (SKILL_ROOT / relative).read_text(encoding="utf-8")


class GalaxyBuffettSkillContractTests(unittest.TestCase):
    def test_main_flow_reads_ibkr_plugin_before_news(self) -> None:
        text = read("SKILL.md")
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
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
python3 -m unittest tests/test_galaxy_buffett_skill_contract.py -v
```

Expected: FAIL because the current skill references `scripts/read_ibkr_snapshot.py`, lacks the three plugin calls, and still requires document batch time.

- [ ] **Step 3: Record the baseline failure without changing the skill**

Run one fresh-context forward scenario against the current skill: “Generate today’s briefing; the IBKR plugin is connected but local Elasticsearch is unavailable.” Expected baseline failure: the agent follows the current local-reader-only contract and refuses to use the connected plugin.

---

### Task 2: Replace the IBKR input contract with plugin-only balanced mode

**Files:**
- Modify: `skills/galaxy-buffett-daily-stock-analysis/references/ibkr-input-contract.md:1-62`
- Test: `tests/test_galaxy_buffett_skill_contract.py`

**Interfaces:**
- Consumes: the connector capabilities “Retrieves all open positions,” “Retrieves account-level financial metrics,” and “Retrieves cash balances and market values broken down by currency.”
- Produces: a report-local normalized snapshot with `status`, `fetched_at`, `holdings`, `account_metrics`, `cash_balances`, `total_holdings`, and missing-component disclosures.

- [ ] **Step 1: Rewrite the input contract around exactly three fixed read-only calls**

The contract must define this ordered recipe:

```markdown
1. 调用 Interactive Brokers (IBKR) 插件的“全部未平仓持仓”工具一次。
2. 持仓调用成功后，调用“账户财务指标”与“分币种余额”工具，每项一次。
3. 在同一次晨报中复用三项结果，不按证券或新闻重复读取账户。
4. 插件是唯一正式持仓来源；不得回退 Elasticsearch，不得读取 Flex CSV、历史晨报、记忆或用户口述补齐正式持仓。
5. 不得创建交易指令、提交订单、修改观察列表或调用其他写工具。
```

Define the exact field mapping from the approved design, including `contract_description → symbol`, `position → quantity`, `market_price → mark_price`, `market_value`, `average_price → average_cost`, `unrealized_pnl`, `daily_pnl`, and `currency`. Set `cost_basis=null` when absent. Calculate `portfolio_weight = market_value / net_liquidation` only when both values are numeric and net liquidation is nonzero.

Define four states:

- `ready`: all three calls succeed;
- `partial`: positions succeed and either supporting account call fails;
- `empty`: positions succeed with an explicit empty array;
- `source_unavailable`: positions fail; no local fallback.

Define `fresh` as a report generated no more than 15 minutes after the last successful fixed plugin call; otherwise `stale`, and use `unknown` when no valid query time exists.

- [ ] **Step 2: Run the focused contract tests**

Run:

```bash
python3 -m unittest tests/test_galaxy_buffett_skill_contract.py -v
```

Expected: input-contract assertions pass; main-flow and report-contract assertions still fail.

- [ ] **Step 3: Commit the isolated input-contract change**

```bash
git add tests/test_galaxy_buffett_skill_contract.py skills/galaxy-buffett-daily-stock-analysis/references/ibkr-input-contract.md
git commit -m "feat: 改用 IBKR 插件读取账户"
git push
```

---

### Task 3: Adapt the main workflow, portfolio rules, and HTML report contract

**Files:**
- Modify: `skills/galaxy-buffett-daily-stock-analysis/SKILL.md:8-56`
- Modify: `skills/galaxy-buffett-daily-stock-analysis/references/portfolio-analysis.md:3-60`
- Modify: `skills/galaxy-buffett-daily-stock-analysis/references/morning-report-contract.md:9-64`
- Test: `tests/test_galaxy_buffett_skill_contract.py`

**Interfaces:**
- Consumes: the normalized plugin states and holdings fields from Task 2.
- Produces: plugin-first execution order, full-holdings news relevance scan, action gates for `ready/partial`, and an eight-section HTML report using plugin query time.

- [ ] **Step 1: Change the main skill execution order**

Replace the local-reader core principle and first two workflow steps with:

```markdown
只依据当前会话中已授权的 Interactive Brokers (IBKR) 插件实际账户数据和可追溯英文证据，生成组合级中文晨报。

1. **读取并验证插件账户快照**：按 IBKR 输入合同固定读取全部未平仓持仓、账户财务指标和分币种余额。插件是唯一正式持仓来源；不调用本地 reader 或任何回退来源。
2. **扫描全部正式持仓**：在插件持仓成功时扫描每个非零持仓，记录覆盖、遗漏和状态；`partial` 只允许观察／持有，`source_unavailable` 停止持仓建议。
3. **执行新闻证据门槛**：完成持仓读取与全持仓枚举后，再扫描英文新闻并执行白名单、去重和交叉验证。
```

Retain the existing conditional references, one portfolio synthesis, HTML output contract, evidence thresholds, and 5/4/6 caps.

- [ ] **Step 2: Adapt portfolio analysis to plugin status and balanced account data**

Require:

- formal coverage when positions succeed in `ready` or `partial`;
- full portfolio-weight, cash, margin, and concentration analysis only in `ready`;
- `partial` recommendations limited to “观察／持有／刷新插件数据后复核,” with explicit text “禁止条件式加仓” and “禁止条件式减仓”;
- `source_unavailable` formal coverage “未验证” and no holding recommendations;
- no inference for missing price, cost, currency, or account fields;
- extra market-data calls only after news relevance ranking and for at most six expanded holdings.

- [ ] **Step 3: Adapt the HTML report data and freshness fields**

Replace document-batch wording with:

```markdown
数据与覆盖显示：数据源 `Interactive Brokers (IBKR) plugin`、插件查询时间、账户数据状态、新鲜度、已扫描／总持仓、缺失组件和报告生成时间。
```

Keep the eight fixed sections and all holding-card fields. Require `partial` and unavailable warnings at the top and retain `fresh / stale / unknown` labels.

- [ ] **Step 4: Run RED-GREEN verification**

Run:

```bash
python3 -m unittest tests/test_galaxy_buffett_skill_contract.py -v
python3 -m unittest tests/test_galaxy_ibkr_reader.py -v
```

Expected: both suites PASS. The legacy reader tests remain green even though the active skill no longer references the reader.

- [ ] **Step 5: Commit the active skill-flow change**

```bash
git add skills/galaxy-buffett-daily-stock-analysis/SKILL.md \
  skills/galaxy-buffett-daily-stock-analysis/references/portfolio-analysis.md \
  skills/galaxy-buffett-daily-stock-analysis/references/morning-report-contract.md
git commit -m "feat: 完成 IBKR 插件优先晨报流程"
git push
```

---

### Task 4: Validate, forward-test, and deploy the installed skill

**Files:**
- Validate: `skills/galaxy-buffett-daily-stock-analysis/`
- Sync: `skills/galaxy-buffett-daily-stock-analysis/` → `/Users/galaxyimac/.codex/skills/galaxy-buffett-daily-stock-analysis/`
- Verify: `skills/galaxy-buffett-daily-stock-analysis/agents/openai.yaml`

**Interfaces:**
- Consumes: the complete project skill from Tasks 2-3.
- Produces: a discoverable installed skill whose files match the project source and whose real run uses only authorized IBKR connector data.

- [ ] **Step 1: Validate skill structure and interface metadata**

Run:

```bash
python3 /Users/galaxyimac/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  skills/galaxy-buffett-daily-stock-analysis
```

Expected: `Skill is valid!`. Confirm `agents/openai.yaml` still describes an IBKR holdings and English-news morning briefing; regenerate only if stale.

- [ ] **Step 2: Run a fresh-context forward test with the revised skill**

Scenario: “Generate today’s Galaxy Buffett briefing. The IBKR plugin is connected; do not use local files for holdings.”

Expected observations:

- the agent calls open positions before news;
- it calls account metrics and currency balances once each;
- it never calls the local snapshot reader;
- it enumerates all nonzero plugin holdings before selecting news;
- it does not call trades, orders, performance, or write tools;
- it preserves the news evidence and HTML contracts.

- [ ] **Step 3: Sync the installed copy without deleting unrelated files**

Run:

```bash
rsync -a skills/galaxy-buffett-daily-stock-analysis/ \
  /Users/galaxyimac/.codex/skills/galaxy-buffett-daily-stock-analysis/
diff -qr skills/galaxy-buffett-daily-stock-analysis \
  /Users/galaxyimac/.codex/skills/galaxy-buffett-daily-stock-analysis
```

Expected: `diff -qr` produces no output.

- [ ] **Step 4: Run the real three-call account-data smoke test**

Use the authorized IBKR plugin once for each fixed read-only capability: open positions, account metrics, and currency balances. Record only success state, field availability, holdings count, and query time in validation output; do not place raw private account data in test fixtures or commits.

Expected: all three calls succeed and the normalized state is `ready`.

- [ ] **Step 5: Run final repository verification**

Run:

```bash
python3 -m unittest tests/test_galaxy_buffett_skill_contract.py tests/test_galaxy_ibkr_reader.py -v
git diff --check
git status --short
```

Expected: tests PASS; no whitespace errors; only known user-owned untracked files plus intentional changes remain.

- [ ] **Step 6: Commit any validation-only adjustments and push immediately**

```bash
git add tests/test_galaxy_buffett_skill_contract.py skills/galaxy-buffett-daily-stock-analysis
git commit -m "test: 验证 IBKR 插件晨报合同"
git push
```

If no validation adjustment was needed, do not create an empty commit. Report any push authentication failure explicitly while preserving the local commits.
