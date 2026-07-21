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

Run:

```bash
python3 /Users/galaxyimac/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  skills/galaxy-buffett-daily-stock-analysis
```

Expected: `Skill is valid!`

**Step 2: 检查占位符和规模**

Run:

```bash
rg -n 'TODO|PLACEHOLDER|example\.com' skills/galaxy-buffett-daily-stock-analysis || true
wc -l skills/galaxy-buffett-daily-stock-analysis/SKILL.md
```

Expected: 无占位符；`SKILL.md` 少于 500 行。

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
