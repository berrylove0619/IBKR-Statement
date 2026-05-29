# Structured Output Governance

## 为什么要做 StructuredOutputRuntime

每个 Agent 都需要从 LLM 输出中提取 JSON、校验 schema、处理格式错误。之前各 Agent 各自实现解析和修复逻辑，导致：
- 重复代码多
- 错误码不统一
- 格式失败被误报为 LLM 不可用
- 缺少统一监控

StructuredOutputRuntime 提供统一的 JSON 提取、Pydantic 校验、repair、fallback、trace、metadata 和错误码。

## 标准生命周期

```
prompt examples → LLM call → JSON extract → Pydantic validate → repair → fallback → trace / metadata / monitoring
```

1. **Prompt examples**: 每个 contract 必须包含 schema_hint 和至少一个正常样例 + 一个数据不足样例
2. **LLM call**: 通过 response_format={"type": "json_object"} 调用 LLM
3. **JSON extract**: 使用 `extract_json_object()` 统一提取
4. **Pydantic validate**: 使用 output_model 校验
5. **Repair**: 如果校验失败，通过 LLM 修复格式（不修复业务逻辑）
6. **Fallback**: 如果 repair 也失败，使用确定性兜底方案
7. **Trace / metadata / monitoring**: 记录完整处理链路和监控指标

## 新增 Agent 时必须做什么

1. 定义 Pydantic output model
2. 定义 StructuredOutputContract（在对应的 `*_structured_outputs.py` 中）
3. Prompt 必须包含 schema + 正常样例 + 数据不足样例
4. 接入 StructuredOutputRuntime（不要自己写 JSON parser）
5. 写 tests（至少覆盖成功、repair 成功、fallback 三种场景）
6. 加入 registry（`app/agents/structured_output/registry.py`）

## 错误码说明

| 错误码 | 含义 |
|--------|------|
| `LLM_OUTPUT_EMPTY` | LLM 输出为空 |
| `LLM_JSON_PARSE_FAILED` | JSON 解析失败 |
| `LLM_OUTPUT_NOT_OBJECT` | JSON 解析成功但不是 object |
| `LLM_SCHEMA_INVALID` | JSON object 不符合 Pydantic schema |
| `LLM_REPAIR_FAILED` | Repair LLM 调用失败 |
| `LLM_REPAIR_SCHEMA_INVALID` | Repair 后仍然不符合 schema |
| `STRUCTURED_FALLBACK_USED` | 使用了 fallback 兜底 |
| `LLM_CALL_FAILED` | LLM 调用本身失败 |
| `STRUCTURED_OUTPUT_UNKNOWN_ERROR` | 未知错误 |

## Repair 和 Fallback 区别

- **Repair** 是格式修复：通过 LLM 把不符合 schema 的 JSON 修复为符合 schema 的格式，不改变业务内容
- **Fallback** 是业务降级：当 repair 也失败时，使用确定性逻辑生成保守的业务结果

## 监控说明

通过 ES index `ibkr_structured_output_metrics_v1` 记录每次结构化输出处理结果。

### 指标

- **success_rate**: 最近 10 次滚动成功率
- **repair_rate**: 最近 10 次 repair 率
- **fallback_rate**: 最近 10 次 fallback 率

### 维度

- contract_name: 每个 contract 独立监控
- agent_name: 按 agent 聚合
- error_code: 按错误类型排查

## 禁止事项

1. 不要每个 Agent 自己写 JSON parser，统一使用 `app.agents.structured_output.extract_json_object`
2. 不要把 schema 校验失败说成 LLM 不可用
3. 不要把 raw Python 异常暴露给用户，使用友好中文提示
4. 不要保存完整 raw_response 到 ES 监控（最多 1000 字符 preview）
