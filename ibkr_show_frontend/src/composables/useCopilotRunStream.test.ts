import { describe, expect, it } from 'vitest'

import { parseCopilotEvent } from './useCopilotRunStream'

describe('parseCopilotEvent', () => {
  it('parses SSE event payloads', () => {
    const event = parseCopilotEvent(
      JSON.stringify({
        id: 'evt_1',
        run_id: 'run_1',
        session_id: 'session_1',
        event_type: 'planner_finished',
        seq: 3,
        created_at: '2026-01-01T00:00:00Z',
        payload: { action_type: 'call_tool' },
      }),
    )

    expect(event.seq).toBe(3)
    expect(event.event_type).toBe('planner_finished')
    expect(event.payload.action_type).toBe('call_tool')
  })

  it('parses terminal cancellation events', () => {
    const event = parseCopilotEvent(
      JSON.stringify({
        id: 'evt_cancel',
        run_id: 'run_1',
        session_id: 'session_1',
        event_type: 'run_cancelled',
        seq: 8,
        created_at: '2026-01-01T00:00:05Z',
        payload: { reason: 'User cancelled the run' },
      }),
    )

    expect(event.event_type).toBe('run_cancelled')
    expect(event.payload.reason).toContain('cancelled')
  })
})
