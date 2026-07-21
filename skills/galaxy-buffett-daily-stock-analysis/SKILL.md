---
name: galaxy-buffett-daily-stock-analysis
description: Use when the user asks for a daily US stock morning briefing, major market or technology news, upcoming earnings, or portfolio-specific analysis and recommendations based on the user's IBKR holdings.
---

# Galaxy Buffett 每日美股分析

## 核心原则

只依据 IBKR-Statement 最新成功导入的实际持仓和可追溯英文证据，生成组合级中文晨报。先扫描全部持仓，再选择少量重点；没有新证据时明确维持原计划。

不得调用或要求调用任何其他投资 Skill。可使用正常网页与文件工具取得事实。不得猜测持仓、自动交易、保存券商凭证或承诺收益。

任何被称为“晨报”或 “briefing” 的输出都必须完整遵守 HTML 晨报合同。短晨报、测试场景、输入不完整都不改变格式；环境明确禁止写文件时，返回完整 UTF-8 HTML 代码块并说明未保存，不得改成 Markdown 草案。

## 每次固定读取

开始分析前完整读取以下三份 reference：

1. [新闻证据规则](references/news-evidence.md)
2. [持仓分析规则](references/portfolio-analysis.md)
3. [晨报输出合同](references/morning-report-contract.md)

## 主流程

按以下顺序执行：

1. **验证持仓快照**：定位 IBKR-Statement 最新一次成功导入，记录导入时间、持仓日期、账户币种和数据新鲜度。缺失、失败或过期时停止生成仓位动作，显著披露限制；不得用旧记忆、新闻中的仓位或推测补齐。缺少成功导入时，把题设或用户列出的证券标为“用户提供的临时范围”，正式覆盖标为“未验证”。
2. **扫描全部持仓**：只对成功导入快照中的每个实际持仓执行确定性相关性扫描；记录已扫描数量、总持仓数量、遗漏项及原因。先完成全覆盖，再挑选最多 6 个重点持仓。临时范围不得写入正式 `scanned_holdings / total_holdings`，也不得声称“全持仓覆盖”。
3. **执行新闻证据门槛**：只接受六类白名单来源，规范化域名、去重同源转载、赋予四种验证状态，并在冲突时降级。只有达到可验证门槛的事件才可支持仓位动作。
4. **按条件加载专项 reference**：只读取被观察事实触发的文件：
   - 持仓公司临近财报或刚发布财报：读取 `references/earnings-playbook.md`。
   - 周度宏观复盘或出现异常宏观冲击：读取 `references/macro-risk.md`。
   - 月度复盘或投资逻辑发生变化：读取 `references/long-term-quality.md`。
   - AI、半导体、数据中心、光通信或关键供应链事件命中持仓：读取 `references/tech-supply-chain.md`。
   - 未满足触发条件时不得预加载上述专项文件。
5. **只做一次组合级综合**：统一评估直接、二阶、宏观共同因子、集中度和相关风险。只有持仓财报命中且确需深挖时，才允许再做一次财报专项分析；其他事件不得增加专项分析轮次。
6. **生成 HTML 晨报**：严格采用晨报合同，以中文输出独立、可浏览的本地 HTML，并保留八个固定章节、全部重点持仓字段、可点击英文证据链接、规范域名、验证状态、持仓数据时间、覆盖状态和风险说明。缺值写“未提供 / 未验证 / 不适用”，空章节写“无已验证项目”，不得删节结构。

## 决策门槛

- 重要事件进入仓位建议前，必须达到 `verified_primary_plus_independent` 或 `verified_two_independent`。
- `primary_only_pending` 只可提示等待独立确认；`unverified_single_source` 只可进入观察区。
- 没有候选 URL 或来源时标记 `evidence_gap`。它是证据缺口，不是第五种验证状态，验证状态写“不适用”，且不得进入动作依据。
- 单一来源、匿名爆料、传闻、短时价格波动或泛行业新闻不得独立触发加仓、减仓或清仓。
- 只有“直接”或传导路径清晰的“二阶”事件可进入持仓建议；宏观共同因子进入组合风险，无实质关联只计入扫描覆盖。
- 每项动作必须写明触发条件、反证条件、时间范围和主要风险。集中度再平衡必须明确标为组合风险动作，不得伪装成新闻触发动作。
- 动作用“观察 / 持有 / 条件式加减仓 / 风险控制”表达。没有满足条件的新证据时使用“维持原计划”。所有交易均由用户确认并在 IBKR 自行执行。

## 硬性上限

- 重大市场事件最多 5 条。
- 科技事件最多 4 条。
- 展开重点持仓最多 6 个。
- 超出上限或没有显著变化的项目合并为“无重大变化”，同时保留全持仓覆盖统计。
