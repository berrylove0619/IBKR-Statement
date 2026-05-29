# Account Copilot Live Goal Report

## Environment

- base_url: `https://your-domain.example`
- started_at: `2026-05-23T14:15:53.742551+00:00`
- finished_at: `2026-05-23T14:26:06.990486+00:00`
- demo_mode: `False`
- health summary:

```json
{
  "ok": true,
  "checks": {
    "llm": {
      "ok": true,
      "message": "configured"
    },
    "es": {
      "ok": true,
      "message": "reachable"
    },
    "ibkr_tools": {
      "ok": true,
      "count": 9
    },
    "longbridge_meta_tools": {
      "ok": true,
      "count": 3
    },
    "skills": {
      "ok": true,
      "count": 5
    },
    "event_bus": {
      "ok": true
    },
    "memory_index": {
      "ok": true
    }
  },
  "settings": {
    "max_react_rounds": 8,
    "run_timeout_seconds": 180,
    "max_event_payload_chars": 6000,
    "demo_mode": false
  }
}
```

## Summary

PASS=10 PARTIAL=2 FAIL=0 SKIPPED=1

| Case | Name | Status | Session | Run | Notes |
|---|---|---|---|---|---|
| A | 健康检查 | PASS | `` | `` | demo_mode=False; ok=True |
| B | 多会话 | PASS | `502406c3-8f89-48d0-995b-6bfea74ddb35` | `` |  |
| C | IBKR 账户事实问答 | PASS | `502406c3-8f89-48d0-995b-6bfea74ddb35` | `ffdfd71e-086c-48fd-b304-fc853b60fd8c` | run_status=completed; event_count=15 |
| D | Longbridge 渐进式披露 | PARTIAL | `502406c3-8f89-48d0-995b-6bfea74ddb35` | `e941cbff-cd8b-4b33-8ad7-9715352b2f8c` | run_status=completed; event_count=14; longbridge progressive flow missing: longbridge_call_public_tool, longbridge_get_public_tool_schema |
| E | Skill 申请 + 同意 | PARTIAL | `165d129b-ce7d-41e0-b380-0b072e6c18d4` | `b0260651-1a6f-41d5-8936-038af2309115` | run_status=awaiting_approval; event_count=8; approval_http=504; polling run for backend completion; run_status=completed; event_count=13; approval endpoint returned an HTTP error but backend completed and executed the ap |
| F | Skill 申请 + 拒绝 | PASS | `e758adab-de68-4aa4-8d55-6112aef47513` | `41e84baf-e420-4f14-8655-27bfe57efe22` | run_status=awaiting_approval; event_count=8; run_status=completed; event_count=11 |
| G | SSE after_seq 恢复 | PASS | `` | `ffdfd71e-086c-48fd-b304-fc853b60fd8c` | last_seq=2; recovered=12 |
| H | 取消运行 | PASS | `0c64307b-b1ea-4d08-ab65-293f412a084e` | `d593ec1d-817a-4993-a8e8-8f2c0b1d8057` | run_status=cancelled; event_count=4 |
| I | active run 防并发 | PASS | `a56e498b-3812-4a36-92d4-a668394d216e` | `d0c62ded-7869-4ccf-81b0-2ccd95d09cf3` | run_status=awaiting_approval; event_count=8 |
| J | Memory | PASS | `ca767e69-9978-453c-8094-bbdf9d3b7adb` | `` | memory_count=1; message_count=12 |
| K | 历史恢复 | PASS | `502406c3-8f89-48d0-995b-6bfea74ddb35` | `ffdfd71e-086c-48fd-b304-fc853b60fd8c` |  |
| L | approval expired | SKIPPED | `` | `` | no pending approval run available |
| M | event sanitizer | PASS | `` | `` | scanned_events=56 |

## Tool Reliability Summary

- total_tools: `23`
- pass_count: `26`
- fail_count: `1`
- partial_count: `0`
- skipped_count: `5`
- longbridge_public_tool_count: `3`
- ibkr_success_rate: `100.0%`
- longbridge_success_rate: `75.0%`
- p95_latency_ms: `10`

## Detailed Cases

### Case A: 健康检查

- Status: **PASS**
- session_id: ``
- run_id: ``
- event_count: 0
- tool_calls: ``
- observations: 0
- final_answer_preview: 
- notes: demo_mode=False; ok=True
- issues: 

### Case B: 多会话

- Status: **PASS**
- session_id: `502406c3-8f89-48d0-995b-6bfea74ddb35`
- run_id: ``
- event_count: 0
- tool_calls: ``
- observations: 0
- final_answer_preview: 
- notes: 
- issues: 

### Case C: IBKR 账户事实问答

- Status: **PASS**
- session_id: `502406c3-8f89-48d0-995b-6bfea74ddb35`
- run_id: `ffdfd71e-086c-48fd-b304-fc853b60fd8c`
- event_count: 15
- tool_calls: `ibkr_get_risk_snapshot`
- observations: 1
- final_answer_preview: 根据刚获取的 IBKR 账户风险快照，您的账户当前风险水平**中等偏高**，主要关注点是集中度风险，尚无保证金压力。 **关键风险指标：** - 净清算价值：[amount] - 现金占比：8.57%（[amount]），可部署流动性充足 - 保证金使用率：0%，无杠杆，无追加保证金风险 - 持仓数量：12 只，有一定分散 **集中度分布：** - 最大单只持仓 AMD 占账户 29.7% - 前 3 大持仓（AMD + MSFT + META）合计占 58.26% - 前 5 大持仓合计占 76.37% **风险解读：** 集中度偏高，尤其是 AMD 接近 30% 的权重，单一股票的大幅波动会对整体账户影响显著。不过，持仓以大型科
- notes: run_status=completed; event_count=15
- issues: 

### Case D: Longbridge 渐进式披露

- Status: **PARTIAL**
- session_id: `502406c3-8f89-48d0-995b-6bfea74ddb35`
- run_id: `e941cbff-cd8b-4b33-8ad7-9715352b2f8c`
- event_count: 14
- tool_calls: `longbridge_list_public_tools`
- observations: 1
- final_answer_preview: 很抱歉，当前长桥公开市场工具暂时不可用（MCP 工具列表返回为空），无法为您查询 AMD 的近期行情、新闻或涨跌原因。建议稍后重试，或者如果您希望查看您账户中 AMD 的持仓、历史交易或权重情况，我可以为您查询 IBKR 账户数据。请问需要我进行这部分查询吗？
- notes: run_status=completed; event_count=14
- issues: longbridge progressive flow missing: longbridge_call_public_tool, longbridge_get_public_tool_schema

### Case E: Skill 申请 + 同意

- Status: **PARTIAL**
- session_id: `165d129b-ce7d-41e0-b380-0b072e6c18d4`
- run_id: `b0260651-1a6f-41d5-8936-038af2309115`
- event_count: 13
- tool_calls: ``
- observations: 1
- final_answer_preview: Skill 已执行，但当前 LLM 不可用，以下是 Skill 的摘要结果：object keys=['id', 'symbol', 'decision_summary', 'action', 'confidence', 'overall_score', 'rating', 'key_reasons']
- notes: run_status=awaiting_approval; event_count=8; approval_http=504; polling run for backend completion; run_status=completed; event_count=13
- issues: approval endpoint returned an HTTP error but backend completed and executed the approved skill

### Case F: Skill 申请 + 拒绝

- Status: **PASS**
- session_id: `e758adab-de68-4aa4-8d55-6112aef47513`
- run_id: `41e84baf-e420-4f14-8655-27bfe57efe22`
- event_count: 11
- tool_calls: ``
- observations: 0
- final_answer_preview: 已取消调用该 Skill。由于该分析需要该 Skill 才能完整完成，我不会编造结论。你可以改问更具体的账户事实问题。
- notes: run_status=awaiting_approval; event_count=8; run_status=completed; event_count=11
- issues: 

### Case G: SSE after_seq 恢复

- Status: **PASS**
- session_id: ``
- run_id: `ffdfd71e-086c-48fd-b304-fc853b60fd8c`
- event_count: 12
- tool_calls: ``
- observations: 0
- final_answer_preview: 
- notes: last_seq=2; recovered=12
- issues: 

### Case H: 取消运行

- Status: **PASS**
- session_id: `0c64307b-b1ea-4d08-ab65-293f412a084e`
- run_id: `d593ec1d-817a-4993-a8e8-8f2c0b1d8057`
- event_count: 4
- tool_calls: ``
- observations: 0
- final_answer_preview: 
- notes: run_status=cancelled; event_count=4
- issues: 

### Case I: active run 防并发

- Status: **PASS**
- session_id: `a56e498b-3812-4a36-92d4-a668394d216e`
- run_id: `d0c62ded-7869-4ccf-81b0-2ccd95d09cf3`
- event_count: 8
- tool_calls: ``
- observations: 0
- final_answer_preview: 已为您申请账户风险评估技能，等待审批后执行。
- notes: run_status=awaiting_approval; event_count=8
- issues: 

### Case J: Memory

- Status: **PASS**
- session_id: `ca767e69-9978-453c-8094-bbdf9d3b7adb`
- run_id: ``
- event_count: 0
- tool_calls: ``
- observations: 0
- final_answer_preview: 
- notes: memory_count=1; message_count=12
- issues: 

### Case K: 历史恢复

- Status: **PASS**
- session_id: `502406c3-8f89-48d0-995b-6bfea74ddb35`
- run_id: `ffdfd71e-086c-48fd-b304-fc853b60fd8c`
- event_count: 0
- tool_calls: ``
- observations: 0
- final_answer_preview: 
- notes: 
- issues: 

### Case L: approval expired

- Status: **SKIPPED**
- session_id: ``
- run_id: ``
- event_count: 0
- tool_calls: ``
- observations: 0
- final_answer_preview: 
- notes: 
- issues: no pending approval run available

### Case M: event sanitizer

- Status: **PASS**
- session_id: ``
- run_id: ``
- event_count: 56
- tool_calls: ``
- observations: 0
- final_answer_preview: 
- notes: scanned_events=56
- issues: 

## Feature Coverage Matrix

| Feature | Status |
|---|---|
| 多会话 | PASS |
| IBKR | PASS |
| Longbridge | PARTIAL |
| ReAct | PASS |
| SSE | PASS |
| Skill同意 | PARTIAL |
| Skill拒绝 | PASS |
| Memory | PASS |
| Cancel | PASS |
| 防并发 | PASS |
| Expired | SKIPPED |
| Sanitizer | PASS |

## Bugs Found

- **Tool Reliability live probe failed** (blocker): 1 reliability probe result(s) failed. Expected Longbridge catalog and read-only tools to be available; actual probe reported a live tool reliability failure. Suggested fix: inspect Longbridge MCP OAuth/client configuration and rerun the reliability probe.

## Final Verdict

- recommended_for_release: `no`
- blocker_exists: `True`
- longbridge_mcp_available: `False`
- tool_reliability_pass_rate_acceptable: `False`
- sensitive_leak_found: `False`

## Next Actions

- Review PARTIAL/SKIPPED cases and decide whether staging-specific settings are needed.
- Re-run this script after any Account Copilot runtime, tool, Skill, memory, or SSE change.
