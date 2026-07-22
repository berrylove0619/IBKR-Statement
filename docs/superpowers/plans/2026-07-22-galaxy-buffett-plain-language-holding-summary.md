# Galaxy Buffett 持仓大白话总结 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在每个持仓卡片顶部增加 100–200 字大白话总结和明确买入／卖出建议，并把深度投委会分析默认折叠。

**Architecture:** 把新要求写成 HTML 结构合同并由现有 Python 校验器强制执行；本地 Skill、安装目录和公开 GitHub Skill 共享同一合同。当前 V3 个人报告按新合同迁移，但继续作为本地私有文件，不进入公开仓库。

**Tech Stack:** Markdown Skill/reference、Python `unittest` 与正则 HTML 合同校验、独立 HTML/CSS、Git。

## Global Constraints

- 每个正式非零持仓恰好一个 `section.plain-language-summary` 和一个 `p.plain-summary-text`。
- `plain-summary-text` 可见中文正文为 100–200 个字符。
- 总结区固定包含“当前动作”“买入建议”“卖出建议”。
- 深度卡片的八角色内容放入默认关闭的 `details.committee-details`；四字段快速摘要保持展开。
- `partial / stale / unknown` 不得输出条件式加仓、条件式减仓、精确交易规模或价位。
- 个人报告不提交到公开 GitHub；Skill 和公开方法说明必须同步。

---

### Task 1: 以失败测试固定新 HTML 合同

**Files:**
- Modify: `tests/test_galaxy_buffett_skill_contract.py`
- Modify: `scripts/validate_galaxy_buffett_artifacts.py`

**Interfaces:**
- Consumes: `validate_html(html: str) -> dict[str, int]`、`class_blocks`、`visible_text`。
- Produces: 对每张 `holding-card` 的大白话总结、动作字段与深度折叠结构校验。

- [ ] **Step 1: 写入失败测试**

在测试文件加入最小完整 HTML 构造器。构造 10 个 `article.news-item`、一个日历、一个 `holding-card` 和账户面板；卡片先故意不包含 `plain-language-summary`。测试代码：

```python
from scripts.validate_galaxy_buffett_artifacts import validate_html


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


class GalaxyBuffettHtmlSummaryTests(unittest.TestCase):
    def test_validator_rejects_holding_without_plain_language_summary(self) -> None:
        card = " ".join((*PORTFOLIO_FIELDS_FOR_TEST, *DEEP_FIELDS_FOR_TEST))
        with self.assertRaisesRegex(AssertionError, "plain-language-summary"):
            validate_html(minimal_holding_report(card))
```

- [ ] **Step 2: 运行失败测试并确认 RED**

Run: `python3 -m unittest tests.test_galaxy_buffett_skill_contract.GalaxyBuffettHtmlSummaryTests.test_validator_rejects_holding_without_plain_language_summary -v`

Expected: `FAIL`，原因是旧校验器没有抛出 `plain-language-summary` 错误。

- [ ] **Step 3: 实现最小校验**

在 `validate_html` 的持仓循环中加入：

```python
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
if 'data-analysis-depth="deep"' in attrs:
    details = class_blocks(card, "details", "committee-details")
    if len(details) != 1 or re.search(r"\bopen(?:\s|=|$)", details[0][0]):
        raise AssertionError(f"deep holding card {position} must contain one closed committee-details")
```

- [ ] **Step 4: 增加通过与边界测试**

分别覆盖：100 字通过、200 字通过、99 字失败、201 字失败、深度详情带 `open` 失败、简版卡无需 `details`。动作标签与完整字段使用测试常量，避免复制生产报告。

- [ ] **Step 5: 运行测试确认 GREEN**

Run: `python3 -m unittest tests.test_galaxy_buffett_skill_contract -v`

Expected: 全部 `OK`。

---

### Task 2: 更新 Skill、安装目录与公开合同

**Files:**
- Modify: `skills/galaxy-buffett-daily-stock-analysis/SKILL.md`
- Modify: `skills/galaxy-buffett-daily-stock-analysis/references/portfolio-analysis.md`
- Modify: `skills/galaxy-buffett-daily-stock-analysis/references/morning-report-contract.md`
- Modify: `/Users/galaxyimac/.codex/skills/galaxy-buffett-daily-stock-analysis/SKILL.md`
- Modify: `/Users/galaxyimac/.codex/skills/galaxy-buffett-daily-stock-analysis/references/portfolio-analysis.md`
- Modify: `/Users/galaxyimac/.codex/skills/galaxy-buffett-daily-stock-analysis/references/morning-report-contract.md`
- Modify: `github-release/galaxy-buffett-daily-stock-analysis/skill/galaxy-buffett-daily-stock-analysis/SKILL.md`
- Modify: `github-release/galaxy-buffett-daily-stock-analysis/skill/galaxy-buffett-daily-stock-analysis/references/portfolio-analysis.md`
- Modify: `github-release/galaxy-buffett-daily-stock-analysis/skill/galaxy-buffett-daily-stock-analysis/references/morning-report-contract.md`
- Modify: `github-release/galaxy-buffett-daily-stock-analysis/docs/DATA-AND-ANALYSIS.md`
- Modify: `github-release/galaxy-buffett-daily-stock-analysis/README.md`
- Modify: `scripts/validate_galaxy_buffett_artifacts.py`

**Interfaces:**
- Consumes: 现有动作枚举、账户状态门槛和双标签 HTML 合同。
- Produces: 未来每次晨报都必须生成相同的置顶总结结构。

- [ ] **Step 1: 先扩展 Skill 合同测试并确认失败**

在 `test_galaxy_buffett_skill_contract.py` 断言以下固定短语存在：

```python
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
```

Run: `python3 -m unittest tests.test_galaxy_buffett_skill_contract -v`

Expected: `FAIL`，缺少新合同短语。

- [ ] **Step 2: 写入最小正向合同**

在持仓分析规则中规定总结的内容与动作门槛；在晨报合同中规定精确标签、class、长度和阅读顺序；在 SKILL 主流程中规定总结置顶、详细分析默认折叠。使用正向结构配方，不重复已有八角色说明。

- [ ] **Step 3: 同步三份 Skill 和公开说明**

将同一段合同同步到本地仓库、`~/.codex/skills` 和 GitHub 发布包。README 增加用户可见说明；`DATA-AND-ANALYSIS.md` 增加如何阅读与验证大白话结论，以及它如何继承账户和证据门槛。

- [ ] **Step 4: 扩展仓库级静态验证**

在 `validate_skill_contract` 和 `validate_public_package` 的必需短语中加入新结构名称与动作字段，确保公开包不会漏同步。

- [ ] **Step 5: 运行 Skill 验证**

Run: `bash scripts/verify_galaxy_buffett_skill.sh`

Expected: `GALAXY BUFFETT VERIFICATION PASSED`。

---

### Task 3: 迁移 V3 报告并发布 Skill

**Files:**
- Modify: `docs/reports/galaxy-buffett/2026-07-22-galaxy-buffett-morning-brief-v3.html`
- Commit in main repo: Skill、验证器、测试、设计与计划；不 add `docs/reports/`。
- Commit in public repo: `github-release/galaxy-buffett-daily-stock-analysis` 中的 Skill 与说明。

**Interfaces:**
- Consumes: Task 1 的 `validate_html` 新合同和 Task 2 的动作门槛。
- Produces: 可直接打开的新版 V3 HTML，以及已推送的可安装公开 Skill。

- [ ] **Step 1: 先对旧 V3 运行新校验并确认失败**

Run:

```bash
python3 - <<'PY'
from pathlib import Path
from scripts.validate_galaxy_buffett_artifacts import validate_html
p = Path("docs/reports/galaxy-buffett/2026-07-22-galaxy-buffett-morning-brief-v3.html")
validate_html(p.read_text(encoding="utf-8"))
PY
```

Expected: `holding card 1 must contain one plain-language-summary`。

- [ ] **Step 2: 更新样式与七张持仓卡**

加入 `plain-language-summary`、三个动作标签和每只证券独立的 100–200 字总结。MU、GOOG、NVDA、NOK、SPCX、IBKR 的八角色网格放入默认关闭的 `details.committee-details`；DRAM 保持简版。

- [ ] **Step 3: 验证长度、结构和隐私**

Run:

```bash
python3 - <<'PY'
from pathlib import Path
from scripts.validate_galaxy_buffett_artifacts import validate_html
p = Path("docs/reports/galaxy-buffett/2026-07-22-galaxy-buffett-morning-brief-v3.html")
print(validate_html(p.read_text(encoding="utf-8")))
PY
rg -n '/Users/|account_id|contract_id|mcp__codex_apps|password|token=' \
  docs/reports/galaxy-buffett/2026-07-22-galaxy-buffett-morning-brief-v3.html
```

Expected: `{'news_items': 13, 'holding_cards': 7, 'deep_holdings': 6}`；隐私扫描无匹配。

- [ ] **Step 4: 运行完整回归**

Run: `python3 -m unittest tests.test_galaxy_buffett_skill_contract -v && bash scripts/verify_galaxy_buffett_skill.sh`

Expected: 单元测试全部 `OK`，技能验证通过。

- [ ] **Step 5: 提交并推送**

主仓库只提交公开 Skill、测试、验证器和计划文件：

```bash
git add scripts tests skills docs/superpowers/plans/2026-07-22-galaxy-buffett-plain-language-holding-summary.md
git commit -m "feat: 增加持仓大白话建议"
git push origin main
```

公开仓库提交用户说明与可安装 Skill：

```bash
git -C github-release/galaxy-buffett-daily-stock-analysis add README.md docs skill
git -C github-release/galaxy-buffett-daily-stock-analysis commit -m "feat: 增加持仓大白话建议"
git -C github-release/galaxy-buffett-daily-stock-analysis push origin main
```

确认 `docs/reports/galaxy-buffett/` 仍未加入任何公开提交。
