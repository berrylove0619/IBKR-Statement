# 线上 E2E 验收报告

## 1. 验收环境

- domain: https://your-domain.example
- 登录是否成功: 成功，浏览器显示已登录用户，首页/持仓/交易/Agent 页面可进入
- 验证时间: 2026-05-21 约 22:20-22:40 Asia/Shanghai
- 浏览器: Codex in-app browser
- 当前线上版本 / commit: 页面与 `/health` 未暴露 commit；`/health` 返回 `{"status":"ok","service":"ibkr_show_backend"}`
- LLM provider 状态: P0/P2/P3 health 显示 LLM ready；P3 结果 metadata 显示 provider `Xiaomi E2E`, model `mimo-v2.5-pro`
- MCP 状态: P0 health 显示 `mcp_enabled=true`, `mcp_available=true`, `public_data_mode=mcp`；但 P0 生成结果 metadata 显示 `mcp_available=false`
- Longbridge 状态: P0/P2/P3 health 均显示 configured/ready；公开数据实际存在大面积缺失或 fallback

## 2. 账户基础数据快照

- net liquidation / total equity: 77,840.83 USD
- cash: 8,691.60 USD
- position count: 12
- top holdings: AMD 29.77%, MSFT 17.66%, META 12.25%, XIACY 10.37%, MSTR 9.11%
- 可用 symbol: AMD, MSFT, META, XIACY, MSTR, INTC, QCOM, TSLA, ORCL, SMCI, CRWV, IBKR；AAPL 当前无持仓但可做建仓建议
- recent trade symbol: XIACY / CRWV
- recent trade id: `9542804678` / `9542631804` / `9538427537`
- 交易日期范围: API 当前页包含 2026-05-20 起的最新交易；summary 显示 140 笔交易、28 个标的
- available daily review date: 2026-05-20

## 3. Agent Health 汇总

| Agent | endpoint | HTTP | agent_mode | graph_version | LLM | MCP | public_data_mode | 结论 |
|---|---|---:|---|---|---|---|---|---|
| P0 交易决策 | `/api/agent/trade-decision/health` | 200 | health 未返回 | health 未返回 | true | available=true | mcp | Health 缺少要求字段，且与结果 metadata 不一致 |
| P1 风险评估 | `/api/agent/risk-assessment/health` | 500 | 不可读 | 不可读 | 不可读 | 不可读 | 不可读 | 主流程不可用 |
| P2 每日持仓复盘 | `/api/agent/daily-position-review/health` | 200 | `daily_position_review_langgraph_v1` | `daily_position_review_graph_v1` | true | 未暴露 | 未暴露，source 为 Longbridge public only | Health 正常，但实际生成失败兜底 |
| P3 交易复盘 | `/api/agent/trade-review/health` | 200 | `trade_review_langgraph_v1` | `trade_review_graph_v1` | true | 未暴露 | `LONGBRIDGE_MCP_OR_SDK_PUBLIC_ONLY` | Health 正常，但新结果缺 run_trace/evidence |

## 4. P0 交易决策验收

- 建仓建议测试 symbol: AAPL.US
- 持仓建议测试 symbol: AMD.US
- result id: AAPL `tdc-20260521142624`; AMD `tdc-20260521142736`
- UI: 页面可打开，可提交任务，任务完成后可展示结果详情
- LangGraph: 两个结果 metadata 均为 `trade_decision_langgraph_v1` / `trade_decision_graph_v1`
- run_trace nodes: 两个结果均包含 `build_account_facts`, `account_fit`, `market_trend`, `fundamental_valuation`, `event_catalyst`, `risk_reward`, `build_card_pack`, `compose_decision`, `persist_decision`
- 账户/持仓事实: AMD 持仓结果读到 `current_position_pct=0.2977`，与持仓页 29.77% 一致；账户/持仓/交易 source 均为 `IBKR_ONLY`
- card_pack 完整性: API 结果没有顶层 `card_pack` 字段，虽然 run_trace 有 `build_card_pack`
- 数据缺失判断: AAPL/AMD 的 fundamental/valuation 为 0，AMD event 为 0；data_limitations 包含 quote 空、财务/估值缺失、公开数据大面积 fallback；AMD 还有 LLM provider 400 `reasoning_content` 错误
- 结论: 主流程可用，LangGraph 路径可确认；但 health 字段缺失、card_pack 不暴露、MCP 状态不一致、公开数据大面积 fallback，不能算通过

## 5. P1 风险评估验收

- result id: 无，生成接口返回 500
- health: `/api/agent/risk-assessment/health` 返回 500 `Internal Server Error`
- generate: `POST /api/agent/risk-assessment/tasks` 返回 500 `Internal Server Error`
- overall_risk_score / risk_level / confidence: 不可获得
- card_pack / stress_test / key_risks / suggested_actions: 不可获得
- run_trace: 不可获得
- 数据缺失判断: 页面已有真实持仓和账户数据，但风险评估 Agent 完全不可用，属于系统 bug
- 结论: 不通过，P0 级主流程故障

## 6. P2 每日持仓复盘验收

- report_date: 2026-05-20
- result id: `2026-05-20`
- UI: 页面可打开，可触发任务；确定性账户归因区域可展示
- 任务状态: 最近任务显示 completed，但历史任务多次 timeout
- symbol_cards 数量: 0；API 未返回 `subagent_card_pack`
- macro_card 状态: 不存在
- portfolio_attribution 状态: 确定性 context 有 top contributors/drags；LLM 结果 attribution 为兜底失败文案
- risk_watch 状态: 确定性 risk 卡可展示集中度、现金、主题暴露；LLM 结果 risk_analysis 为兜底失败文案
- run_trace: 空数组
- 是否出现旧 context budget 噪声: 本次 P2 结果未出现该噪声，但直接是 `graph_failed: graph completed without saving`
- 数据缺失判断: IBKR/ES 基础数据完整，context 能看到 12 个持仓、AMD 贡献、XIACY 拖累；Agent 图结果没有保存有效 card pack/trace，属于系统 bug
- 结论: 不通过，任务状态 completed 但结果是失败兜底，P0/P1 级

## 7. P3 交易复盘验收

- symbol-level 测试 symbol: XIACY.US
- symbol-level result id: `fb240799-9767-42e5-87ad-e5e89dcbe238`
- single-trade 测试 trade_id: `9538427537` (CRWV BUY，仍持仓)
- single-trade result id: `e69c37b9-a05d-4b9b-9b54-851a9ed65644`
- UI: 页面可打开，可触发 symbol-level 与 single-trade，结果可展示
- metadata: 两个新结果均为 `trade_review_langgraph_v1` / `trade_review_graph_v1`
- trade_facts 是否 IBKR_ONLY: 结果本身没有 evidence_pack；从 trade_ids、交易明细和文案可确认读取了 IBKR trade_id，但 API 未暴露 `evidence_pack.data_sources`
- run_trace nodes: 两个新结果 `run_trace=[]`，缺少要求的 `load_trade_facts`, `position_evidence`, `account_evidence`, `market_evidence`, `benchmark_evidence`, `event_evidence`, `build_trade_review_context`, `behavior_pattern`, `opportunity_cost`, `compose_trade_review`, `persist_trade_review`
- market/benchmark/event 状态: XIACY 缺少 benchmark，价格数据只到 2026-03-19；CRWV benchmark 口径看起来不可靠，将极短持仓与长区间 ETF 回报比较
- 数据缺失判断: trade_ids 非空，主文本可生成；但 evidence_pack/evidence_summary/run_trace 缺失，无法验收数据来源隔离和 LangGraph 节点执行完整性
- single BUY 检查: CRWV 没有整体给 0 分，能评价买点、仓位、买入后表现和风险控制；但 exit_quality 因无 SELL 直接 0 分，仍不符合“开放持仓应评价退出计划质量”的最佳要求
- 结论: 主输出可用但审计信息严重缺失，不通过

## 8. 前端页面验收

| 页面 | 路径 | 是否可打开 | 是否能生成 | 是否能展示详情 | Console Error | Network Error | 结论 |
|---|---|---|---|---|---|---|---|
| 首页 | `/` | 是 | 不适用 | 是 | 无明显 error | 无持续 401/403/500 | 通过 |
| 持仓 | `/positions` | 是 | 不适用 | 是 | 无明显 error | 无持续错误 | 通过 |
| 交易明细 | `/trades` | 是 | 不适用 | 是 | 无明显 error | 无持续错误 | 通过 |
| P0 交易决策 | `/agent/trade-decision` | 是 | 是 | 是 | 无明显 error | 生成成功 | 部分通过，公开数据/审计字段问题 |
| P1 风险评估 | 无前端路由 | 不适用 | 否 | 否 | 不适用 | API 500 | 不通过 |
| P2 每日持仓复盘 | `/agent/daily-position-review` | 是 | 是 | 是 | 无明显 error | 任务 completed 但结果失败兜底 | 不通过 |
| P3 交易复盘 | `/agent/trade-review` | 是 | 是 | 是 | 无明显 error | 生成成功 | 部分通过，trace/evidence 缺失 |

## 9. 问题清单

| 编号 | 严重级别 | Agent/页面 | 问题 | 复现步骤 | 预期 | 实际 | 数据缺失类型 | 可能原因 | 证据 |
|---|---|---|---|---|---|---|---|---|---|
| E2E-001 | P0 | P1 风险评估 | health 500 | GET `/api/agent/risk-assessment/health` | 返回 LangGraph health JSON | 500 Internal Server Error | 全部字段缺失 | agent 初始化或 health schema 异常 | HTTP 500 |
| E2E-002 | P0 | P1 风险评估 | 生成 500 | POST `/api/agent/risk-assessment/tasks` | 返回 risk result | 500 Internal Server Error | score/card/run_trace 全缺失 | graph 或依赖服务异常 | HTTP 500 |
| E2E-003 | P0 | P2 每日复盘 | 任务 completed 但结果为失败兜底 | 页面触发 2026-05-20 生成 | 有 symbol_cards/macro/attribution/risk_watch/run_trace | `graph completed without saving`, run_trace 空 | card_pack、symbol_cards、run_trace 缺失 | graph fan-in/persist 未保存或 runner 异常吞掉 | result id `2026-05-20` |
| E2E-004 | P1 | P0 交易决策 health | health 缺少 `agent_mode` 和 `graph_version` | GET `/api/agent/trade-decision/health` | 返回 `trade_decision_langgraph_v1` 和 graph version | 字段缺失 | metadata 缺失 | health schema 未补齐 | health JSON |
| E2E-005 | P1 | P0 交易决策 | health MCP 可用但结果 metadata 为不可用 | 生成 AAPL/AMD 后查 metadata | health/result 状态一致 | health `mcp_available=true`，result `mcp_available=false` | 状态不一致 | 运行期 MCP 检测或 metadata 写入错误 | `tdc-20260521142624`, `tdc-20260521142736` |
| E2E-006 | P1 | P0 交易决策 | card_pack 不在 API 响应中 | 查 trade decision detail | 暴露 card_pack | 顶层无 card_pack | card_pack 缺失 | response schema 未返回 | run_trace 有 `build_card_pack` |
| E2E-007 | P1 | P0 交易决策 | 公开数据大面积 fallback | 生成 AAPL/AMD | fundamental/valuation/event 至少部分可用，fallback 有限 | fundamental/valuation 为 0，AMD event 为 0，data_limitations 写明大面积 fallback | public market/fundamental/event 缺失 | Longbridge/MCP 或 LLM subagent 错误 | AMD data_limitations 含 reasoning_content 400 |
| E2E-008 | P1 | P3 交易复盘 | 新 LangGraph 结果 run_trace/evidence_summary 为空 | 生成 XIACY symbol 与 CRWV single | 返回完整节点 trace 和 evidence_summary | `run_trace=[]`, `evidence_summary={}` | 审计链路缺失 | graph runner 未持久化 trace 或 response 丢字段 | result ids `fb240...`, `e69c...` |
| E2E-009 | P1 | P3 交易复盘 | API 不暴露 evidence_pack | GET recent/detail | 可检查 IBKR_ONLY / Longbridge public only | 没有 evidence_pack | data_sources 不可验证 | route `include_evidence` 未实际开启 | recent/detail JSON |
| E2E-010 | P1 | P3 交易复盘 | XIACY market/benchmark 数据不足 | 生成 XIACY 6 个月复盘 | 有 benchmark/event/完整价格区间 | benchmark 缺失，价格数据只到 2026-03-19 | public market data 缺失 | Longbridge 数据或时间范围处理错误 | XIACY data_limitations |
| E2E-011 | P2 | P0 前端 | AMD.US 持仓管理表单提示“无持仓” | 输入 AMD.US 做持仓建议 | 识别当前 AMD 持仓 | 表单提示无持仓，但 Agent 结果读到 29.77% | 前端 symbol 匹配错误 | AMD vs AMD.US 归一化不一致 | 页面 DOM |
| E2E-012 | P2 | P3 前端/历史 | 最近复盘仍展示旧 tool_calling/context budget 噪声 | 打开 `/agent/trade-review` | 默认展示新 LangGraph 或过滤旧噪声 | 历史 SMCI 显示 `review_context被压缩...`，metadata 有 `tool_calling` | 旧路径噪声 | 历史结果未迁移/未过滤 | recent JSON |
| E2E-013 | P2 | P3 单笔复盘 | 开放 BUY 的 exit_quality 因无 SELL 得 0 | 复盘 CRWV BUY trade | 评价退出计划质量，不因无 SELL 直接 0 | 总分非 0，但 exit_quality=0 | 评分维度偏差 | open-position rubric 未完全应用 | result `e69c...` |
| E2E-014 | P3 | P0/P3 文案 | 结果中出现 Python dict 风格字符串和 unknown tag 过滤文案 | 查看 AAPL/XIACY/CRWV 结果 | 面向用户的结构化自然语言 | `{'event': ...}`、`Unknown mistake tags filtered...` | 展示体验 | LLM 输出未规范化或内部提示泄漏 | UI 与 JSON |

## 10. 总结结论

1. 不建议继续部署当前版本作为稳定线上版本。
2. 如果这是刚发布的新版本，建议回滚或至少暂停继续推广；如果已在线，应优先热修 P1 风险评估和 P2 每日复盘。
3. 存在 P0/P1 问题：P0 3 个，P1 7 个。
4. 最优先修复的 5 个问题：
   - P1 风险评估 health/generate 500。
   - P2 每日复盘 graph completed without saving，但任务标为 completed。
   - P3 新 LangGraph 结果缺 run_trace/evidence_summary/evidence_pack。
   - P0 交易决策 health 缺 agent_mode/graph_version 且 MCP 状态不一致。
   - P0 公开市场/基本面/事件数据大面积 fallback，AMD 触发 LLM provider reasoning_content 400。
5. 数据缺失主要集中在 P1、P2、P3 的审计字段，以及 P0/P3 的公开市场数据。
6. 根因倾向：
   - P1/P2 是 Agent graph/runner/persist 或 health 初始化问题。
   - P0/P3 的行情、估值、事件、benchmark 缺失更像 MCP/Longbridge 或 subagent 调用问题。
   - 前端有 symbol 归一化展示问题，但 IBKR/ES 基础账户和交易数据本身是可用的。
7. 下一步建议：
   - 先修 P1 500 和 P2 graph persist，不要让失败兜底写成 completed。
   - 补齐四个 Agent health 和 result schema 的 `agent_mode`, `graph_version`, `card_pack/evidence_pack`, `run_trace`。
   - 统一 MCP availability 检测，并把 Longbridge/MCP fallback 明确写入 metadata 和 data_limitations。
   - 对 P3 开放 BUY 持仓使用 entry/open-position rubric，避免 exit_quality 单纯因无 SELL 归零。
   - 清理或迁移旧 tool_calling/context budget 历史结果，避免前端默认展示旧噪声。
