# Account Copilot Tool Reliability Report

## Summary
- probe_run_id: `probe_run_d03ce871b636`
- started_at: `2026-05-23T13:29:45.940310+00:00`
- finished_at: `2026-05-23T13:29:46.196348+00:00`
- total_tools: `17`
- pass_count: `17`
- fail_count: `0`
- partial_count: `0`
- skipped_count: `0`
- avg_latency_ms: `0`
- p95_latency_ms: `0`

## Domain Summary
| Domain | Total | Pass | Fail | Partial | Skipped | Success Rate | P95 Latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| ibkr | 9 | 9 | 0 | 0 | 0 | 100.0% | 0 |
| longbridge | 3 | 3 | 0 | 0 | 0 | 100.0% | 0 |
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

## Longbridge Public Tools
| Tool | Probe | Status | Latency | Error |
|---|---|---|---:|---|
| longbridge_list_public_tools | schema | pass | 0 |  |
| longbridge_get_public_tool_schema | schema | pass | 0 |  |
| longbridge_call_public_tool | schema | pass | 0 |  |

## Blocked Summary
- blocked_count: `0`

## Agent Eval
| Question | Expected Tools | Actual Tools | Forbidden Called | Evidence Based | Status |
|---|---|---|---|---|---|

## Failures
No failures.
