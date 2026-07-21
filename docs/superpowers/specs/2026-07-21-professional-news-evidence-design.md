# 每日持仓复盘专业新闻证据层设计方案

> 主要阅读版本：打开 [每日美股与 IBKR 持仓智能晨报任务 HTML](./2026-07-21-daily-investment-intelligence-task.html)。本文件保留新闻证据层的技术细节。

## 目标

将每日持仓复盘中未经来源验证的新闻输入，替换为只接受专业英文来源的新闻证据层。系统必须排除中国新闻网站，对可能影响持仓的重大事件进行交叉验证，并阻止单一来源新闻直接驱动加仓、减仓或清仓建议。

## 产品边界

- IBKR Flex 和 Elasticsearch 仍是账户、持仓、成本及盈亏事实的唯一来源。
- LongBridge 继续用于公开行情、K 线、估值字段及新闻线索发现。
- 新闻的真实来源以文章或申报文件的最终域名为准，不能把 LongBridge 或其他聚合平台当作新闻发布者。
- 不增加登录系统、后台管理页面、新 Agent 平台、自动交易功能或新的外部付费 API。
- 本阶段不修改现有每日复盘的公开响应结构。
- 每次每日复盘继续最多分析六个重点持仓。

## 备选方案

### 方案一：后端专业新闻证据适配层——采用

在现有 FastAPI 后端增加一个小型同步服务。该服务负责读取 SEC EDGAR 和官方 RSS，将 LongBridge 找到的新闻链接作为线索输入，执行英文来源白名单检查，以保守方式合并同一事件，并在新闻进入 LLM 之前确定验证状态。

优点是数据保存在本地、规则可重复验证、不需要新增凭据，并且可以直接复用现有每日持仓复盘。局限是 Reuters 和公司 Investor Relations 的覆盖取决于 LongBridge 是否发现合格链接；如果当天没有相应来源，系统必须明确报告来源缺失，不能用其他低质量来源替代。

### 方案二：Codex 定时网页研究任务

每天通过域名限定的网页搜索收集新闻，再生成一份独立报告。该方案能够提高 Reuters 和公司 IR 的发现率，但结果会脱离当前每日复盘的数据仓库，也不利于确定性重放和审计。

### 方案三：商业专业新闻 API

接入 Reuters Connect、Bloomberg、Dow Jones Newswires 或其他授权新闻源。这种方式覆盖最完整、元数据质量最好，但会增加成本、凭据、授权条款和运维复杂度，不适合当前聚焦本地使用的试运行版本。

## 可信来源规则

新闻白名单包含六类来源：

1. `sec.gov`：一手证据，包括 SEC EDGAR 申报文件和发行人元数据。
2. 从 SEC submissions 元数据确定的公司官方 Investor Relations 域名：一手证据。
3. `reuters.com`：独立专业公司、行业、监管和宏观新闻。
4. `cnbc.com`：独立美股、财报、盘前盘后和宏观报道。
5. `marketwatch.com` 及其 Dow Jones 官方 RSS 域名：独立市场报道。
6. `nasdaq.com`：仅当 RSS 的 publisher 元数据确认原作者是 Nasdaq 时才可以计作 Nasdaq 证据。合作伙伴转载内容不能当作 Nasdaq 的独立确认。

新浪、腾讯、东财、Yahoo、Google 和 Bing 不能出现在 `canonical_domains` 中，也不能计入验证来源数量。这些服务可以继续用于与新闻分离的行情、K 线、基本面或线索发现。即使 Reuters 文章是通过 LongBridge 或 Yahoo 找到的，也只能算作一个 `reuters.com` 来源。

## 内部数据结构

新服务返回内部字典，并写入 `symbol_public_context` 和 `professional_news_context`，但本阶段不把这些字段加入公开 API 结构。

每条候选新闻包含：

```json
{
  "title": "Issuer announces material event",
  "summary": "Short source-provided summary",
  "url": "https://canonical.example/article",
  "canonical_domain": "reuters.com",
  "publisher": "Reuters",
  "published_at": "2026-07-21T09:00:00Z",
  "source_type": "independent",
  "symbol": "AAPL.US",
  "transport": "longbridge_discovery"
}
```

合并后的事件包含：

```json
{
  "event_id": "sha256-stable-prefix",
  "symbol": "AAPL.US",
  "claim": "Conservative normalized event title",
  "event_type": "filing_or_news",
  "published_at": "2026-07-21T09:00:00Z",
  "canonical_urls": ["https://..."],
  "canonical_domains": ["sec.gov", "reuters.com"],
  "source_count": 2,
  "verification_status": "verified_primary_plus_independent",
  "conflicts": []
}
```

允许的验证状态：

- `verified_primary_plus_independent`：SEC 或公司 IR 一手证据，加至少一个独立来源。
- `verified_two_independent`：至少两个互相独立且位于白名单内的原创媒体来源。
- `primary_only_pending`：只有 SEC 或公司 IR 一手证据，等待独立媒体确认。
- `unverified_single_source`：只有一个独立媒体来源。

只有前两个 `verified_*` 状态可以作为加仓、减仓或清仓表述的新闻依据。`primary_only_pending` 和 `unverified_single_source` 只能进入数据限制或观察清单，不能驱动仓位动作。

## 组件设计

### `app/services/professional_news_service.py`

职责：

- 每次复盘获取并缓存 CNBC、MarketWatch 和 Nasdaq RSS。
- 获取并缓存 SEC ticker 元数据及发行人近期申报文件。
- 根据 SEC 元数据确定公司的官方 Investor Relations 域名。
- 将 URL 规范化为最终域名，并拒绝不在白名单内的域名。
- 保留 RSS publisher 元数据，禁止把 Nasdaq 的合作伙伴内容计作 Nasdaq 独立证据。
- 将发布时间统一为 UTC，并丢弃没有日期或超出每日时间窗口的候选新闻。
- 使用 ticker、规范化标题词和发布时间，以保守方式合并同一事件。
- 根据互相独立的原创发布者数量确定验证状态。
- 某个来源失败时，返回其他来源的部分结果和明确警告。

该服务使用项目现有的 `httpx` 依赖，并允许注入 `httpx.Client`，方便测试时使用确定性响应。RSS 结果在同一个服务实例中缓存，因此六个重点标的不应重复下载相同的 RSS。

### `app/services/daily_position_review_service.py`

增加可选的 `professional_news_service` 依赖。构建个股公开信息时执行：

1. 按现有逻辑获取 LongBridge 新闻、申报信息、行情和技术数据。
2. 将 LongBridge 新闻 URL 和股票代码交给专业新闻服务。
3. 增加 `news_evidence`，包含已验证事件、待确认事件、被拒绝来源数量和警告。
4. 保留原来的 `news` 作为原始发现数据，但 Prompt 不能将其视为已验证证据。

构建每日复盘上下文时，增加用于宏观 RSS 事件的 `professional_news_context`，并将 `data_sources.public_news` 设置为 `PROFESSIONAL_ENGLISH_CROSS_VERIFIED`。

### `app/agents/daily_position_review_graph/nodes.py`

宏观节点从确定性上下文读取 `professional_news_context`。LongBridge 宏观新闻搜索继续作为线索发现入口，但搜索结果必须经过相同的域名白名单过滤后才能合并。某个来源失败时，节点将错误写入 `data_limitations`，不能退回到不受限制的新闻来源。

### 证据 Prompt

更新个股和宏观证据 Prompt，使其遵循：

- 只有 `news_evidence.verified_events` 可以用于因果解释和与仓位动作有关的结论。
- `primary_only_pending` 和 `unverified_single_source` 只能进入观察点或数据限制。
- 不能把 `Longbridge news` 写成新闻发布者；必须引用证据中提供的最终域名和 URL。
- 没有已验证事件时，不能仅凭价格变化推断上涨或下跌原因。

### 依赖注入

在 `app/api/deps.py` 中创建一个 `ProfessionalNewsService`，并注入 `DailyPositionReviewService`。本阶段不增加新路由，也不增加新前端页面。

## 事件匹配与冲突处理

事件合并采用保守规则：

- 候选新闻必须属于同一个规范化股票代码。
- 发布时间差必须在 36 小时以内。
- 规范化标题词的 Jaccard 相似度必须达到 `0.45`。
- 比较前移除常见市场停用词、ticker 后缀和公司法律实体后缀。
- 出现假阴性时，事件保持未验证；系统不能为了强行确认而降低阈值。

如果两个已匹配来源在重要数字、日期、交易状态或管理层身份上存在冲突，系统必须记录冲突，并将事件降级为 `unverified_single_source`。Prompt 必须展示差异，且不能给出基于该事件的仓位动作。

## 失败处理

- 单个 RSS 来源失败不能导致整个每日复盘失败。
- 所有专业新闻来源都不可用时，系统返回空的已验证事件和明确警告。
- SEC 请求必须使用已配置且真实的 User-Agent。未配置时跳过 SEC 收集并给出警告，不能发送虚假联系地址。
- HTTP 请求必须设置有限超时时间，不能无限重试。
- 所有外部内容均按不可信文本处理，不能执行，也不能拼入 shell 命令。
- 新闻不可用时，现有行情、持仓、归因、风险、持久化和邮件链路仍须继续运行。

## 配置

在后端环境变量示例中增加可选的 `SEC_USER_AGENT`。该变量没有默认值，必须由使用者提供真实的应用描述和联系邮箱。未设置时跳过 SEC 收集，不能使用伪造身份。

该值只用于 SEC HTTP 请求，不能写入日志。RSS 收集不需要 API Key。Reuters 继续采用线索发现方式；当天没有符合条件的 Reuters URL 时，系统报告 `reuters_missing`。

## 测试策略

### 单元测试

- 接受白名单最终域名，拒绝中国网站及聚合网站域名。
- 通过 LongBridge 找到的 Reuters 新闻归属 Reuters，不能归属 LongBridge。
- Nasdaq 合作伙伴内容的 publisher 如果是 `Barchart`、`Zacks` 或其他非 Nasdaq 发布者，不能计作 Nasdaq 独立确认。
- SEC 加 Reuters 产生 `verified_primary_plus_independent`。
- CNBC 加 MarketWatch 产生 `verified_two_independent`。
- 单一来源产生 `unverified_single_source`，且不能成为仓位动作证据。
- 数字冲突会导致事件降级。
- Feed 超时返回部分结果和警告。
- Feed 缓存可以避免六个标的重复发起 HTTP 请求。

### 集成测试

- `DailyPositionReviewService.build_review_context()` 包含 `professional_news_context`，每个标的包含 `news_evidence`。
- 非白名单域名的 LongBridge 原始新闻不能进入证据层。
- 宏观和个股 Prompt 包含验证状态及最终来源。
- 所有专业来源不可用时，现有 LangGraph 每日复盘仍能完成。
- 现有每日复盘公开响应结构保持不变。

### 在线冒烟测试

提供一个显式启用的测试，访问三个官方 RSS 和 SEC 元数据。测试只输出条目数量、来源时间及失败信息，不能打印文章正文或配置值。

## 验收标准

- 生成的新闻证据中不能出现任何中国新闻域名。
- 每条能够影响仓位动作的新闻事件，必须拥有至少两个互相独立的原创媒体来源，或者一个一手来源加一个独立来源。
- 每个事件在内部保留最终 URL、最终域名、发布时间和验证状态。
- 来源故障只降低证据质量，不能破坏每日 IBKR 复盘。
- 每日复盘继续只使用 IBKR 账户和持仓事实。
- 不增加登录、付费 API、自动下单路径或公开响应结构变更。
