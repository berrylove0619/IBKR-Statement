# Account Copilot

## 业务定位

Account Copilot 是面向 IBKR 账户的 ChatGPT 式多轮账户级 Agent。它不是交易决策、交易复盘、每日复盘或风险评估 Agent 的包装层，而是统一的账户问答入口：用户用自然语言提问，Copilot 通过 ReAct 自主选择账户事实工具、长桥公开市场工具，必要时申请高阶 Skill，并把每轮 action、observation、tool call、approval 和 memory trace 持久化。

## 总体架构

- 前端：Vue 3 + Vite + TypeScript + PrimeVue，三栏 ChatGPT 式页面。
- 后端：FastAPI 路由 + service/repository 分层。
- 存储：Elasticsearch 保存 session、message、run、memory、event。
- 推理：LLM Planner 只输出结构化 action，不保存 hidden chain-of-thought。
- 工具：IBKR 只读账户事实工具 + Longbridge public market meta tools。
- Skill：只读高阶工作流，必须 Human-in-the-loop 审批后执行。

## 后端模块结构

- `app/api/routes/account_copilot.py`：API、SSE、health、demo seed。
- `app/agents/account_copilot/runtime.py`：LLM Planner + ReAct action/observation 循环。
- `app/agents/account_copilot/tool_registry.py`：Account Copilot 顶层工具注册。
- `app/agents/account_copilot/skill_registry.py`：Skill Catalog。
- `app/services/account_copilot/repository.py`：session/message/run ES 读写。
- `app/services/account_copilot/memory_service.py`：上下文压缩和记忆召回。
- `app/services/account_copilot/event_bus.py`：SSE run events。
- `app/services/account_copilot/demo_service.py`：本地演示 seed。

## 前端模块结构

- `src/views/AccountCopilotView.vue`：三栏页面和状态编排。
- `src/components/accountCopilot/CopilotSessionSidebar.vue`：会话列表。
- `src/components/accountCopilot/CopilotMessageList.vue`：消息流。
- `src/components/accountCopilot/CopilotApprovalCard.vue`：HITL 审批卡片。
- `src/components/accountCopilot/CopilotRunTracePanel.vue`：run trace、实时事件和执行摘要。
- `src/components/accountCopilot/CopilotMemoryPanel.vue`：会话 memory。
- `src/composables/useCopilotRunStream.ts`：SSE 自动重连和 after_seq 恢复。

## ReAct 流程

Runtime 每轮把用户输入、最近消息、rolling_summary、retrieved_memories、constraints、可用工具和可用 Skill Catalog 传给 Planner。Planner 每轮只能选择一个 action：

1. `call_tool`：后端校验工具存在、只读、有 handler，再执行并写 observation。
2. `final_answer`：证据足够时生成最终回答。
3. `request_skill_approval`：需要高阶 Skill 时暂停，进入 HITL。

每轮 observation 会回到下一轮 Planner。超过最大轮数、超时、取消、LLM 不可用或 planner JSON 非法时，都走保守 fallback。

## 工具体系

IBKR 账户事实工具共 9 个，全部只读，数据源是 IBKR/ES：

- `ibkr_get_account_overview`
- `ibkr_get_current_positions`
- `ibkr_get_symbol_position`
- `ibkr_get_symbol_trades`
- `ibkr_get_position_history`
- `ibkr_get_equity_curve`
- `ibkr_get_daily_attribution`
- `ibkr_get_risk_snapshot`
- `ibkr_get_cash_flow_summary`

Longbridge 只用于公开市场数据。Copilot 顶层只注册 6 个渐进式披露 meta tools：

- `longbridge_list_public_tool_categories`
- `longbridge_list_public_tools`
- `longbridge_get_public_tool_schema`
- `longbridge_get_public_tool_schemas`
- `longbridge_call_public_tool`
- `longbridge_call_public_tools`

`longbridge_list_public_tool_categories` 是第一层业务目录，覆盖行情、K线、新闻、财务、估值、分析师预期、财经日历、市场状态和公司信息等公开市场分类。`longbridge_list_public_tools` 返回 grouped list；`category` / `categories` 是结构化过滤，`query` 只用于排序，不用于过滤，因此不会因为 query 词没有完全命中而裁掉可用工具。

`longbridge_get_public_tool_schemas` 用于一次获取多个 public tool schema，减少 schema discovery 轮次。`longbridge_call_public_tools` 由后端并行执行多个公开市场只读工具；每个子工具调用前仍会重新校验 `public_market_readonly`，任一子工具失败不会拖垮整个 batch，结果会按 Account Copilot 上下文预算做压缩或截断。

禁止直接暴露长桥原始 100+ 工具。账户、订单、成交、持仓、出入金、交易写操作和 unknown 工具默认不可见、不可查 schema、不可调用。

### PublicMarketEvidenceBuilder

`PublicMarketEvidenceBuilder` 是内部公开市场证据组件，不是顶层 Skill，也不是用户可见工具。它只依赖 Account Copilot 的 Longbridge public market meta tools，通过 `longbridge_list_public_tools` 做可用性发现，并通过 `longbridge_call_public_tools` 批量获取公开市场只读数据，输出稳定的 public market Evidence Pack。

Evidence Pack 明确标注 `public_market_data = LONGBRIDGE_PUBLIC_ONLY`，并声明账户、持仓、交易等私有 IBKR 数据不包含在内。该组件后续可被交易决策、交易复盘、风险评估和每日复盘复用。本阶段实现 deterministic builder；LLM Evidence SubAgent 语义压缩留到后续阶段。

### PublicMarketEvidenceSubAgent

`PublicMarketEvidenceSubAgent` 是内部语义压缩组件，不是 Skill，也不是用户可见 tool。它不调用 Longbridge 工具，不读取 IBKR 私有账户、持仓或交易数据，只读取 `PublicMarketEvidenceBuilder` 输出的 Evidence Pack，并用 LLM 生成结构化 Semantic Evidence Pack。

该 SubAgent 只做公开市场证据整理，不做交易决策、交易复盘或确定性买卖建议。输出会过滤 hidden chain-of-thought，强制保留 `public_market_data = LONGBRIDGE_PUBLIC_ONLY` 和账户/持仓/交易数据 `NOT_INCLUDED` 的边界。后续交易决策、交易复盘、风险评估和每日复盘可以复用该语义证据层。

### SubAgent 委托机制

SubAgent 不是 Skill，也不是用户可见工具，不需要审批。主 Agent 可以通过 `delegate_to_subagent` action 委托探索性任务；SubAgent 的中间上下文不进入主 Agent，主 Agent 只接收压缩后的 `subagent_result` observation。

能力选择优先级写在 Planner prompt 中：Skill 优先，SubAgent 次之，普通只读工具最后。SubAgent 不能替代 Skill；涉及建仓、加仓、减仓、买入、卖出、交易复盘、账户风险、保证金、仓位、历史交易等问题，应优先申请对应 Skill。目前仅注册 `public_market_research_subagent`，它基于 `PublicMarketEvidenceBuilder` 做 Longbridge 公开市场研究，不读取 IBKR 私有账户事实。

## Skill + HITL 审批

Skill 不是普通工具，LLM 不能直接执行，只能申请。后端保存 `pending_approval`，校验 `approval_id`、`skill_name`、`skill_arguments`、`plan_hash`。用户批准后才执行 Skill，并把 Skill result 写成 observation，再调用 LLM 生成最终回答。用户拒绝或审批过期时，不执行 Skill，不编造完整结论。

当前 Skill Catalog：

- `trade_decision_entry_skill`
- `trade_decision_holding_skill`
- `trade_review_symbol_skill`
- `daily_position_review_skill`
- `risk_assessment_skill`

## Memory 分层设计

- L0：原始消息完整保留在 messages index。
- L1：最近上下文原文进入 prompt。
- L2：旧消息压缩成结构化 memory segment。
- L3：按 symbol/topic/query 召回相关 memory。
- L4：长期偏好、安全约束和用户明确要求。

Memory 不能覆盖账户事实。IBKR 工具返回的实时事实优先于旧 memory。

## SSE 事件流

`POST /sessions/{session_id}/messages/stream` 创建 run 后立即返回，前端连接：

`GET /runs/{run_id}/events?after_seq=N`

事件包括 `planner_started`、`planner_finished`、`tool_started`、`tool_finished`、`observation_created`、`skill_approval_requested`、`final_answer`、`memory_update_finished`、`run_completed`、`run_failed`、`run_cancelled`。页面刷新后可通过 `/events/list` 恢复历史事件，再用 `after_seq` 继续接 SSE。

## 生产化兜底

- timeout：默认 180 秒，超时安全停止并写 `RUN_TIMEOUT`。
- cancel：用户可取消 queued/running/awaiting_approval run，后台完成后不会覆盖 cancelled。
- approval expired：审批过期后标记 expired，不执行 Skill。
- payload sanitizer：SSE payload 删除 token、api_key、authorization、cookie、reasoning、chain_of_thought，并裁剪大 JSON。
- active run 防并发：同一 session 有 queued/running/awaiting_approval 时阻止新消息。

## 本地启动方式

```bash
cd ibkr_show_backend
./.venv/bin/uvicorn app.main:app --reload

cd ../ibkr_show_frontend
npm run dev
```

## Demo Mode 使用方式

默认关闭：

```bash
ACCOUNT_COPILOT_DEMO_MODE=false
```

开启后可调用：

```bash
curl -X POST http://127.0.0.1:8000/api/agent/account-copilot/demo/seed
```

前端 health 返回 `demo_mode=true` 时会显示“加载 Demo 会话”。Demo seed 会创建风险问答、Longbridge 渐进披露、awaiting approval Skill run 和一段 compressed memory。

## 面试讲解稿

### 1 分钟版

Account Copilot 是一个面向 IBKR 账户的多轮投资分析 Agent，它通过 ReAct 自主调用 IBKR 账户事实工具和长桥公开市场工具，并通过 Skill + HITL 机制调用交易决策、交易复盘等高阶工作流。系统支持上下文压缩、结构化记忆、SSE 实时进度和完整 run trace，保证金融分析场景下的可控、可追踪和可恢复。

### 3 分钟版

它不是固定 DAG，因为用户问题可能从账户风险、单票持仓、公开新闻、历史交易行为一路跳转到高阶决策。固定路由很容易把复杂意图写死，也难以解释为什么调用某个能力。Account Copilot 用外层状态机保证安全和持久化，用内层 ReAct 让 LLM 每轮基于 observation 决定下一步。

Longbridge 工具很多，所以只暴露 3 个 meta tools，让模型先查公开工具目录，再按需取 schema，再调用已确认的 public readonly 工具。Skill 必须审批，因为交易决策、复盘和风险评估是高阶工作流，可能影响用户行为，LLM 只能申请，不能绕过用户执行。

Memory 用来保留会话历史、偏好和约束，但不能替代账户事实。只要涉及真实仓位、现金、PnL、风险，必须以 IBKR 工具为准。可观测性通过 run trace、actions、observations、tool_calls、events 和 memory_snapshot 实现，生产兜底包括 timeout、cancel、approval expired、payload sanitizer 和 active run 防并发。

### 5 分钟版

一次端到端链路是：用户在前端发送问题，后端创建 user message 和 run，SSE 立即返回执行进度。Runtime 构建 memory context，把最近消息、rolling_summary、retrieved_memories、不可压缩约束、顶层工具和 Skill Catalog 交给 Planner。Planner 输出结构化 action。如果是账户事实问题，Runtime 调用 IBKR 工具并生成 observation；如果是公开市场问题，先通过 Longbridge meta tools 渐进披露；如果需要高阶能力，Planner 输出 request_skill_approval，后端进入 awaiting_approval。

用户批准 Skill 后，ApprovalService 校验 approval_id 和 plan_hash，执行只读 Skill，把结果压缩成 skill_result observation，再让 LLM 基于原问题、审批信息和 observation 生成最终回答。所有 message、run、event、memory 都保存在 ES，刷新页面后可以恢复会话、消息、run trace、pending approval 和 memory。取消、超时、审批过期、工具失败都不会让 API 500，而是写入可追踪状态和保守回答。
