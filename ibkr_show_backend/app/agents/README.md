# Agent Harness 文档

本目录包含 IBKR Show Agent 系统的核心组件。

## 目录结构

| 文件 | 说明 |
|------|------|
| `versions.py` | 版本常量和元信息定义 |
| `evidence_summary.py` | Evidence Summary 构建器 |
| `trace_summary.py` | Run Trace 摘要构建器 |
| `evidence_schema.py` | 各 Agent 的 Evidence Pack Schema |
| `output_schemas.py` | Agent 输出 Schema |
| `context_budget.py` | 上下文预算管理 |
| `invariants.py` | 输出标准化和不变量 |
| `runtime.py` | Agent 运行时（ToolCallingRuntime） |

## 版本体系

### 版本常量（versions.py）

- `AGENT_HARNESS_VERSION`: Harness 整体版本（p1.0）
- `TRADE_DECISION_AGENT_VERSION`: 交易决策 Agent 版本（trade_decision_v2）
- `TRADE_REVIEW_AGENT_VERSION`: 交易复盘 Agent 版本（trade_review_v2）
- `DAILY_POSITION_REVIEW_AGENT_VERSION`: 每日持仓复盘 Agent 版本（daily_position_review_v2）
- Prompt / Toolset / Evidence Builder 各有独立版本
- `build_metadata()` 生成标准元信息字典

### Agent 模式（AGENT_MODE_*）

| 模式 | 说明 |
|------|------|
| `fixed_evidence` | 固定证据集模式，证据在运行前构建完毕，Agent 只做分析和生成 |
| `tool_calling` | 工具调用模式 |
| `fixed_evidence_with_single_tool` | 固定证据+单工具模式 |
| `legacy_tool_calling` | 旧版工具调用模式 |

## Evidence Summary（evidence_summary.py）

`build_evidence_summary()` 将完整 `evidence_pack` 转换为前端安全的摘要：

- **不返回**：`evidence_pack` 原文、`raw_llm_response`、敏感字段（token、api_key、password 等）
- **返回**：
  - `data_sources`: 数据源策略
  - `evidence_sections`: 各分段的状态、来源、数据量、摘要
  - `tools_used`: 工具调用记录
  - `missing_data`: 缺失的必需数据段
  - `data_limitations`: 数据局限说明
  - `budget_summary`: 上下文预算消耗统计
  - `llm_input_policy`: LLM 输入策略

## Run Trace Summary（trace_summary.py）

`build_run_trace_summary()` 将完整 `run_trace` 转换为可读摘要：

- `tool_call_count`: 工具调用总次数
- `tool_success_count` / `tool_error_count`: 成功/失败次数
- `llm_rounds`: LLM 调用轮次
- `truncated_observations`: 截断的观察结果数
- `llm_started` / `llm_finished`: 耗时统计
- `tools`: 各工具的调用详情（含截断状态和大小）

## 数据流

```
Agent.generate_*()
  -> build_*_evidence_pack()      # 构建证据包
  -> ToolCallingRuntime.run()     # 运行 Agent
  -> build_metadata()             # 生成版本元信息
  -> build_evidence_summary()     # 生成证据摘要
  -> build_run_trace_summary()   # 生成运行轨迹摘要
  -> repository.save_*()          # 保存完整文档（含 run_trace）
```

前端通过 API 获取时：
- `metadata`: 版本元信息
- `evidence_summary`: 证据摘要
- `run_trace_summary`: 运行轨迹摘要

完整 `evidence_pack` 和 `raw_llm_response` **不会**暴露给前端。