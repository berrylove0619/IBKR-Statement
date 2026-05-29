import { describe, expect, it } from 'vitest'

import { applyGraphEvent } from '@/api/agentTasks'
import type { AgentGraphSnapshot } from '@/types/agentTasks'

function snapshot(): AgentGraphSnapshot {
  return {
    graph_version: 'trade_decision_graph_v1',
    nodes: [
      {
        id: 'build_account_facts',
        label: '账户事实',
        status: 'pending',
        started_at: null,
        finished_at: null,
        elapsed_ms: 0,
        fallback_used: false,
        fallback_reason: null,
        error: null,
        rounds_used: 0,
        tools_called: [],
        tool_calls: [],
        tool_call_count: 0,
        data_limitations_count: 0,
      },
    ],
    edges: [],
    current_nodes: [],
    status: 'pending',
    updated_seq: 0,
    started_at: null,
    updated_at: null,
  }
}

describe('applyGraphEvent', () => {
  it('marks a node running from SSE events', () => {
    const next = applyGraphEvent(snapshot(), {
      seq: 1,
      type: 'node_started',
      created_at: '2026-05-23T00:00:00Z',
      node_id: 'build_account_facts',
    })

    expect(next?.nodes[0].status).toBe('running')
    expect(next?.current_nodes).toEqual(['build_account_facts'])
    expect(next?.status).toBe('running')
  })

  it('merges a node finish event without replacing the full graph', () => {
    const running = applyGraphEvent(snapshot(), {
      seq: 1,
      type: 'node_started',
      created_at: '2026-05-23T00:00:00Z',
      node_id: 'build_account_facts',
    })
    const next = applyGraphEvent(running, {
      seq: 2,
      type: 'node_finished',
      created_at: '2026-05-23T00:00:01Z',
      node_id: 'build_account_facts',
      status: 'success',
      elapsed_ms: 850,
      tool_call_count: 2,
    })

    expect(next?.nodes[0]).toMatchObject({ status: 'success', elapsed_ms: 850, tool_call_count: 2 })
    expect(next?.current_nodes).toEqual([])
    expect(next?.status).toBe('success')
  })
})
