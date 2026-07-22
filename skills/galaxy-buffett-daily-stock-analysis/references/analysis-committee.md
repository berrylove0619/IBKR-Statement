# 八角色投资委员会

## 使用范围

只对持仓分析规则选出的深度持仓执行八角色分析。正常日深度分析 4-5 只，硬上限 5 只；重大事件日硬上限 8 只。其余非零持仓仍生成简版卡片，并通过每日轮换避免长期缺少深度复核。

八个角色是分析职责，不要求启动八个独立 Agent。无论由一个还是多个执行单元完成，都必须遵循“共享证据、独立判断、一次裁决”：共享同一份已分级证据包，各角色按职责形成结构化判断，不展开循环辩论，最后只由主席裁决一次。

## 共享输入

每只深度持仓只接收：

- 具有合格白名单来源并已赋予四种正式状态之一的公共证据、时间、原始链接及尚未解决的冲突；每条证据分配稳定的 `EV-*` 引用；
- IBKR 插件返回的当次持仓事实、账户权重和可用账户指标，分别引用 `ACCT-POSITIONS`、`ACCT-METRICS`、`ACCT-BALANCES`；
- 已验证的直接或二阶传导路径；
- 可追溯的财务、公司 IR、监管、行业、估值或市场预期数据；
- 账户状态、新鲜度、现金、集中度、保证金和财报暴露中的可用字段。

没有合格来源的候选新闻、社交媒体情绪、其他持仓的无关材料和无法追溯的估值数字不得进入共享输入。`primary_only_pending` 中的一手正式材料可写入 `primary_confirmed_facts`，但其媒体解释与投资含义只能进入 `pending_interpretations`；只有两种 verified 状态可写入 `cross_verified_facts` 并支持事件驱动动作。`unverified_single_source` 只可进入观察与未知项。某个角色缺少必要数据时输出“数据不足／未验证”和所需补充项，不得用常识补造结论。每个角色的实质要点必须附 `evidence_refs`：公共事实引用 `EV-*`，账户事实引用 `ACCT-*`；不得把局部证据扩张成对整个裁决的证明。

## 八个角色

### 1. 事实与新闻分析师

界定今天真正发生了什么。分开已确认事实、媒体解读、分析推论、未知项和冲突；标注事件与持仓的直接、二阶、宏观共同因子或无实质关联。

输出：`primary_confirmed_facts`、`cross_verified_facts`、`pending_interpretations`、`event_relevance`、`evidence_status`、`open_questions`、`evidence_refs`。

### 2. 财务与基本面分析师

判断新信息是否改变收入、利润率、现金流、资本开支、资产负债表、管理层指引或长期业务质量。临近或刚发布财报时使用财报专项 reference；没有足够财务更新时明确写“基本面暂无可验证变化”。

输出：`fundamental_change`、`earnings_driver`、`financial_watch_items`、`fundamental_confidence`、`evidence_refs`。

### 3. 行业与竞争分析师

分析客户、供应商、竞争者、监管与关键投入的传导链。二阶影响必须写成“事件 → 中间变量 → 持仓收入、成本、资本开支、估值或风险”，并为关键连接提供证据。

输出：`industry_position`、`competitive_change`、`transmission_chain`、`industry_watch_items`、`evidence_refs`。

### 4. 估值与市场预期分析师

判断市场已计价的假设、可能的预期差和需要验证的估值变量。只使用有来源且口径可解释的数据；无法取得可靠预期、倍数或历史区间时，不给伪精确目标价，改为列出“市场预期差待验证”。

输出：`priced_in_assumptions`、`expectation_gap`、`valuation_watch_items`、`valuation_confidence`、`evidence_refs`。

### 5. Bull Analyst

基于前四个角色已经验证的材料提出最强看多论点，写明成立条件、催化剂、潜在受益变量和最容易被忽略的上行路径。不得引入新的未取证事实。

输出：`bull_case`、`bull_catalysts`、`bull_conditions`、`evidence_refs`。

### 6. Bear Analyst

基于同一材料提出最强看空论点，写明主要下行路径、逻辑失效点、尾部风险和需要优先监测的恶化指标。不得把传闻或短时价格波动升级为基本面事实。

输出：`bear_case`、`bear_triggers`、`thesis_breakers`、`evidence_refs`。

### 7. Portfolio Risk Manager

结合真实权重、集中度、相关性、流动性、财报跳空、现金、保证金、汇率与税务风险，判断单股事件对整个账户的重要性。区分公司事件动作与组合集中度再平衡。

输出：`portfolio_impact`、`concentration_risk`、`scenario_loss_path`、`risk_budget_view`、`evidence_refs`。

### 8. Investment Committee Chair

审阅前七个角色的结论，指出一致意见与关键分歧，判断证据强度是否足以改变原计划。只选择一个允许的建议标签，并给出可观察的触发条件、反证条件、时间范围、未来观察指标和主要风险。

输出：`consensus`、`key_disagreement`、`judgment`、`trigger`、`disconfirm`、`horizon`、`watch_metrics`、`risk`、`rationale`、`evidence_refs`。

## 执行顺序与隔离

1. 先冻结共享证据包；角色执行期间不得为迎合某个观点追加低质量证据。
2. 事实与新闻、财务与基本面、行业与竞争、估值与市场预期四个研究角色分别从共享输入形成判断；前四个研究角色的草稿彼此不可见，直到四份结果都冻结，不以其他研究角色、Bull、Bear 或主席结论为前提。
3. Bull Analyst 与 Bear Analyst 阅读相同研究结果，各自给出最强证据支持型论点，只进行一轮，不互相追加新事实。
4. Portfolio Risk Manager 先独立形成账户风险基线，只读取 IBKR 账户快照和已验证事件影响；冻结风险基线后再读取研究角色及 Bull／Bear 结果并评估增量风险，不得把组合集中度包装成公司基本面变化。
5. Investment Committee Chair 最后裁决一次；公共证据只支持观察时，不得升级为新闻或公司事件驱动的条件式加仓／减仓。若 `ACCT-*` 完整、账户 `ready + fresh` 且风险口径可复核，仍可独立裁决“优先控制组合风险”，并标明“组合风险动作，非当日新闻触发”。

## 深度卡片结构化结果

深度卡片至少保留：

- `primary_confirmed_facts`
- `cross_verified_facts`
- `pending_interpretations`
- `open_questions`
- `fundamental_change`
- `earnings_driver`
- `industry_and_competition`
- `transmission_chain`
- `priced_in_assumptions`
- `expectation_gap`
- `bull_case`
- `bull_catalysts_and_conditions`
- `bear_case`
- `bear_triggers_and_thesis_breakers`
- `portfolio_impact`
- `concentration_scenario_and_risk_budget`
- `consensus`
- `key_disagreement`
- `judgment`
- `trigger`
- `disconfirm`
- `horizon`
- `watch_metrics`
- `risk`
- `evidence_status`
- `impact_class`
- `evidence_links`
- `evidence_refs`
- `rationale`

综合判断只使用：维持原计划、继续持有、谨慎持有、等待确认、暂缓加仓、条件式加仓、条件式减仓、优先控制组合风险。

## 输出与效率规则

- 共享新闻、公司材料和账户快照只建立一次，各角色复用，避免重复搜索。
- 允许分析阶段使用更多 token 换取更完整的专业判断，但不得重复叙述同一事实。
- 最终 HTML 不展示角色对话或思维过程，只展示每个角色的结构化结论、关键分歧和主席裁决。
- 每个角色正常输出 1-3 个高信息密度要点；数据不足时写缺口，不用空泛观点填满版面。
- `watch_metrics` 优先列出 3 个未来可验证指标；确有必要时最多 5 个。
- 账户状态不是 `ready` 或新鲜度不是 `fresh` 时，主席只能输出等待确认、继续持有或刷新插件数据后复核。公共证据未达标时禁止事件驱动动作，但不覆盖满足独立账户门槛的纯组合风险动作。
