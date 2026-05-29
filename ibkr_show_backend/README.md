# ibkr_show_backend

FastAPI 查询层，从 Elasticsearch 读取 IBKR ETL 数据并对前端提供 REST API。

## 快速开始

```bash
cd /path/to/ibkr_show/ibkr_show_backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## ES 配置

`.env` 至少需要配置：

- `ES_HOST=http://localhost:9200`
- `CORS_ALLOW_ORIGINS=http://localhost:5173,http://127.0.0.1:5173`
- `CORS_ALLOW_ORIGIN_REGEX=https?://.*`
- `ES_USERNAME=`
- `ES_PASSWORD=`
- `ES_VERIFY_CERTS=false`
- `ES_ACCOUNT_INDEX=ibkr_account_daily_snapshot_v1`
- `ES_POSITION_INDEX=ibkr_position_daily_snapshot_v1`
- `ES_TRADE_INDEX=ibkr_trade_records_v1`
- `ES_CASH_FLOW_INDEX=ibkr_cash_flow_records_v1`
- `ES_PRICE_HISTORY_INDEX=ibkr_symbol_price_history_v1`

## Longbridge 外部数据源配置

Longbridge 只用于外部行情和资讯数据。IBKR Flex 仍是账户、持仓、交易、成本、盈亏、股息和出入金的唯一数据源。

如需启用，在 `ibkr_show_backend/.env` 中配置：

```env
LONGBRIDGE_ENABLE=true
LONGBRIDGE_OPENAPI_OAUTH_CLIENT_ID=
LONGBRIDGE_OPENAPI_OAUTH_FILE=./data/config/longbridge_openapi_oauth.json
LONGBRIDGE_OPENAPI_OAUTH_SCOPE=
LONGBRIDGE_MCP_ENABLED=true
LONGBRIDGE_MCP_ENDPOINT=https://openapi.longbridge.com/mcp
```

不要把 `.env` 提交到 git。即使 `LONGBRIDGE_ENABLE=false` 或 LongBridge OAuth 未连接，后端也会正常启动，只是 `/api/longbridge/*`、依赖 OpenAPI / SDK 的外部数据功能，以及 MCP 工具调用不可用。

LongBridge 只需要一次 OAuth 授权。OpenAPI OAuth 是唯一授权源，OpenAPI / SDK 和 hosted MCP 复用同一个 OAuth token。MCP 仍只允许公开市场只读工具，不会调用 LongBridge TradeContext，不会下单，不会访问长桥账户、订单、持仓、成交或出入金接口。

第二阶段已验证 OpenAPI OAuth token 与 MCP 双向复用成功，因此第三阶段已统一为 OpenAPI OAuth 单授权。旧版 `LONGBRIDGE_APP_KEY`、`LONGBRIDGE_APP_SECRET`、`LONGBRIDGE_ACCESS_TOKEN` 已废弃，不再作为后端 SDK fallback。

生产环境配置步骤：

1. 在 LongBridge 注册 OAuth client_id。
2. 配置 `LONGBRIDGE_OPENAPI_OAUTH_CLIENT_ID`。
3. 重启 backend。
4. 到管理后台 `/admin/longbridge-mcp` 完成一次 LongBridge OAuth 授权。
5. 检查 OpenAPI / SDK 和 MCP 健康状态均为可用。

历史的 `data/config/longbridge_mcp_oauth.json` 已废弃，可手动删除；程序不会再读取它。

## LLM 配置管理

后台路径：

- `/admin/llm`

当前支持 OpenAI-compatible 协议，后续交易得失复盘 Agent、个股决策 Agent 都应统一通过后端 `LLMService` 读取 active Provider，不直接读取厂商 API Key 或写死 `base_url`。

可在后台新增多个 Provider，但同一时间只能有一个 active/default Provider。API Key 只保存在后端配置文件中，前端接口只返回 masked key，例如 `sk-****abcd`。

小米 LLM 示例配置：

```text
Base URL: https://token-plan-cn.xiaomimimo.com/v1
Model: 由用户在后台填写
API Key: 在后台填写，或通过环境变量 LLM_DEFAULT_API_KEY 提供
```

阿里百炼 / DashScope OpenAI-compatible 示例配置：

```text
Base URL: https://dashscope.aliyuncs.com/compatible-mode/v1
Model: deepseek-v4-pro
API Key: 在后台填写，或通过环境变量 LLM_DEFAULT_API_KEY 提供
```

环境变量：

```env
LLM_ENABLE=true
LLM_DEFAULT_PROVIDER_NAME=
LLM_DEFAULT_BASE_URL=
LLM_DEFAULT_API_KEY=
LLM_DEFAULT_MODEL=
LLM_CONFIG_FILE=
```

如果本地 JSON 配置文件没有任何 Provider，但环境变量中存在 `LLM_DEFAULT_BASE_URL`、`LLM_DEFAULT_API_KEY`、`LLM_DEFAULT_MODEL`，后端会构造一个临时默认 Provider 用于 health/test/chat。环境变量中的 API Key 不会自动写入配置文件，除非你在后台主动保存。

默认配置文件路径是 `ibkr_show_backend/data/config/llm_providers.json`，也可以用 `LLM_CONFIG_FILE` 覆盖。`data/config/*.json` 已加入 git 忽略规则。不要提交真实 API Key。

## 每日持仓复盘邮件

后台路径：

- `/admin/email`

开启后，worker 触发的每日自动复盘在生成成功后会通过 SMTP 发送摘要邮件。手动点击生成或重新生成复盘默认不发送邮件，避免重复通知。后台支持保存 SMTP 配置和发送测试邮件，密码/授权码只保存在后端配置文件中，前端只显示 masked 状态。

环境变量：

```env
DAILY_REVIEW_EMAIL_ENABLE=false
SMTP_HOST=
SMTP_PORT=465
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_USE_SSL=true
SMTP_USE_STARTTLS=false
EMAIL_FROM=
DAILY_REVIEW_EMAIL_TO=
DAILY_REVIEW_EMAIL_SUBJECT_PREFIX=IBKR每日持仓复盘
PUBLIC_SITE_BASE_URL=
EMAIL_CONFIG_FILE=
```

默认配置文件路径是 `ibkr_show_backend/data/config/email.json`，也可以用 `EMAIL_CONFIG_FILE` 覆盖。后台保存的配置优先于环境变量。邮件密码建议使用邮箱授权码，不要使用邮箱登录密码；网易、QQ、Gmail 等邮箱通常需要先开启 SMTP 服务。

## 交易得失复盘 Agent

前端页面：

- `/agent/trade-review`

数据来源：

- IBKR Flex：交易事实、账户、持仓、成本、盈亏
- Longbridge：历史行情、默认基准 ETF `SPY.US`、`QQQ.US`、`SMH.US`，以及资讯
- LLMService：基于 Evidence Pack 进行复盘分析和打分

复盘目标：

- 以平均年化 30% 为目标
- 投资风格为 aggressive growth
- 用 100 分制评估交易是否帮助长期最大化账户复合收益
- 支持标的级复盘和单笔交易复盘

评分维度：

- 收益结果 20 分
- 相对收益 15 分
- 买点质量 15 分
- 卖点质量 15 分
- 仓位质量 15 分
- 持仓周期 5 分
- 风险控制 10 分
- 决策归因 5 分

后端接口：

- `GET /api/agent/trade-review/health`
- `POST /api/agent/trade-review/symbol/{symbol}/generate`
- `POST /api/agent/trade-review/trade/{trade_id}/generate`
- `GET /api/agent/trade-review/symbol/{symbol}`
- `GET /api/agent/trade-review/recent`
- `GET /api/agent/trade-review/{review_id}`
- `GET /api/agent/trade-review/mistakes/summary`

复盘结果保存到 Elasticsearch 索引：

- `ibkr_trade_reviews_v1`

安全说明：

- 不会自动交易
- 不会调用 IBKR 下单接口
- 不会调用 Longbridge TradeContext
- 不会从长桥获取账户、持仓、订单、成交
- 不会暴露 LLM API Key 或 Longbridge Key
- Evidence Pack 原文只在后端保存，前端页面只展示复盘结论、分数、标签和建议

## 交易决策 Agent

前端页面：

- `/agent/trade-decision`

支持两种模式：

- 持仓标的决策：展示 IBKR 当前持仓，针对单个持仓生成加仓、持有、减仓、清仓或等待建议
- 任意股票建仓建议：输入任意股票代码，结合账户净值、现金比例、已有持仓集中度和公开市场数据生成建仓建议

数据来源：

- IBKR Flex：账户、持仓、交易、成本、盈亏、现金、保证金、股息、出入金等个人账户数据
- Longbridge：公开行情、历史 K 线、基准 ETF、新闻、公告、财报、估值等公开数据
- Trade Review Agent：历史复盘结果和错误标签
- LLMService：基于 Evidence Pack 输出结构化决策

评分维度：

- 公司质量 20 分
- 估值 15 分
- 趋势 15 分
- 账户适配 20 分
- 风险收益 15 分
- 复盘约束 10 分
- 事件催化 5 分

后端接口：

- `GET /api/agent/trade-decision/health`
- `GET /api/agent/trade-decision/holdings`
- `POST /api/agent/trade-decision/holding/{symbol}/analyze`
- `POST /api/agent/trade-decision/entry/analyze`
- `GET /api/agent/trade-decision/recent`
- `GET /api/agent/trade-decision/symbol/{symbol}`
- `GET /api/agent/trade-decision/{decision_id}`

交易决策结果保存到 Elasticsearch 索引：

- `ibkr_trade_decisions_v1`

安全说明：

- 不会自动交易
- 不会生成订单草稿
- 不会调用 IBKR 下单接口
- 不会调用 Longbridge TradeContext
- 不会从长桥获取账户、持仓、订单、成交或资金数据
- 不会暴露 LLM API Key 或 Longbridge Key
- Evidence Pack 原文只在后端保存，前端页面只展示决策结论、分数、仓位建议和风险提示

## 启动 API

```bash
cd /path/to/ibkr_show/ibkr_show_backend
./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 接口说明

- `GET /health`
- `GET /api/account/overview`
- `GET /api/account/latest-report-date`
- `GET /api/charts/equity-curve`
- `GET /api/positions`
- `GET /api/positions/detail`
- `GET /api/trades`
- `GET /api/trades/summary`
- `GET /api/cash-flows`
- `GET /api/cash-flows/summary`
- `GET /api/longbridge/health`
- `GET /api/longbridge/candles`
- `GET /api/longbridge/benchmark-candles`
- `GET /api/longbridge/news`
- `GET /api/admin/llm/health`
- `GET /api/admin/llm/providers`
- `POST /api/admin/llm/providers`
- `PUT /api/admin/llm/providers/{provider_id}`
- `DELETE /api/admin/llm/providers/{provider_id}`
- `POST /api/admin/llm/providers/{provider_id}/activate`
- `POST /api/admin/llm/providers/{provider_id}/test`
- `POST /api/admin/llm/chat-test`
- `GET /api/admin/email/settings`
- `PUT /api/admin/email/settings`
- `POST /api/admin/email/test`
- `GET /api/agent/trade-review/health`
- `POST /api/agent/trade-review/symbol/{symbol}/generate`
- `POST /api/agent/trade-review/trade/{trade_id}/generate`
- `GET /api/agent/trade-review/recent`
- `GET /api/agent/trade-review/mistakes/summary`

## 接口示例

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/account/overview
curl 'http://localhost:8000/api/charts/equity-curve?start_date=2026-01-01&end_date=2026-04-17'
curl 'http://localhost:8000/api/positions?sort_by=position_value&sort_order=desc&page=1&page_size=20'
curl 'http://localhost:8000/api/positions/detail?symbol=AAPL&asset_class=STK'
curl 'http://localhost:8000/api/trades?sort_by=date_time&sort_order=desc&page=1&page_size=20'
curl 'http://localhost:8000/api/trades/summary?start_date=2026-01-01&end_date=2026-04-17'
curl 'http://localhost:8000/api/cash-flows?page=1&page_size=20'
curl 'http://localhost:8000/api/cash-flows/summary'
curl http://localhost:8000/api/longbridge/health
curl 'http://localhost:8000/api/longbridge/candles?symbol=AAPL&start=2025-01-01&end=2025-01-31'
curl 'http://localhost:8000/api/longbridge/benchmark-candles?symbols=SPY,QQQ,SMH&start=2025-01-01&end=2025-01-31'
curl 'http://localhost:8000/api/longbridge/news?symbol=AAPL&limit=10'
```

如果 ES 不可达或索引不存在，接口会返回清晰错误，不会把 ES 原始响应直接透传给前端。
