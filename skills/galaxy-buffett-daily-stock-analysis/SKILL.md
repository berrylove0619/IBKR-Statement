---
name: galaxy-buffett-daily-stock-analysis
description: Use when the user asks for a daily US stock morning briefing or portfolio-specific analysis of major market, technology, or earnings events based on the user's IBKR holdings.
---

# Galaxy Buffett 每日美股分析

## 核心原则

只依据当前会话中已授权的 Interactive Brokers (IBKR) 插件实际账户数据和可追溯英文证据，生成组合级中文晨报。先读取并扫描全部正式持仓，再收集新闻并选择少量重点；没有新证据时明确维持原计划。

不得调用或要求调用任何其他投资 Skill。IBKR 插件是账户数据连接器，不属于被禁止的投资 Skill。不得猜测持仓、自动交易、保存券商凭证或承诺收益。

任何被称为“晨报”或 “briefing” 的输出都必须完整遵守 HTML 晨报合同。短晨报、测试场景、输入不完整都不改变格式；环境明确禁止写文件时，返回完整 UTF-8 HTML 代码块并说明未保存，不得改成 Markdown 草案。

## 每次固定读取

开始分析前完整读取以下四份 reference：

1. [IBKR 持仓输入合同](references/ibkr-input-contract.md)
2. [新闻证据规则](references/news-evidence.md)
3. [持仓分析规则](references/portfolio-analysis.md)
4. [晨报输出合同](references/morning-report-contract.md)

## 主流程

按以下顺序执行：

1. **读取并验证插件账户快照**：按 IBKR 输入合同调用 Interactive Brokers (IBKR) 插件。固定读取全部未平仓持仓、账户财务指标和分币种余额，每项一次并在本次晨报复用。插件是唯一正式持仓来源；不得调用本地 reader、Elasticsearch、Flex CSV 或历史记录回退。
2. **扫描全部正式持仓**：持仓调用成功后，枚举并扫描每个非零持仓，记录已扫描数量、总持仓数量、遗漏和 `ready / partial / empty` 状态。先完成正式覆盖，再选择最多 6 个重点持仓；临时范围不得冒充正式覆盖。
3. **执行新闻证据门槛**：完成账户读取和全持仓枚举后，再收集新闻。只接受六类白名单来源，规范化域名、去重同源转载、赋予四种验证状态，并在冲突时降级。只有达到可验证门槛的事件才可支持仓位动作。
4. **按条件补充行情与专项 reference**：只有新闻初筛命中重点持仓且插件持仓行情不足时，才补充最多 6 个重点持仓的市场数据；同时按观察事实加载专项文件：
   - 持仓公司临近财报或刚发布财报：读取 `references/earnings-playbook.md`。
   - 周度宏观复盘或出现异常宏观冲击：读取 `references/macro-risk.md`。
   - 月度复盘或投资逻辑发生变化：读取 `references/long-term-quality.md`。
   - AI、半导体、数据中心、光通信或关键供应链事件命中持仓：读取 `references/tech-supply-chain.md`。
   - 未满足触发条件时不得加载额外行情或上述专项文件。
5. **只做一次组合级综合**：统一评估直接、二阶、宏观共同因子、权重、现金、集中度、杠杆和相关风险。只有持仓财报命中且确需深挖时，才允许再做一次财报专项分析。
6. **生成 HTML 晨报**：严格采用晨报合同，以中文输出独立、可浏览的本地 HTML，并保留八个固定章节、全部重点持仓字段、可点击英文证据链接、插件查询时间、覆盖状态和风险说明。缺值写“未提供 / 未验证 / 不适用”，空章节写“无已验证项目”。

## 账户状态与动作门槛

- `ready`：三项固定插件调用成功；新闻证据同时达标时，可生成完整条件式持仓建议。
- `partial`：持仓成功但账户指标或币种余额不完整；只允许“观察／持有／刷新插件数据后复核”，禁止条件式加仓和条件式减仓。
- `empty`：插件明确返回没有未平仓持仓；仍可报告市场事实，不生成持仓建议。
- `source_unavailable`：持仓插件调用失败；正式覆盖写“未验证”，停止持仓建议且不得回退其他来源。
- `stale` 或 `unknown`：只允许“观察／刷新插件数据后复核”。

## 新闻与投资决策门槛

- 重要事件进入仓位建议前，必须达到 `verified_primary_plus_independent` 或 `verified_two_independent`。
- `primary_only_pending` 只可提示等待独立确认；`unverified_single_source` 只可进入观察区。
- 没有候选 URL 或来源时标记 `evidence_gap`；验证状态写“不适用”，且不得进入动作依据。
- 单一来源、匿名爆料、传闻、短时价格波动或泛行业新闻不得独立触发加仓、减仓或清仓。
- 只有“直接”或传导路径清晰的“二阶”事件可进入持仓建议；宏观共同因子进入组合风险，无实质关联只计入扫描覆盖。
- 每项动作必须写明触发条件、反证条件、时间范围和主要风险。集中度再平衡必须明确标为组合风险动作。
- 动作用“观察 / 持有 / 条件式加减仓 / 风险控制 / 维持原计划”表达。所有交易均由用户确认并在 IBKR 自行执行。
- 不读取成交、活动订单、观察列表或历史收益；不得创建交易指令、提交订单、修改观察列表或调用任何写工具。

## 硬性上限

- 固定账户调用 3 次：持仓、账户指标、分币种余额各一次。
- 重大市场事件最多 5 条。
- 科技事件最多 4 条。
- 展开重点持仓及条件补充行情最多 6 个。
- 超出上限或没有显著变化的项目合并为“无重大变化”。只有插件持仓调用成功时才保留正式覆盖统计；否则正式覆盖必须显示“未验证”。
