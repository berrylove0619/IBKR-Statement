import { computed, onUnmounted, ref } from 'vue'

import { API_BASE_URL } from '@/api/http'
import type { CopilotEvent } from '@/types/accountCopilot'

export function parseCopilotEvent(raw: string): CopilotEvent {
  return JSON.parse(raw) as CopilotEvent
}

export function useCopilotRunStream() {
  const source = ref<EventSource | null>(null)
  const connected = ref(false)
  const events = ref<CopilotEvent[]>([])
  const lastSeq = ref(0)
  const error = ref('')
  const reconnecting = ref(false)
  const reconnectAttempts = ref(0)
  const terminal = ref(false)
  let activeRunId = ''
  let autoReconnect = true
  let reconnectTimer: number | null = null
  let manualDisconnect = false

  const terminalEvents = new Set(['run_completed', 'run_failed', 'run_cancelled'])
  const eventTypes = [
    'run_started',
    'planner_started',
    'planner_finished',
    'planner_repair_started',
    'planner_repair_finished',
    'action_selected',
    'tool_started',
    'tool_finished',
    'tool_failed',
    'observation_created',
    'skill_approval_requested',
    'skill_approval_approved',
    'skill_approval_rejected',
    'skill_started',
    'skill_finished',
    'skill_failed',
    'final_answer',
    'memory_update_started',
    'memory_update_finished',
    'memory_update_failed',
    'run_completed',
    'run_failed',
    'run_cancelled',
    'heartbeat',
  ]

  function disconnect(): void {
    manualDisconnect = true
    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    source.value?.close()
    source.value = null
    connected.value = false
    reconnecting.value = false
  }

  function connect(runId: string, afterSeq = 0, options: { autoReconnect?: boolean } = {}): void {
    disconnect()
    manualDisconnect = false
    activeRunId = runId
    autoReconnect = options.autoReconnect ?? true
    events.value = []
    lastSeq.value = afterSeq
    error.value = ''
    terminal.value = false
    reconnectAttempts.value = 0
    openStream(runId, afterSeq)
  }

  function openStream(runId: string, afterSeq: number): void {
    const url = `${API_BASE_URL}/api/agent/account-copilot/runs/${encodeURIComponent(runId)}/events?after_seq=${afterSeq}`
    const eventSource = new EventSource(url, { withCredentials: true })
    source.value = eventSource
    connected.value = true
    reconnecting.value = false
    error.value = ''

    eventSource.onmessage = (event) => appendEvent(event.data)
    eventSource.onerror = () => {
      source.value?.close()
      source.value = null
      connected.value = false
      if (manualDisconnect || terminal.value || !autoReconnect) {
        if (!terminal.value) error.value = '实时连接已断开，可刷新获取最终结果'
        return
      }
      scheduleReconnect()
    }

    eventTypes.forEach((type) => {
      eventSource.addEventListener(type, (event) => appendEvent((event as MessageEvent).data))
    })
  }

  function scheduleReconnect(): void {
    if (!activeRunId || reconnectAttempts.value >= 5) {
      reconnecting.value = false
      error.value = '实时连接已断开，可刷新获取最终结果'
      return
    }
    const delays = [1000, 2000, 5000, 10000, 10000]
    const delay = delays[Math.min(reconnectAttempts.value, delays.length - 1)]
    reconnectAttempts.value += 1
    reconnecting.value = true
    error.value = '连接中断，正在重连...'
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null
      if (!manualDisconnect && !terminal.value) {
        openStream(activeRunId, lastSeq.value)
      }
    }, delay)
  }

  function appendEvent(raw: string): void {
    try {
      const item = parseCopilotEvent(raw)
      if (item.event_type !== 'heartbeat') {
        events.value = [...events.value, item]
      }
      lastSeq.value = Math.max(lastSeq.value, Number(item.seq || 0))
      if (terminalEvents.has(item.event_type)) {
        terminal.value = true
        disconnect()
      }
    } catch (eventError) {
      error.value = eventError instanceof Error ? eventError.message : 'SSE 数据解析失败'
    }
  }

  onUnmounted(disconnect)

  return {
    connect,
    disconnect,
    connected: computed(() => connected.value),
    events,
    lastSeq,
    error,
    reconnecting,
    reconnectAttempts,
    terminal,
  }
}
