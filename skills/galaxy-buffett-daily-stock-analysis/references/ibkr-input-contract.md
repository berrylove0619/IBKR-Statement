# IBKR 持仓输入合同

## 唯一正式来源

只使用当前会话中已授权的 `Interactive Brokers (IBKR)` 插件取得正式账户数据。按工具能力与说明选择接口，不依赖可能变化的内部哈希工具名。

不得回退 Elasticsearch。不得读取 Flex CSV、本地缓存、历史晨报、记忆或用户口述来补齐正式持仓。用户列出的证券只能作为“用户提供的临时范围”，必须与插件正式持仓分开。

## 平衡模式固定调用

每次晨报按以下顺序执行：

1. 调用插件的“全部未平仓持仓”只读工具一次。
2. 持仓调用成功后，调用“账户财务指标”和“分币种余额”只读工具，每项一次。
3. 在同一次晨报中复用三项结果，不按证券、新闻或章节重复读取账户。
4. 只有新闻初筛命中重点持仓且现有返回值不足以判断影响时，才条件调用额外市场数据；最多覆盖最终展开的 6 个重点持仓。

不读取成交、活动订单、观察列表或历史收益，除非用户在当次任务明确要求对应的只读数据。不得创建交易指令、不得提交订单、不得修改观察列表，也不得调用插件中的其他写工具。

只对明确的临时网络或服务错误重试一次。认证、权限或账户选择错误直接进入降级分支，不重复消耗调用。

## 三项工具能力

| 调用 | 必要返回 |
|---|---|
| 全部未平仓持仓 | 合约描述与标识、资产类型、数量、价格、市值、平均成本、当日盈亏、未实现盈亏、币种 |
| 账户财务指标 | 净清算值、现金、可用资金、购买力、初始保证金、维持保证金、总持仓市值、杠杆 |
| 分币种余额 | 各币种现金、已结算现金、股票市值、净清算值、汇率、已实现与未实现盈亏 |

插件调用结果只在本次报告内存中合并。不得把原始工具响应、账户号码、授权信息或内部会话写入晨报、测试夹具、日志或 Git。

## 规范化字段

| 规范字段 | 插件字段与规则 |
|---|---|
| `symbol` | `contract_description`；缺失或歧义时写“未提供”，必要时条件调用合约搜索核实 |
| `contract_id` | `contract_id`；仅用于同次运行内精确识别证券 |
| `asset_class` | `asset_class` |
| `quantity` | `position` |
| `mark_price` | `market_price` |
| `market_value` | 插件原始 `market_value`，保留数值但在币种口径未确认前不得用于组合百分比 |
| `market_value_basis` | 插件明确标示为持仓原币时写 `native`，明确标示为账户基准币时写 `base`，否则写 `unknown`；不得猜测 |
| `market_value_native` | 仅在 `market_value_basis=native` 时使用原始市值；否则保留 `null` |
| `base_currency` | 账户财务指标或分币种余额明确返回的账户基准币种 |
| `net_liquidation_base` | 账户财务指标明确返回的基准币种净清算值；币种口径不明时为 `null` |
| `fx_to_base` | 插件分币种余额返回、方向明确的“1 单位持仓币种折合多少基准币种”；基准币种自身为 1 |
| `market_value_base` | 插件明确给出基准币市值时直接使用；否则仅在 `market_value_native` 与 `fx_to_base` 均有效时相乘；其余为 `null` |
| `average_cost` | `average_price` |
| `cost_basis` | 插件未直接返回时保留 `null`，不得以数量乘均价推算 |
| `unrealized_pnl` | `unrealized_pnl` |
| `daily_pnl` | `daily_pnl` |
| `currency` | `currency` |
| `portfolio_weight` | `market_value_base / net_liquidation_base`；两者为有效数值且净清算值非零时才计算 |
| `fetched_at` | 三项固定调用各自的完成时间；报告同时保留最早与最晚时间，不展示内部会话信息 |

只保留 `quantity != 0` 或 `market_value != 0` 的持仓。能够得到 `market_value_base` 时按其绝对值降序，否则把币种口径未验证的记录单列，不跨币种直接排序。插件缺失的价格、成本、币种、汇率或盈亏保留 `null`，不得使用网页汇率或常识补算。

三项账户调用在本次报告内分配固定审计引用：`ACCT-POSITIONS`、`ACCT-METRICS`、`ACCT-BALANCES`。它们记录调用能力、查询时间、状态、可用／缺失字段、计算口径和本次报告实际使用的脱敏规范化数值：

- `ACCT-POSITIONS`：每个持仓的 symbol、asset_class、quantity、currency、mark_price、market_value_basis、market_value_native、fx_to_base、market_value_base、average_cost、daily_pnl、unrealized_pnl；
- `ACCT-METRICS`：base_currency、net_liquidation_base、cash、available_funds、buying_power、initial_margin、maintenance_margin、excess_liquidity、leverage；
- `ACCT-BALANCES`：每个币种的 currency、cash、settled_cash、stock_market_value、net_liquidation、fx_to_base 及其查询时间。

不得记录账户号码、原始响应、授权信息或内部会话字段。账户审计记录只存在于用户本地 HTML，不进入 Git、公共测试夹具或公开仓库。

## 状态分支

- `ready`：三项调用成功且动作关键字段完整。至少包括全部持仓身份／数量／币种、`market_value_basis`、所有非基准币持仓的 `fx_to_base`、`market_value_base`、`base_currency`、`net_liquidation_base`、现金、可用资金、初始与维持保证金；不得存在足以改变权重或风险结论的未解决口径冲突。允许完整计算组合权重、现金比例、集中度、毛／净敞口和保证金风险。
- `partial`：持仓成功，但其余任一固定调用失败，或上述动作关键字段／币种口径／重要对账不完整。持仓可正式扫描；缺失字段写“未验证”，禁止仓位百分比、集中度再平衡和条件式加减仓。
- `empty`：持仓调用成功并明确返回空数组。显示账户当前没有未平仓持仓，不把它当作故障，也不回退其他来源。
- `source_unavailable`：持仓调用因授权、权限、服务或网络问题失败。正式覆盖显示“未验证”，停止持仓建议，不尝试本地数据回退。

## 新鲜度

记录插件查询时间，不将它描述成券商估值时间。三项固定调用成功、报告在最早一次固定调用后 15 分钟内生成，且三项调用时间跨度不超过 5 分钟时标记 `fresh`。任一条件超限标记 `stale`；没有全部有效查询时间时标记 `unknown`。报告显示三项查询时间范围，避免最后一次调用掩盖最早持仓数据已经过时。

`stale` 或 `unknown` 只可输出“观察／刷新插件数据后复核”。报告必须披露失败的调用、查询时间和新鲜度，但不得展示底层认证信息或完整错误响应。
