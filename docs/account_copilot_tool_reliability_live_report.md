# Account Copilot Tool Reliability Report

## Summary
- probe_run_id: `probe_run_b5d2f4355d38`
- started_at: `2026-05-23T13:58:03.756248+00:00`
- finished_at: `2026-05-23T13:58:04.375552+00:00`
- total_tools: `23`
- pass_count: `26`
- fail_count: `1`
- partial_count: `0`
- skipped_count: `5`
- avg_latency_ms: `5`
- p95_latency_ms: `10`

## Domain Summary
| Domain | Total | Pass | Fail | Partial | Skipped | Success Rate | P95 Latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| agent | 5 | 0 | 0 | 0 | 5 | 0.0% | 0 |
| ibkr | 18 | 18 | 0 | 0 | 0 | 100.0% | 10 |
| longbridge | 4 | 3 | 1 | 0 | 0 | 75.0% | 0 |
| skill | 5 | 5 | 0 | 0 | 0 | 100.0% | 0 |

## Tool Results
| Tool | Domain | Probe Type | Status | Latency | Error | Notes |
|---|---|---|---|---:|---|---|
| ibkr_get_account_overview | ibkr | schema | pass | 0 |  |  |
| ibkr_get_current_positions | ibkr | schema | pass | 0 |  |  |
| ibkr_get_symbol_position | ibkr | schema | pass | 0 |  |  |
| ibkr_get_symbol_trades | ibkr | schema | pass | 0 |  |  |
| ibkr_get_position_history | ibkr | schema | pass | 0 |  |  |
| ibkr_get_equity_curve | ibkr | schema | pass | 0 |  |  |
| ibkr_get_daily_attribution | ibkr | schema | pass | 0 |  |  |
| ibkr_get_risk_snapshot | ibkr | schema | pass | 0 |  |  |
| ibkr_get_cash_flow_summary | ibkr | schema | pass | 0 |  |  |
| longbridge_list_public_tools | longbridge | schema | pass | 0 |  |  |
| longbridge_get_public_tool_schema | longbridge | schema | pass | 0 |  |  |
| longbridge_call_public_tool | longbridge | schema | pass | 0 |  |  |
| trade_decision_entry_skill | skill | schema | pass | 0 |  |  |
| trade_decision_holding_skill | skill | schema | pass | 0 |  |  |
| trade_review_symbol_skill | skill | schema | pass | 0 |  |  |
| daily_position_review_skill | skill | schema | pass | 0 |  |  |
| risk_assessment_skill | skill | schema | pass | 0 |  |  |
| ibkr_get_account_overview | ibkr | invoke | pass | 0 |  |  |
| ibkr_get_current_positions | ibkr | invoke | pass | 6 |  |  |
| ibkr_get_symbol_position | ibkr | invoke | pass | 2 |  |  |
| ibkr_get_symbol_trades | ibkr | invoke | pass | 2 |  |  |
| ibkr_get_position_history | ibkr | invoke | pass | 2 |  |  |
| ibkr_get_equity_curve | ibkr | invoke | pass | 10 |  |  |
| ibkr_get_daily_attribution | ibkr | invoke | pass | 9 |  |  |
| ibkr_get_risk_snapshot | ibkr | invoke | pass | 5 |  |  |
| ibkr_get_cash_flow_summary | ibkr | invoke | pass | 6 |  |  |
| longbridge_catalog | longbridge | catalog | fail | 0 | LONGBRIDGE_ADAPTER_UNAVAILABLE |  |
| account_risk | agent | agent_eval | skipped | 0 |  |  |
| amd_public_market | agent | agent_eval | skipped | 0 |  |  |
| mu_entry_skill | agent | agent_eval | skipped | 0 |  |  |
| loss_attribution | agent | agent_eval | skipped | 0 |  |  |
| longbridge_degraded | agent | agent_eval | skipped | 0 |  |  |

## Longbridge Public Tools
| Tool | Probe | Status | Latency | Error |
|---|---|---|---:|---|
| longbridge_list_public_tools | schema | pass | 0 |  |
| longbridge_get_public_tool_schema | schema | pass | 0 |  |
| longbridge_call_public_tool | schema | pass | 0 |  |
| longbridge_catalog | catalog | fail | 0 | LONGBRIDGE_ADAPTER_UNAVAILABLE |

## Blocked Summary
- blocked_count: `0`

## Agent Eval
| Question | Expected Tools | Actual Tools | Forbidden Called | Evidence Based | Status |
|---|---|---|---|---|---|
| 我现在账户风险高不高？ | ibkr_get_risk_snapshot, ibkr_get_account_overview, ibkr_get_current_positions | n/a | False | None | skipped |
| AMD 最近为什么涨跌？ | longbridge_list_public_tools, longbridge_get_public_tool_schema, longbridge_call_public_tool | n/a | False | None | skipped |
| MU 现在适合建仓吗？ |  | n/a | False | None | skipped |
| 我最近亏损主要来自哪些股票？ | ibkr_get_daily_attribution, ibkr_get_current_positions, ibkr_get_equity_curve | n/a | False | None | skipped |
| 如果长桥不可用，请基于账户事实给有限结论。 | ibkr_get_account_overview, ibkr_get_risk_snapshot | n/a | False | None | skipped |

## Failures
- longbridge_catalog / catalog: LONGBRIDGE_ADAPTER_UNAVAILABLE Longbridge adapter is not configured
