# 中文 HTML 晨报合同

## 交付形式

任何“晨报”或 briefing 都生成一个 UTF-8、可独立打开的完整 HTML。正常环境保存本地文件；环境禁止写文件时，返回从 <!doctype html> 到 </html> 的完整代码块并说明未保存。正文使用简体中文；代码、公司名和英文来源保留原文。

页面不依赖外部 JavaScript、CSS、字体或 CDN。所有外部文本先 HTML 转义，证据链接指向原始页面，不链接搜索结果或聚合摘要。

## 单页双标签

页面只使用两个顶层标签：

```html
<nav class="report-tabs" role="tablist" aria-label="晨报视图">
  <button id="market-tab" data-panel="market-panel" aria-controls="market-panel"
    aria-selected="true" role="tab">每日市场</button>
  <button id="portfolio-tab" data-panel="portfolio-panel" aria-controls="portfolio-panel"
    aria-selected="false" role="tab">我的持仓</button>
</nav>
<main id="market-panel" role="tabpanel" aria-labelledby="market-tab"></main>
<main id="portfolio-panel" role="tabpanel" aria-labelledby="portfolio-tab" hidden></main>
```

默认打开每日市场。内联脚本根据 data-panel 切换 hidden，并同步 aria-selected。加入 noscript 样式，使禁用 JavaScript 时两个面板按顺序可读。桌面和移动端都采用单列连续阅读，不使用仪表盘、环形图或速度表。新闻、日历、账户摘要和持仓大白话总结始终展开；只有深度持仓的八角色详细分析允许默认折叠。

## 每日市场

市场面板不得显示个人数量、市值、盈亏、账户净值或仓位动作。持仓信息只允许在月底日历以 ★ 作为视觉标识。

顶部显示：晨报日期、新闻截止时间、新闻条数和预计阅读时间。随后按市场影响力统一排列 10-15 个 article.news-item，目标 12 条，全部默认展开。市场、宏观、财报、公司和科技只作为分类标签，不拆成固定章节或固定名额。

每条 news-item 包含：

- 编号和分类；
- 标题；
- 事件时间或发布时间；
- 一个 p.fact-summary，事实摘要不超过 100 个中文字符；
- 一句“为什么重要”，只解释市场、行业或变量影响；
- 验证状态；
- 2-3 个最有价值的原始来源链接。

事实摘要与分析分开，不能把推测写成已发生事实。同一事件的转载不重复展示。

正常面板不写 data-news-shortfall。若达到证据门槛的重要事件确实不足 10 条，在 market-panel 写 data-news-shortfall="true"，展示实际数量并原样披露：“达到证据门槛的重要事件不足 10 条”。不得添加低质量或虚构内容凑数。

## 月底前重点财报与重大事件

每日市场末尾保留：

```html
<section id="month-end-calendar">
  <h2>月底前重点财报与重大事件</h2>
</section>
```

从晨报日期显示到当月最后一个交易日，按日期分组。只收录大型权重股、市场热门公司、重要科技公司、正式持仓公司和重大宏观事件。显示公司／事件、代码、盘前／盘后或公布时间、日期、时区和日期来源。正式持仓公司显示“★ 当前持仓”；插件不可用时不猜测持仓标记。

## 我的持仓

个人面板首先显示账户情况：

- 数据源固定写 Interactive Brokers (IBKR) plugin；
- 插件查询时间；
- ready / partial / empty / source_unavailable；
- fresh / stale / unknown；
- 净清算值、现金、总持仓市值；
- 当日盈亏、未实现盈亏；
- 可用资金、保证金和杠杆字段；
- 已扫描持仓数 / 非零持仓总数；
- 缺失组件与报告生成时间。

随后显示组合风险文字结论：最大单一持仓、前三大集中度、共同因子、当月财报暴露、现金／保证金缓冲，以及当天最重要的一个组合风险。缺失值写“未提供”或“未验证”，不推算。

ready 或 partial 时，在 portfolio-panel 写 `data-account-status`、`data-total-holdings` 和 `data-major-event-day="true/false"`，并为插件返回的每个正式非零持仓生成一个 article.holding-card，按绝对市值降序。`holding-card` 数量必须等于 `data-total-holdings`；不得只显示重点持仓，也不得把其余持仓合并隐藏。

每张持仓卡在持仓事实后、其他分析前，固定显示：

```html
<section class="plain-language-summary">
  <h4>持仓建议·大白话总结</h4>
  <div>当前动作：...</div>
  <div>买入建议：...</div>
  <div>卖出建议：...</div>
  <p class="plain-summary-text">100–200 个中文字符的通俗总结</p>
</section>
```

每张卡恰好一个 `plain-language-summary` 和一个 `plain-summary-text`。总结说明当前结论、核心原因、主要仓位风险和下一项验证条件；不得在总结区发明正文其他部分没有的事实或动作。动作继续受账户状态、证据状态与影响类别门槛约束。

每张卡片包含以下可见标签：

- 持仓事实；
- 当日关联事件；
- 影响类别；
- 影响路径；
- 组合风险；
- 综合判断；
- 触发条件；
- 反证条件；
- 时间范围；
- 主要风险；
- 证据状态；
- 证据链接；
- 判断理由。

深度卡片使用 data-analysis-depth="deep"，并按以下顺序展示八角色投委会的可见结论：

- 今日确认事实；
- 数据缺口与待确认问题；
- 基本面变化；
- 财务与盈利驱动；
- 行业与竞争；
- 二阶传导链；
- 已计价假设；
- 市场预期差；
- 最强看多理由；
- 催化剂与成立条件；
- 最强看空理由；
- 尾部风险与逻辑失效点；
- 对实际仓位的影响；
- 集中度、情景损失与风险预算；
- 投委会共识；
- 关键分歧；
- 综合判断；
- 触发条件；
- 反证条件；
- 时间范围；
- 未来观察指标；
- 主要风险；
- 证据状态与链接；
- 判断理由。

上述八角色字段放入不带 `open` 属性的 `details.committee-details`，默认折叠；`summary` 文案固定为“展开八角色详细分析与证据”。持仓事实、大白话总结和当日关联事件／影响类别／影响路径／组合风险四字段快速摘要保持展开。

每个角色正常保留 1-3 个高信息密度要点。“未来观察指标”优先展示 3 项可验证指标，确有必要时最多 5 项。每个实质要点就近显示对应 `evidence_ref`：公共证据使用 `EV-*` 并映射到原始来源链接与正式证据状态；账户事实使用 `ACCT-*` 并映射到本次账户审计记录。数据不足的角色必须显示“数据不足／未验证”及所需补充项，不得隐藏字段或用泛化观点填充。

简版卡片使用 data-analysis-depth="brief"，可以省略八角色专项字段，但必须明确“今日无足以改变原计划的新证据”或实际数据缺口。

`data-major-event-day="false"` 时正常日深度卡片最多 5 张；只有确有多项重大直接事件、密集持仓财报或系统性冲击时才写 `true`，此时重大事件日硬上限 8 张。优先覆盖事件驱动持仓，其余名额按权重和上次深度复核时间轮换。

empty 时显示账户当前没有未平仓持仓。source_unavailable 时不根据用户口述或历史报告创建 holding-card；显示正式覆盖未验证并停止持仓建议。partial、stale 或 unknown 的建议只能是观察、继续持有、等待确认或刷新数据后复核。

## 证据与风险

来源链接就近放在新闻或持仓卡片中。页面底部必须包含 `<section id="evidence-audit">` 证据审计区，只列最终报告实际引用的依据。

公共证据记录至少展示 `EV-*`、事件标题、支持的最小事实、发布者、`canonical_domain`、`underlying_source`、原始链接、`published_at`、`fetched_at`、正式验证状态、`supports` 和 `conflicts_with`。

账户依据记录固定使用 `ACCT-POSITIONS`、`ACCT-METRICS`、`ACCT-BALANCES`，展示调用能力、查询时间、状态、可用／缺失字段、组合计算口径，以及本次报告实际使用的脱敏规范化数值。至少包括持仓 symbol／数量／币种／原币市值／`market_value_basis`／`fx_to_base`／`market_value_base`，账户 `base_currency`／`net_liquidation_base`／现金／可用资金／保证金，以及分币种余额与 FX。不得展示账户号码、授权信息或原始插件响应。角色要点中的 `evidence_ref` 必须能定位到对应公共或账户记录。

证据审计区同时展示冲突／更正、账户数据限制和研究声明，不重复堆放未使用候选链接。它是本次报告的可追溯索引，不是网页内容的永久存档；原页面以后可能更新、下线或进入付费墙，报告不得声称保存了完整原文。

底部原样注明：“本报告仅供研究辅助，不构成收益保证或自动交易指令；任何交易由用户确认并在 IBKR 自行执行。”

## 篇幅与阅读预算

- 新闻 10-15 条，约 6-7 分钟；
- 月底日历约 1 分钟；
- 账户与持仓约 4-6 分钟；
- 总目标约 10-14 分钟；
- 允许适度增加分析内容，但角色对话、候选事件列表、思维过程和重复证据不得出现在 HTML。
