# Galaxy Buffett Skill Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 创建、验证并安装 `galaxy-buffett-daily-stock-analysis`，用一个低 Token 的专属 Skill 生成基于 IBKR 持仓的每日美股智能晨报。

**Architecture:** 项目内 Skill 是唯一真源；`SKILL.md` 负责主流程和 reference 路由，七个 references 分离新闻核验、持仓分析、财报、宏观、长期质量、科技供应链和 HTML 输出契约。IBKR-Statement 负责本地持仓、缓存、调度和报告保存，全局 Skill 目录只保存验证后的安装副本。

**Tech Stack:** Codex Skill Markdown、`agents/openai.yaml`、Python `init_skill.py` / `quick_validate.py`、Git、基于独立代理的压力测试。

---

### Task 1: 建立无专属 Skill 基线

**Files:**
- Create: `docs/superpowers/specs/2026-07-21-galaxy-buffett-skill-baseline.md`

**Step 1: 运行三个相互独立的无 Skill 场景**

分别测试：25 个持仓和 100 条候选新闻的资源压力；NVDA 财报证据冲突和立即卖出压力；与 AAPL、MSFT、BRK.B、短债 ETF 相关的科技/宏观筛选。

**Step 2: 记录原始回答中的失败模式**

按以下标准审查：是否有固定信息上限；是否明确来源白名单和双源门槛；是否区分直接和二阶影响；是否禁止单一来源触发仓位动作；是否给出数据新鲜度、反证条件和可审计输出。

**Step 3: 保存基线证据**

写入三个场景的表现摘要、可保留能力、缺失纪律和 Skill 必须补齐的规则。预期基线不是“全部错误”，而是缺少稳定、可复现的专属约束。

### Task 2: 初始化 Skill 骨架

**Files:**
- Create: `skills/galaxy-buffett-daily-stock-analysis/SKILL.md`
- Create: `skills/galaxy-buffett-daily-stock-analysis/agents/openai.yaml`
- Create: `skills/galaxy-buffett-daily-stock-analysis/references/`

**Step 1: 确认目标目录不存在**

Run: `test ! -e skills/galaxy-buffett-daily-stock-analysis`

Expected: exit 0。

**Step 2: 使用官方初始化脚本**

Run:

```bash
python3 /Users/galaxyimac/.codex/skills/.system/skill-creator/scripts/init_skill.py \
  galaxy-buffett-daily-stock-analysis \
  --path skills \
  --resources references \
  --interface 'display_name=Galaxy Buffett - Daily Stock Analysis' \
  --interface 'short_description=基于 IBKR 持仓与可信英文新闻的每日美股智能晨报' \
  --interface 'default_prompt=使用 $galaxy-buffett-daily-stock-analysis 生成今天的美股与 IBKR 持仓智能晨报。'
```

Expected: 生成 `SKILL.md`、`agents/openai.yaml` 和空的 `references/`。

### Task 3: 编写主 Skill 与固定 reference

**Files:**
- Modify: `skills/galaxy-buffett-daily-stock-analysis/SKILL.md`
- Create: `skills/galaxy-buffett-daily-stock-analysis/references/news-evidence.md`
- Create: `skills/galaxy-buffett-daily-stock-analysis/references/portfolio-analysis.md`
- Create: `skills/galaxy-buffett-daily-stock-analysis/references/morning-report-contract.md`

**Step 1: 写触发描述**

Frontmatter 只保留 `name` 和 `description`。描述只回答何时使用：每日美股晨报、重大市场或科技新闻、财报日，以及基于用户 IBKR 持仓的影响分析和建议。

**Step 2: 写单入口主流程**

主流程固定为：验证持仓快照 -> 全持仓扫描 -> 新闻证据门槛 -> 条件加载 -> 一次组合级综合 -> HTML 晨报。明确不调用其他投资 Skill，不猜测持仓，不自动交易。

**Step 3: 写三个固定 reference**

- `news-evidence.md`: 六类英文来源、双源状态、冲突处理和中国新闻网站禁用规则。
- `portfolio-analysis.md`: 数据新鲜度、直接/二阶/宏观/无关联分类、组合权重与动作条件。
- `morning-report-contract.md`: 一分钟结论、市场大事、科技、持仓建议、事件日历、证据与风险；包含条数和篇幅上限。

### Task 4: 编写四个条件 reference

**Files:**
- Create: `skills/galaxy-buffett-daily-stock-analysis/references/earnings-playbook.md`
- Create: `skills/galaxy-buffett-daily-stock-analysis/references/macro-risk.md`
- Create: `skills/galaxy-buffett-daily-stock-analysis/references/long-term-quality.md`
- Create: `skills/galaxy-buffett-daily-stock-analysis/references/tech-supply-chain.md`

**Step 1: 财报框架**

比较收入、利润率、现金流、指引、预期差和管理层措辞；区分已发生结果、未来指引和市场预期，最多只对一个财报命中执行额外深挖。

**Step 2: 宏观框架**

按增长、通胀、流动性、政策和利率传导到组合；正常日不加载，周度或异常事件才加载。

**Step 3: 长期质量框架**

只在月度复盘或投资逻辑变化时评估护城河、资本回报、资产负债表、管理层和估值区间。

**Step 4: 科技供应链框架**

建立 AI 算力、半导体、数据中心、光通信和供应链的一阶/二阶传导；泛行业热度不能直接转成持仓动作。

### Task 5: 结构与内容验证

**Files:**
- Verify: `skills/galaxy-buffett-daily-stock-analysis/`

**Step 1: 运行官方校验器**

Run: `scripts/verify_galaxy_buffett_skill.sh`

Expected: 官方 `quick_validate.py` 输出 `Skill is valid!`；`openai.yaml` 独立解析、占位符、结构和 fixture 断言全部通过。

**Step 2: 检查占位符和规模**

验证入口内部显式处理 `rg` 状态：exit 1 代表无匹配，exit >1 代表工具错误并失败；不得用 `|| true` 吞错。同时检查 `SKILL.md` 少于 500 行。

**Step 3: 检查禁止内容与条件加载**

确认中国新闻站点只出现在“禁止作为新闻来源”的规则内；确认主 Skill 不要求调用其他投资 Skill；确认四个专项 reference 都有清晰触发条件。

### Task 6: 前向压力测试

**Files:**
- Modify: `docs/superpowers/specs/2026-07-21-galaxy-buffett-skill-baseline.md`

**Step 1: 用新上下文加载 Skill 重跑三个场景**

要求测试代理明确使用项目内 Skill，并复用 Task 1 的场景。

**Step 2: 对照验收**

三个场景共同验证固定条数上限、双源门槛、数据新鲜度、四类相关性、条件式动作和无重大变化时默认维持计划。逐场景只验收被题设实际触发的规则；未触发项必须记录为“不适用／未展示”，不得冒充已验证。

**Step 3: 记录残余风险**

说明正式晨报仍依赖实时网页可访问性、IBKR 导入完整性和用户风险偏好；Skill 不替代交易决策。

### Task 7: 安装、比对与版本控制

**Files:**
- Install: `/Users/galaxyimac/.codex/skills/galaxy-buffett-daily-stock-analysis/`

**Step 1: 确认没有现有安装需要保护**

Run: `test ! -e /Users/galaxyimac/.codex/skills/galaxy-buffett-daily-stock-analysis`

Expected: exit 0。若已存在则停止覆盖并先比较。

**Step 2: 复制验证后的 Skill**

Run: `cp -R skills/galaxy-buffett-daily-stock-analysis /Users/galaxyimac/.codex/skills/`

**Step 3: 校验安装副本一致**

Run:

```bash
diff -ru \
  skills/galaxy-buffett-daily-stock-analysis \
  /Users/galaxyimac/.codex/skills/galaxy-buffett-daily-stock-analysis
```

Expected: 无输出，exit 0。

**Step 4: 提交并推送**

Run:

```bash
git add docs/superpowers/specs/2026-07-21-galaxy-buffett-skill-design.md \
  docs/superpowers/plans/2026-07-21-galaxy-buffett-skill.md
git commit -m "feat: 创建 Galaxy Buffett 每日持仓分析技能"
git push
```

只暂存本轮实际新增的 design 和 plan 两份文档；baseline 与 Skill 已在前序任务提交，不在此重放暂存，避免误导。

Expected: 提交成功；若 HTTPS 凭证仍不可用，明确报告 push 失败并保留本地提交。

### Task 8: 最终审查 remediation

**Files:**
- Create: `skills/galaxy-buffett-daily-stock-analysis/references/ibkr-input-contract.md`
- Create: `skills/galaxy-buffett-daily-stock-analysis/scripts/read_ibkr_snapshot.py`
- Create: `scripts/validate_galaxy_buffett_artifacts.py`
- Create: `scripts/verify_galaxy_buffett_skill.sh`
- Create: `tests/fixtures/galaxy-buffett-forward/*`
- Modify: `skills/galaxy-buffett-daily-stock-analysis/SKILL.md`
- Modify: `skills/galaxy-buffett-daily-stock-analysis/references/news-evidence.md`
- Modify: `skills/galaxy-buffett-daily-stock-analysis/references/portfolio-analysis.md`
- Modify: design、baseline 与本计划

**Step 1: 证明 fixture red/green**

Run:

```bash
python3 scripts/validate_galaxy_buffett_artifacts.py report \
  tests/fixtures/galaxy-buffett-forward/forward_relevance_failed.md --expect invalid
python3 scripts/validate_galaxy_buffett_artifacts.py report \
  tests/fixtures/galaxy-buffett-forward/forward_relevance_fixed.md --expect valid
```

Expected: failed fixture 被拒绝；fresh fixed fixture 通过八章节、HTML、5/4/6、覆盖、`evidence_gap` 与持仓字段断言。

**Step 2: 验证真实 IBKR 输入合同**

用现有 Flex → transformer → Elasticsearch 字段作为唯一事实来源。schema 没有持久化 import success；禁止新增或猜测成功状态。脚本强制四键精确连接、账户隔离、逐文档后验验证和 transformer 时间顺序证明，只读最新可用且可证明同批的账户／持仓快照，过滤零持仓并隐去账户号、文件名和配置。用 query-aware 脱敏 ES fake 验证缺键、错账户／文件／query type、旧 `ingested_at` partial import、多账户歧义、ready、empty 与 source_unavailable 分支。

**Step 3: 验证新闻输入停止规则**

优先从上一份成功生成晨报的新闻截止时间续接；无记录时正常连续交易日回看 36 小时，星期一或 NYSE 休市后的首份晨报最多 96 小时，超过 96 小时披露未覆盖缺口。保持 120 条元数据、40 个事件簇、12 个深读事件簇、每事件 3 源、每源摘录上限、达标停止、冲突额外 2 源及溢出披露。持仓直接事件与系统性事件先进入元数据扫描，5/4/6 只约束输出。

**Step 4: 运行可复现总验证**

Run: `scripts/verify_galaxy_buffett_skill.sh`

Expected: 临时隔离环境安装 PyYAML 与 worker requirements，官方 quick validate、独立 YAML parse、placeholder、语法、结构／fixture assertions、reader 单测、worker 精确 10 tests 与 `git diff --check` 全部 exit 0；退出时安全清理临时环境。

**Step 5: 精确同步并复验安装副本**

先保存修改前 `diff -ru` exit 0 证据，再只同步到 `/Users/galaxyimac/.codex/skills/galaxy-buffett-daily-stock-analysis`。同步后再次运行 `diff -ru` 与：

```bash
scripts/verify_galaxy_buffett_skill.sh \
  /Users/galaxyimac/.codex/skills/galaxy-buffett-daily-stock-analysis
```

Expected: 安装 diff 与安装副本验证均 exit 0。
