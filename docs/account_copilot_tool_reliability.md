# Account Copilot Tool Reliability Center

## Purpose

Account Copilot now has IBKR account tools, Longbridge MCP public-market meta tools, Skills, ReAct, SSE, Memory, and HITL. The Tool Reliability Center is a sidecar reliability layer that measures whether those capabilities are actually available and whether tool usage remains safe.

It does not change the Account Copilot planner/runtime flow and it never adds trading or write capabilities.

## Three Probe Layers

1. Fake Test
   Validates wrappers, schemas, safety boundaries, envelope shape, and failure handling without external services.

2. Live Probe
   Calls configured read-only tools and records catalog availability, schema completeness, safe argument construction, invocation status, latency, error code, empty results, and data limitations.

3. Agent Eval
   Uses fixed questions to evaluate whether Account Copilot should choose the right tool family, avoid forbidden tools, degrade when public data is unavailable, and ground final answers in evidence.

## Probe Result Index

`ES_COPILOT_TOOL_PROBE_INDEX`

Default:

`ibkr_copilot_tool_probe_results_v1`

Document fields:

- `id`
- `probe_run_id`
- `tool_name`
- `tool_domain`: `ibkr`, `longbridge`, `skill`, or `agent`
- `category`
- `probe_type`: `catalog`, `schema`, `invoke`, or `agent_eval`
- `status`: `pass`, `fail`, `partial`, or `skipped`
- `ok`
- `latency_ms`
- `error_code`
- `error_message`
- `arguments_preview`
- `data_empty`
- `data_size`
- `data_limitations`
- `created_at`
- `metadata`

## Longbridge Safety

Longbridge probing only uses `LongbridgeMCPToolAdapter`.

The probe:

- calls `get_tool_catalog(force_refresh=True)`
- only inspects tools classified as `public_market_readonly`
- only invokes tools with `allowed=true`
- does not output blocked/private/write schemas
- reports blocked count only
- skips tools whose required parameters cannot be constructed safely
- blocks account/order/trade/token/password/private parameters

## Safe Argument Construction

Default public-market probe values:

- `symbol`, `ticker`, `security`, `code`: `AMD.US`
- `keyword`, `query`: `AMD`
- `market`: `US`
- `period`: `day`
- `start_date` / `end_date`: recent 30 days
- `count` / `limit`: `5`
- `language`: `zh-CN`

If required arguments are unknown, the result is marked `skipped` with `SKIPPED_UNSUPPORTED_ARGS`.

## API

Authenticated debug endpoints:

- `GET /api/agent/account-copilot/tool-reliability/latest`
- `GET /api/agent/account-copilot/tool-reliability/results`
- `POST /api/agent/account-copilot/tool-reliability/probe`

`POST /probe` defaults to registry/schema checks. Live calls require explicit flags:

```json
{
  "include_live": true,
  "include_longbridge": true,
  "include_ibkr": true,
  "include_agent_eval": true
}
```

## Script

Local dry-run:

```bash
python scripts/account_copilot_tool_reliability_probe.py --local --report-path docs/account_copilot_tool_reliability_report.md
```

Online HTTP probe:

```bash
ACCOUNT_COPILOT_BASE_URL=https://your-domain.example \
ACCOUNT_COPILOT_USERNAME=... \
ACCOUNT_COPILOT_PASSWORD=... \
python scripts/account_copilot_tool_reliability_probe.py \
  --include-longbridge-live \
  --include-ibkr-live \
  --include-agent-eval \
  --report-path docs/account_copilot_tool_reliability_report.md
```

The script also supports `ACCOUNT_COPILOT_SESSION_COOKIE`. It does not print credentials.

## Report

Generated report:

`docs/account_copilot_tool_reliability_report.md`

The report includes:

- overall pass/fail/partial/skipped counts
- average and p95 latency
- domain summary
- individual tool results
- Longbridge public tool status
- blocked count summary
- Agent Eval expectations
- sanitized failures and suggested follow-up targets

## Security

- No trading write tools are invoked.
- No raw ES query is exposed.
- Longbridge private/account/write tools are not called.
- Sensitive keys such as token, API key, cookie, password, authorization, and secret are redacted.
- Single tool failures are isolated and do not fail the entire probe run.

## Next Step

Build a backend Tool Health page that reads the probe index and shows recent success rate, latency trend, Longbridge public catalog status, and failing tools.
