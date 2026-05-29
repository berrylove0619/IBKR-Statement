<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'
import { TooltipComponent } from 'echarts/components'
import type { EChartsType } from 'echarts/core'
import type { GraphSeriesOption } from 'echarts'
import { applyGraphEvent, buildAgentTaskEventsUrl, fetchAgentTaskGraph } from '@/api/agentTasks'
import type { AgentGraphNode, AgentGraphNodeStatus, AgentGraphSnapshot, AgentTask } from '@/types/agentTasks'

echarts.use([GraphChart, CanvasRenderer, TooltipComponent])

const props = defineProps<{
  task: AgentTask
  expanded: boolean
}>()

const emit = defineEmits<{
  (event: 'snapshot', taskId: string, snapshot: AgentGraphSnapshot | null): void
}>()

const chartEl = ref<HTMLDivElement | null>(null)
const snapshot = ref<AgentGraphSnapshot | null>(props.task.graph_snapshot)
const selectedNodeId = ref<string | null>(null)
const connectionStatus = ref<'idle' | 'live' | 'polling' | 'done' | 'error'>('idle')

let chart: EChartsType | null = null
let source: EventSource | null = null
let pollTimer: number | undefined
let pendingRender = false
let resizeObserver: ResizeObserver | null = null

const selectedNode = computed(() => snapshot.value?.nodes.find((node) => node.id === selectedNodeId.value) || snapshot.value?.nodes.find((node) => node.status === 'running') || snapshot.value?.nodes[0] || null)
const selectedNodeToolSteps = computed(() => {
  const node = selectedNode.value
  if (!node) return []
  if (node.tool_calls?.length) return node.tool_calls
  return (node.tools_called || []).map((name) => ({ tool_name: name, success: null, empty_result: null, error_type: null }))
})
const progressLabel = computed(() => {
  const nodes = snapshot.value?.nodes || []
  const done = nodes.filter((node) => ['success', 'failed', 'fallback', 'skipped'].includes(node.status)).length
  return nodes.length ? `${done}/${nodes.length}` : '--'
})

watch(
  () => props.task.graph_snapshot,
  (next) => {
    if (next && (!snapshot.value || next.updated_seq >= snapshot.value.updated_seq)) {
      snapshot.value = next
      scheduleRender()
    }
  },
)

watch(
  () => props.expanded,
  (expanded) => {
    if (expanded) {
      void openGraph()
    } else {
      closeLiveUpdates()
    }
  },
)

onMounted(() => {
  if (props.expanded) void openGraph()
})

onBeforeUnmount(() => {
  closeLiveUpdates()
  resizeObserver?.disconnect()
  chart?.dispose()
})

async function openGraph(): Promise<void> {
  const response = await fetchAgentTaskGraph(props.task.id)
  snapshot.value = response.graph_snapshot
  emit('snapshot', props.task.id, snapshot.value)
  await nextTick()
  ensureChart()
  scheduleRender()
  if (props.task.status === 'completed' || props.task.status === 'failed') {
    connectionStatus.value = 'done'
    return
  }
  startSse()
}

function ensureChart(): void {
  if (!chartEl.value || chart) return
  const instance = echarts.init(chartEl.value, undefined, { renderer: 'canvas' })
  chart = instance
  resizeObserver = new ResizeObserver(() => chart?.resize())
  resizeObserver.observe(chartEl.value)
  instance.on('click', (params) => {
    if (params.dataType === 'node' && typeof params.name === 'string') {
      selectedNodeId.value = params.name
    }
  })
}

function startSse(): void {
  closeLiveUpdates()
  if (typeof EventSource === 'undefined') {
    startPolling()
    return
  }
  connectionStatus.value = 'live'
  source = new EventSource(buildAgentTaskEventsUrl(props.task.id, snapshot.value?.updated_seq || props.task.updated_seq || 0), { withCredentials: true })
  source.addEventListener('graph_event', (event) => {
    const parsed = JSON.parse((event as MessageEvent).data)
    snapshot.value = applyGraphEvent(snapshot.value, parsed)
    emit('snapshot', props.task.id, snapshot.value)
    scheduleRender()
    if (parsed.type === 'graph_synced' || parsed.type === 'graph_failed') {
      connectionStatus.value = parsed.type === 'graph_failed' ? 'error' : 'done'
    }
  })
  source.onerror = () => {
    closeLiveUpdates()
    startPolling()
  }
}

function startPolling(): void {
  connectionStatus.value = 'polling'
  pollTimer = window.setInterval(async () => {
    const response = await fetchAgentTaskGraph(props.task.id)
    snapshot.value = response.graph_snapshot
    emit('snapshot', props.task.id, snapshot.value)
    scheduleRender()
    if (response.status === 'completed' || response.status === 'failed') {
      closeLiveUpdates()
      connectionStatus.value = 'done'
    }
  }, 1800)
}

function closeLiveUpdates(): void {
  source?.close()
  source = null
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
}

function scheduleRender(): void {
  if (pendingRender) return
  pendingRender = true
  window.requestAnimationFrame(() => {
    pendingRender = false
    renderChart()
  })
}

function renderChart(): void {
  ensureChart()
  if (!chart || !snapshot.value) return
  const layout = buildFixedLayout(snapshot.value)
  const series: GraphSeriesOption = {
    type: 'graph',
    layout: 'none',
    roam: false,
    symbolSize: 46,
    label: { show: true, color: '#dbeafe', fontSize: 11, formatter: (params) => String((params.data as { nodeLabel?: string }).nodeLabel || params.name) },
    edgeSymbol: ['none', 'arrow'],
    edgeSymbolSize: 8,
    lineStyle: { color: 'rgba(148, 163, 184, 0.5)', width: 1.5, curveness: 0.06 },
    data: layout.nodes,
    links: layout.links,
    animation: false,
  }
  chart.setOption(
    {
      tooltip: {
        trigger: 'item',
        formatter: (params: { dataType?: string; data?: unknown }) => {
          if (params.dataType !== 'node') return ''
          const data = params.data as AgentGraphNode & { nodeLabel?: string; value?: unknown }
          return `${data.nodeLabel || data.id}<br/>状态: ${statusLabel(data.status)}<br/>耗时: ${data.elapsed_ms || 0}ms<br/>工具: ${data.tool_call_count || 0}`
        },
      },
      series: [series],
    },
    { notMerge: false, lazyUpdate: true },
  )
}

function buildFixedLayout(graph: AgentGraphSnapshot) {
  const incoming = new Map<string, number>()
  graph.nodes.forEach((node) => incoming.set(node.id, 0))
  graph.edges.forEach((edge) => incoming.set(edge.target, (incoming.get(edge.target) || 0) + 1))
  const levels = new Map<string, number>()
  const queue = graph.nodes.filter((node) => (incoming.get(node.id) || 0) === 0).map((node) => node.id)
  queue.forEach((id) => levels.set(id, 0))
  while (queue.length) {
    const id = queue.shift()!
    const level = levels.get(id) || 0
    graph.edges.filter((edge) => edge.source === id).forEach((edge) => {
      const nextLevel = Math.max(levels.get(edge.target) || 0, level + 1)
      levels.set(edge.target, nextLevel)
      queue.push(edge.target)
    })
  }
  const grouped = new Map<number, AgentGraphNode[]>()
  graph.nodes.forEach((node) => {
    const level = levels.get(node.id) || 0
    grouped.set(level, [...(grouped.get(level) || []), node])
  })
  const nodes = graph.nodes.map((node) => {
    const level = levels.get(node.id) || 0
    const peers = grouped.get(level) || [node]
    const index = peers.findIndex((item) => item.id === node.id)
    return {
      name: node.id,
      id: node.id,
      nodeLabel: node.label,
      status: node.status,
      started_at: node.started_at,
      finished_at: node.finished_at,
      elapsed_ms: node.elapsed_ms,
      fallback_used: node.fallback_used,
      fallback_reason: node.fallback_reason,
      error: node.error,
      rounds_used: node.rounds_used,
      tools_called: node.tools_called,
      tool_calls: node.tool_calls,
      tool_call_count: node.tool_call_count,
      data_limitations_count: node.data_limitations_count,
      x: 80 + level * 150,
      y: 60 + index * 86 + Math.max(0, 2 - peers.length) * 32,
      itemStyle: { color: statusColor(node.status), borderColor: node.id === selectedNodeId.value ? '#facc15' : 'rgba(255,255,255,0.18)', borderWidth: node.id === selectedNodeId.value ? 3 : 1 },
    }
  })
  return {
    nodes,
    links: graph.edges.map((edge) => ({ source: edge.source, target: edge.target })),
  }
}

function statusColor(status: AgentGraphNodeStatus): string {
  if (status === 'running') return '#38bdf8'
  if (status === 'success') return '#34d399'
  if (status === 'failed') return '#fb7185'
  if (status === 'fallback') return '#f59e0b'
  if (status === 'skipped') return '#64748b'
  return '#334155'
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: '等待',
    running: '执行中',
    success: '成功',
    failed: '失败',
    fallback: '降级',
    skipped: '跳过',
  }
  return labels[status] || status
}
</script>

<template>
  <div class="agent-task-graph">
    <div class="agent-task-graph__header">
      <span>LangGraph 执行图</span>
      <small>{{ progressLabel }} · {{ connectionStatus }}</small>
    </div>
    <div v-if="snapshot" class="agent-task-graph__body">
      <div ref="chartEl" class="agent-task-graph__chart"></div>
      <aside class="agent-task-graph__detail">
        <template v-if="selectedNode">
          <strong>{{ selectedNode.label }}</strong>
          <span class="agent-task-graph__status" :class="`agent-task-graph__status--${selectedNode.status}`">{{ statusLabel(selectedNode.status) }}</span>
          <dl>
            <dt>耗时</dt>
            <dd>{{ selectedNode.elapsed_ms || 0 }}ms</dd>
            <dt>LLM轮次</dt>
            <dd>{{ selectedNode.rounds_used || 0 }}</dd>
            <dt>工具调用</dt>
            <dd>{{ selectedNode.tool_call_count || 0 }}</dd>
            <dt>数据限制</dt>
            <dd>{{ selectedNode.data_limitations_count || 0 }}</dd>
          </dl>
          <div v-if="selectedNodeToolSteps.length" class="agent-task-graph__subflow">
            <span class="agent-task-graph__subflow-title">节点内部执行</span>
            <div v-for="(tool, index) in selectedNodeToolSteps" :key="`${tool.tool_name}-${index}`" class="agent-task-graph__tool">
              <span class="agent-task-graph__tool-dot" :class="tool.success === false ? 'is-error' : tool.empty_result ? 'is-empty' : 'is-ok'"></span>
              <span>{{ tool.tool_name }}</span>
              <small v-if="tool.empty_result">empty</small>
              <small v-else-if="tool.success === false">{{ tool.error_type || 'failed' }}</small>
              <small v-else>ok</small>
            </div>
          </div>
          <p v-if="selectedNode.error" class="agent-task-graph__error">{{ selectedNode.error }}</p>
          <p v-else-if="selectedNode.fallback_reason" class="agent-task-graph__warning">{{ selectedNode.fallback_reason }}</p>
        </template>
      </aside>
    </div>
    <div v-else class="agent-task-graph__empty">该任务没有 LangGraph 进度快照。</div>
  </div>
</template>

<style scoped>
.agent-task-graph {
  margin-top: 12px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.42);
  padding: 12px;
}

.agent-task-graph__header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: #e2e8f0;
  font-weight: 700;
}

.agent-task-graph__header small {
  color: #94a3b8;
  font-weight: 500;
}

.agent-task-graph__body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 220px;
  gap: 12px;
  min-height: 320px;
}

.agent-task-graph__chart {
  min-height: 320px;
}

.agent-task-graph__detail {
  border-left: 1px solid rgba(148, 163, 184, 0.16);
  padding: 12px 0 12px 12px;
  color: #cbd5e1;
}

.agent-task-graph__detail strong,
.agent-task-graph__detail span,
.agent-task-graph__detail dd,
.agent-task-graph__detail dt {
  display: block;
}

.agent-task-graph__detail dl {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 8px 10px;
  margin: 12px 0;
}

.agent-task-graph__detail dt {
  color: #94a3b8;
}

.agent-task-graph__status {
  margin-top: 8px;
  font-size: 0.8rem;
}

.agent-task-graph__status--success { color: #34d399; }
.agent-task-graph__status--running { color: #38bdf8; }
.agent-task-graph__status--failed { color: #fb7185; }
.agent-task-graph__status--fallback { color: #f59e0b; }

.agent-task-graph__error,
.agent-task-graph__warning {
  margin: 10px 0 0;
  overflow-wrap: anywhere;
  font-size: 0.82rem;
}

.agent-task-graph__error { color: #fb7185; }
.agent-task-graph__warning { color: #fbbf24; }

.agent-task-graph__subflow {
  display: grid;
  gap: 7px;
  margin-top: 12px;
}

.agent-task-graph__subflow-title {
  color: #94a3b8;
  font-size: 0.78rem;
}

.agent-task-graph__tool {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  min-height: 28px;
  padding: 6px 8px;
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.58);
  color: #dbeafe;
  font-size: 0.8rem;
}

.agent-task-graph__tool span:nth-child(2) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-task-graph__tool small {
  color: #94a3b8;
}

.agent-task-graph__tool-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #34d399;
}

.agent-task-graph__tool-dot.is-error {
  background: #fb7185;
}

.agent-task-graph__tool-dot.is-empty {
  background: #f59e0b;
}

.agent-task-graph__empty {
  padding: 16px 0 4px;
  color: #94a3b8;
}

@media (max-width: 760px) {
  .agent-task-graph__body {
    grid-template-columns: 1fr;
  }

  .agent-task-graph__detail {
    border-left: 0;
    border-top: 1px solid rgba(148, 163, 184, 0.16);
    padding: 12px 0 0;
  }
}
</style>
