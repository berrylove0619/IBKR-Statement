<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, ScatterChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsType } from 'echarts/core'
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import {
  getAgentMonitoringOverview,
  getAgentRecentLlmCalls,
  getAgentRecentToolCalls,
  getStructuredOutputRecent,
  getToolReliabilityLatest,
  runToolReliabilityProbe,
} from '@/api/accountCopilot'
import ErrorBlock from '@/components/ErrorBlock.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import type {
  AgentMonitoringOverviewResponse,
  AgentMonitoringStatusSummary,
  AgentRecentLlmCall,
  AgentRecentToolCall,
  AgentStructuredOutputEvent,
  CopilotToolProbeResult,
  CopilotToolReliabilityLatestResponse,
  CopilotToolReliabilityProbeResponse,
} from '@/types/accountCopilot'

echarts.use([LineChart, BarChart, ScatterChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

type ProbeKind = 'mcp' | 'ibkr'
type MetricSource = 'runtime' | 'probe' | 'all'
type CallTypeFilter = 'all' | 'mcp' | 'ibkr' | 'llm'

const agentOptions = [
  { label: '全部 Agent', value: '' },
  { label: 'Trade Decision', value: 'trade_decision' },
  { label: 'Account Copilot', value: 'account_copilot' },
  { label: 'Trade Review', value: 'trade_review' },
  { label: 'Daily Review', value: 'daily_review' },
]
const sourceOptions: { label: string; value: MetricSource }[] = [
  { label: 'Runtime', value: 'runtime' },
  { label: 'Probe', value: 'probe' },
  { label: 'All', value: 'all' },
]
const typeOptions: { label: string; value: CallTypeFilter }[] = [
  { label: '全部', value: 'all' },
  { label: 'MCP', value: 'mcp' },
  { label: 'IBKR', value: 'ibkr' },
  { label: 'LLM', value: 'llm' },
]
const limitOptions = [50, 100, 200, 500]

const SENSITIVE_KEYWORDS = ['api_key', 'apikey', 'cookie', 'authorization', 'secret', 'password', 'access_token', 'refresh_token']
const SENSITIVE_VALUE_PATTERN = /(bearer\s+[a-z0-9._~+/-]+|sk-[a-z0-9_-]+|api[_-]?key\s*[:=]\s*[^,\s]+)/gi

const loading = ref(true)
const errorMessage = ref('')
const probeMessage = ref('')
const probing = ref<ProbeKind | null>(null)
const selectedAgent = ref('')
const selectedSource = ref<MetricSource>('runtime')
const selectedType = ref<CallTypeFilter>('all')
const selectedLimit = ref(100)
const overview = ref<AgentMonitoringOverviewResponse | null>(null)
const toolCalls = ref<AgentRecentToolCall[]>([])
const llmCalls = ref<AgentRecentLlmCall[]>([])
const soEvents = ref<AgentStructuredOutputEvent[]>([])
const latestProbe = ref<CopilotToolReliabilityLatestResponse | CopilotToolReliabilityProbeResponse | null>(null)
const showProbeDetails = ref(false)
const expandedFailure = ref<string | null>(null)
const expandedProbeRow = ref<string | null>(null)

const ibkrChartRef = ref<HTMLDivElement | null>(null)
const mcpChartRef = ref<HTMLDivElement | null>(null)
const llmChartRef = ref<HTMLDivElement | null>(null)
const soChartRef = ref<HTMLDivElement | null>(null)

let ibkrChart: EChartsType | null = null
let mcpChart: EChartsType | null = null
let llmChart: EChartsType | null = null
let soChart: EChartsType | null = null
let resizeObserver: ResizeObserver | null = null

const ibkrCalls = computed(() => toolCalls.value.filter((item) => item.tool_domain === 'ibkr'))
const mcpCalls = computed(() => toolCalls.value.filter((item) => item.tool_domain === 'longbridge'))
const soContractOptions = computed(() => {
  const names = new Set(soEvents.value.map((e) => e.contract_name).filter(Boolean))
  return [{ label: '全部 Contract', value: '' }, ...Array.from(names).sort().map((n) => ({ label: n, value: n }))]
})
const soFailures = computed(() =>
  soEvents.value.filter((e) => !e.ok || e.repaired || e.fallback_used).slice(0, 50),
)
const visibleProbeResults = computed(() => (latestProbe.value?.results ?? []).filter((row) => ['fail', 'partial', 'skipped'].includes(row.status)))
const hasVisibleProbeResults = computed(() => visibleProbeResults.value.length > 0)

const statusCards = computed(() => [
  {
    key: 'ibkr',
    title: 'IBKR 工具',
    icon: 'pi pi-database',
    summary: overview.value?.ibkr,
    recent: summarizeRecent(ibkrCalls.value),
  },
  {
    key: 'mcp',
    title: 'MCP 工具',
    icon: 'pi pi-link',
    summary: overview.value?.longbridge,
    recent: summarizeRecent(mcpCalls.value),
  },
  {
    key: 'llm',
    title: 'LLM',
    icon: 'pi pi-sparkles',
    summary: overview.value?.llm,
    recent: summarizeRecent(llmCalls.value),
    models: Array.from(new Set(llmCalls.value.map((item) => item.model).filter(Boolean))).slice(0, 6),
  },
])

const recentFailures = computed(() => {
  const toolRows = toolCalls.value
    .filter((item) => item.ok === false || item.empty_result || item.compact_ok === false || item.missing_fields_count > 0)
    .map((item) => ({
      key: `tool:${item.id}`,
      created_at: item.created_at,
      kind: 'tool' as const,
      agent_name: item.agent_name,
      node_name: item.node_name,
      name: item.tool_name,
      domain: item.tool_domain,
      source: item.source,
      error_code: item.error_code || (item.missing_fields_count > 0 ? 'PARTIAL_FIELDS' : item.empty_result ? 'EMPTY_RESULT' : ''),
      error_message: item.error_message || (item.missing_fields_count > 0 ? `缺少字段 ${item.missing_fields_count} 个` : ''),
      latency_ms: item.latency_ms,
      run_id: item.run_id,
      task_id: item.task_id,
      partial: item.ok && item.missing_fields_count > 0,
    }))
  const llmRows = llmCalls.value
    .filter((item) => item.ok === false)
    .map((item) => ({
      key: `llm:${item.id}`,
      created_at: item.created_at,
      kind: 'llm' as const,
      agent_name: item.agent_name,
      node_name: item.node_name,
      name: item.model,
      domain: 'llm',
      source: 'runtime',
      error_code: item.error_code || '',
      error_message: item.error_message || '',
      latency_ms: item.latency_ms,
      run_id: item.run_id,
      task_id: item.task_id,
      partial: false,
    }))
  return [...toolRows, ...llmRows]
    .sort((a, b) => timestamp(b.created_at) - timestamp(a.created_at))
    .slice(0, 80)
})

watch([selectedAgent, selectedSource, selectedLimit], () => {
  void loadAll()
})

watch([toolCalls, llmCalls, selectedType], () => {
  void nextTick(renderCharts)
})

onMounted(async () => {
  await loadAll()
  await nextTick()
  ensureCharts()
  renderCharts()
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  ibkrChart?.dispose()
  mcpChart?.dispose()
  llmChart?.dispose()
  soChart?.dispose()
})

async function loadAll(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const agentName = selectedAgent.value || undefined
    const soSource = selectedSource.value === 'probe' ? 'runtime' : selectedSource.value
    const [overviewResponse, toolResponse, llmResponse, latestResponse, soResponse] = await Promise.all([
      getAgentMonitoringOverview({ hours: 24, bucket: '1h', source: selectedSource.value }),
      getAgentRecentToolCalls({
        limit: selectedLimit.value,
        source: selectedSource.value,
        agent_name: agentName,
      }),
      getAgentRecentLlmCalls({
        limit: selectedLimit.value,
        source: selectedSource.value,
        agent_name: agentName,
      }),
      getToolReliabilityLatest(),
      getStructuredOutputRecent({
        limit: selectedLimit.value,
        source: soSource as 'runtime' | 'all',
        agent_name: agentName || undefined,
      }).catch(() => ({ items: [] })),
    ])
    overview.value = overviewResponse
    toolCalls.value = toolResponse.items || []
    llmCalls.value = llmResponse.items || []
    latestProbe.value = latestResponse
    soEvents.value = soResponse.items || []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载 Agent 监控数据失败'
  } finally {
    loading.value = false
    await nextTick()
    ensureCharts()
    renderCharts()
  }
}

async function runOneClickProbe(kind: ProbeKind): Promise<void> {
  probing.value = kind
  probeMessage.value = ''
  errorMessage.value = ''
  try {
    const response = await runToolReliabilityProbe({
      include_live: true,
      include_longbridge: kind === 'mcp',
      include_ibkr: kind === 'ibkr',
      include_agent_eval: false,
      symbol: 'AMD.US',
      keyword: 'AMD',
      max_tools: 20,
    })
    latestProbe.value = response
    probeMessage.value = [
      `${kind === 'mcp' ? 'MCP' : 'IBKR'} 检测完成`,
      `total ${response.total}`,
      `pass ${response.pass}`,
      `fail ${response.fail}`,
      `skipped ${response.skipped}`,
      `成功率 ${formatPct(response.success_rate)}`,
      selectedSource.value === 'probe' || selectedSource.value === 'all' ? '已展示在最近调用视图中。' : '切换 Source=all/probe 可查看主动检测调用。',
    ].join(' · ')
    await loadAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '运行检测失败'
  } finally {
    probing.value = null
  }
}

function ensureCharts(): void {
  if (!ibkrChart && ibkrChartRef.value) ibkrChart = echarts.init(ibkrChartRef.value, undefined, { renderer: 'canvas' })
  if (!mcpChart && mcpChartRef.value) mcpChart = echarts.init(mcpChartRef.value, undefined, { renderer: 'canvas' })
  if (!llmChart && llmChartRef.value) llmChart = echarts.init(llmChartRef.value, undefined, { renderer: 'canvas' })
  if (!soChart && soChartRef.value) soChart = echarts.init(soChartRef.value, undefined, { renderer: 'canvas' })
  if (!resizeObserver && (ibkrChartRef.value || mcpChartRef.value || llmChartRef.value || soChartRef.value)) {
    resizeObserver = new ResizeObserver(() => {
      ibkrChart?.resize()
      mcpChart?.resize()
      llmChart?.resize()
      soChart?.resize()
    })
    ;[ibkrChartRef.value, mcpChartRef.value, llmChartRef.value, soChartRef.value].forEach((element) => {
      if (element) resizeObserver?.observe(element)
    })
  }
}

function renderCharts(): void {
  ensureCharts()
  if (selectedType.value === 'llm') {
    renderToolChart(ibkrChart, [], 'IBKR 最近调用视图')
    renderToolChart(mcpChart, [], 'MCP 最近调用视图')
  } else {
    renderToolChart(ibkrChart, selectedType.value === 'mcp' ? [] : ibkrCalls.value, 'IBKR 最近调用视图')
    renderToolChart(mcpChart, selectedType.value === 'ibkr' ? [] : mcpCalls.value, 'MCP 最近调用视图')
  }
  renderLlmChart(selectedType.value === 'mcp' || selectedType.value === 'ibkr' ? [] : llmCalls.value)
  renderSoChart(soEvents.value)
}

function baseChartOption(title: string): Record<string, any> {
  return {
    color: ['#60a5fa', '#22c55e', '#f59e0b', '#ef4444'],
    backgroundColor: 'transparent',
    title: { text: title, left: 0, top: 0, textStyle: { color: '#dbeafe', fontSize: 14, fontWeight: 700 } },
    legend: { top: 28, left: 0, textStyle: { color: '#9fb2d1' }, itemWidth: 12, itemHeight: 8 },
    grid: { left: 48, right: 52, top: 76, bottom: 42 },
    xAxis: {
      type: 'category',
      axisLine: { lineStyle: { color: 'rgba(159, 178, 209, 0.24)' } },
      axisTick: { show: false },
      axisLabel: { color: '#9fb2d1' },
      data: [],
    },
    yAxis: { type: 'value', axisLabel: { color: '#9fb2d1' }, splitLine: { lineStyle: { color: 'rgba(129, 160, 207, 0.12)' } } },
    series: [],
  }
}

function renderToolChart(chart: EChartsType | null, calls: AgentRecentToolCall[], title: string): void {
  if (!chart) return
  const labels = calls.map((_, index) => `#${index + 1}`)
  chart.setOption({
    ...baseChartOption(title),
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(8, 13, 24, 0.96)',
      borderColor: 'rgba(129, 160, 207, 0.22)',
      textStyle: { color: '#dbeafe' },
      formatter: (params: any) => {
        const rows = Array.isArray(params) ? params : [params]
        const index = rows[0]?.dataIndex ?? 0
        const point = calls[index]
        if (!point) return '暂无调用'
        return [
          `${rows[0]?.axisValue || ''} · ${formatTime(point.created_at)}`,
          `agent: ${point.agent_name}`,
          `node: ${point.node_name}`,
          `tool: ${point.tool_name}`,
          `ok: ${point.ok}`,
          `latency: ${formatMs(point.latency_ms)}`,
          `rolling success: ${formatPct(point.rolling_success_rate_10)} (${point.rolling_window_size})`,
          `rolling failure: ${formatPct(point.rolling_failure_rate_10)}`,
          `empty_result: ${point.empty_result}`,
          `raw_ok: ${point.raw_ok ?? '--'}`,
          `compact_ok: ${point.compact_ok ?? '--'}`,
          `parsed_fields: ${point.parsed_fields_count}`,
          `missing_fields: ${point.missing_fields_count}`,
          `error_code: ${point.error_code || '--'}`,
          `error: ${truncateText(point.error_message, 180) || '--'}`,
        ].join('<br/>')
      },
    },
    xAxis: { ...baseChartOption(title).xAxis, data: labels },
    yAxis: [
      { type: 'value', min: 0, axisLabel: { formatter: '{value}ms', color: '#9fb2d1' }, splitLine: { lineStyle: { color: 'rgba(129, 160, 207, 0.12)' } } },
      { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%', color: '#9fb2d1' }, splitLine: { show: false } },
    ],
    series: [
      { name: 'latency_ms', type: 'line', yAxisIndex: 0, smooth: true, data: calls.map((item) => item.latency_ms) },
      { name: 'rolling_success_rate_10', type: 'line', yAxisIndex: 1, smooth: true, data: calls.map((item) => roundPct(item.rolling_success_rate_10)) },
      { name: 'missing_fields_count', type: 'bar', yAxisIndex: 0, barMaxWidth: 16, data: calls.map((item) => item.missing_fields_count) },
      {
        name: '失败/空结果',
        type: 'scatter',
        yAxisIndex: 0,
        symbolSize: 9,
        data: calls.map((item) => (item.ok === false || item.empty_result || item.compact_ok === false ? item.latency_ms : null)),
      },
    ],
  }, true)
}

function renderLlmChart(calls: AgentRecentLlmCall[]): void {
  if (!llmChart) return
  const labels = calls.map((_, index) => `#${index + 1}`)
  llmChart.setOption({
    ...baseChartOption('LLM 最近调用视图'),
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(8, 13, 24, 0.96)',
      borderColor: 'rgba(129, 160, 207, 0.22)',
      textStyle: { color: '#dbeafe' },
      formatter: (params: any) => {
        const rows = Array.isArray(params) ? params : [params]
        const index = rows[0]?.dataIndex ?? 0
        const point = calls[index]
        if (!point) return '暂无调用'
        return [
          `${rows[0]?.axisValue || ''} · ${formatTime(point.created_at)}`,
          `agent: ${point.agent_name}`,
          `node: ${point.node_name}`,
          `provider: ${point.provider}`,
          `model: ${point.model}`,
          `call_type: ${point.call_type}`,
          `ok: ${point.ok}`,
          `latency: ${formatMs(point.latency_ms)}`,
          `prompt_tokens: ${formatNumber(point.prompt_tokens)}`,
          `completion_tokens: ${formatNumber(point.completion_tokens)}`,
          `total_tokens: ${formatNumber(point.total_tokens)}`,
          `rolling success: ${formatPct(point.rolling_success_rate_10)} (${point.rolling_window_size})`,
          `error_code: ${point.error_code || '--'}`,
          `error: ${truncateText(point.error_message, 180) || '--'}`,
        ].join('<br/>')
      },
    },
    xAxis: { ...baseChartOption('LLM 最近调用视图').xAxis, data: labels },
    yAxis: [
      { type: 'value', min: 0, axisLabel: { formatter: '{value}ms', color: '#9fb2d1' }, splitLine: { lineStyle: { color: 'rgba(129, 160, 207, 0.12)' } } },
      { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%', color: '#9fb2d1' }, splitLine: { show: false } },
      { type: 'value', min: 0, axisLabel: { color: '#9fb2d1' }, splitLine: { show: false } },
    ],
    series: [
      { name: 'latency_ms', type: 'line', yAxisIndex: 0, smooth: true, data: calls.map((item) => item.latency_ms) },
      { name: 'rolling_success_rate_10', type: 'line', yAxisIndex: 1, smooth: true, data: calls.map((item) => roundPct(item.rolling_success_rate_10)) },
      { name: 'total_tokens', type: 'bar', yAxisIndex: 2, barMaxWidth: 16, data: calls.map((item) => item.total_tokens) },
      { name: '失败', type: 'scatter', yAxisIndex: 0, symbolSize: 9, data: calls.map((item) => (item.ok === false ? item.latency_ms : null)) },
    ],
  }, true)
}

function renderSoChart(events: AgentStructuredOutputEvent[]): void {
  if (!soChart) return
  const labels = events.map((_, index) => `#${index + 1}`)
  soChart.setOption({
    ...baseChartOption('结构化输出最近调用'),
    color: ['#60a5fa', '#22c55e', '#f59e0b', '#ef4444', '#a78bfa'],
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(8, 13, 24, 0.96)',
      borderColor: 'rgba(129, 160, 207, 0.22)',
      textStyle: { color: '#dbeafe' },
      formatter: (params: any) => {
        const rows = Array.isArray(params) ? params : [params]
        const index = rows[0]?.dataIndex ?? 0
        const point = events[index]
        if (!point) return '暂无记录'
        return [
          `${rows[0]?.axisValue || ''} · ${formatTime(point.created_at)}`,
          `contract: ${point.contract_name}`,
          `agent: ${point.agent_name}`,
          `node: ${point.node_name}`,
          `ok: ${point.ok}`,
          `repaired: ${point.repaired} (${point.repair_attempts} 次)`,
          `fallback: ${point.fallback_used}`,
          `schema_valid: ${point.schema_validation_passed}`,
          `rolling success: ${formatPct(point.rolling_success_rate_10)}`,
          `rolling repair: ${formatPct(point.rolling_repair_rate_10)}`,
          `rolling fallback: ${formatPct(point.rolling_fallback_rate_10)}`,
          `error_code: ${point.error_code || '--'}`,
          `error: ${truncateText(point.error_message, 180) || '--'}`,
          `run_id: ${point.run_id || '--'}`,
          `task_id: ${point.task_id || '--'}`,
        ].join('<br/>')
      },
    },
    xAxis: { ...baseChartOption('结构化输出最近调用').xAxis, data: labels },
    yAxis: [
      { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%', color: '#9fb2d1' }, splitLine: { lineStyle: { color: 'rgba(129, 160, 207, 0.12)' } } },
      { type: 'value', min: 0, axisLabel: { color: '#9fb2d1' }, splitLine: { show: false } },
    ],
    series: [
      { name: 'rolling_success_rate_10', type: 'line', yAxisIndex: 0, smooth: true, data: events.map((item) => roundPct(item.rolling_success_rate_10)) },
      { name: 'rolling_repair_rate_10', type: 'line', yAxisIndex: 0, smooth: true, data: events.map((item) => roundPct(item.rolling_repair_rate_10)) },
      { name: 'rolling_fallback_rate_10', type: 'line', yAxisIndex: 0, smooth: true, data: events.map((item) => roundPct(item.rolling_fallback_rate_10)) },
      { name: 'repair_attempts', type: 'bar', yAxisIndex: 1, barMaxWidth: 12, data: events.map((item) => item.repair_attempts) },
      {
        name: '状态',
        type: 'scatter',
        yAxisIndex: 1,
        symbolSize: 10,
        data: events.map((item) => {
          if (!item.ok) return 1
          if (item.fallback_used) return 0.8
          if (item.repaired) return 0.5
          return 0
        }),
      },
    ],
  }, true)
}

function summarizeRecent(items: Array<{ ok: boolean; latency_ms: number; rolling_success_rate_10?: number }>): { count: number; successRate: number; p95: number; status: string } {
  const count = items.length
  const last = items[count - 1]
  const successRate = last?.rolling_success_rate_10 ?? (count ? items.filter((item) => item.ok).length / count : 0)
  const p95 = percentile(items.map((item) => item.latency_ms), 0.95)
  return { count, successRate, p95, status: statusFromSuccessRate(successRate, count) }
}

function percentile(values: number[], ratio: number): number {
  const sorted = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b)
  if (!sorted.length) return 0
  const index = Math.min(sorted.length - 1, Math.ceil(sorted.length * ratio) - 1)
  return sorted[index]
}

function statusFromSuccessRate(successRate: number, total: number): string {
  if (total <= 0) return 'unknown'
  if (successRate >= 0.95) return 'healthy'
  if (successRate >= 0.8) return 'degraded'
  return 'down'
}

function roundPct(value: number | null | undefined): number {
  return Number(((value ?? 0) * 100).toFixed(1))
}

function formatPct(value: number | null | undefined): string {
  return `${roundPct(value).toFixed(1)}%`
}

function formatMs(value: number | null | undefined): string {
  const ms = Math.round(value ?? 0)
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}

function formatNumber(value: number | null | undefined): string {
  return new Intl.NumberFormat('zh-CN').format(Math.round(value ?? 0))
}

function formatTime(value: string | null | undefined): string {
  if (!value) return '--'
  return value.slice(0, 19).replace('T', ' ')
}

function timestamp(value: string): number {
  const time = new Date(value).getTime()
  return Number.isNaN(time) ? 0 : time
}

function statusLabel(status: string | undefined): string {
  switch (status) {
    case 'healthy': return '正常'
    case 'degraded': return '降级'
    case 'down': return '异常'
    default: return '暂无数据'
  }
}

function statusSeverity(status: string | undefined): 'success' | 'warn' | 'danger' | 'secondary' {
  switch (status) {
    case 'healthy': return 'success'
    case 'degraded': return 'warn'
    case 'down': return 'danger'
    default: return 'secondary'
  }
}

function getLegacySummaryMetric(summary: AgentMonitoringStatusSummary | undefined, metric: string): number {
  if (!summary) return 0
  const requested = `${metric}_24h`
  const value = summary[requested] ?? 0
  return typeof value === 'number' ? value : 0
}

function isSensitiveKey(key: string): boolean {
  const lower = key.toLowerCase()
  return SENSITIVE_KEYWORDS.some((keyword) => lower === keyword || lower.includes(keyword))
}

function sanitizeText(value: string | null | undefined): string {
  if (!value) return ''
  let sanitized = value.replace(SENSITIVE_VALUE_PATTERN, '***REDACTED***')
  SENSITIVE_KEYWORDS.forEach((keyword) => {
    const pattern = new RegExp(`(${keyword}\\s*[:=]\\s*)[^,;\\s]+`, 'gi')
    sanitized = sanitized.replace(pattern, '$1***REDACTED***')
  })
  return sanitized
}

function truncateText(value: string | null | undefined, maxLength = 120): string {
  const sanitized = sanitizeText(value)
  return sanitized.length > maxLength ? `${sanitized.slice(0, maxLength)}...` : sanitized
}

function sanitizeObject(obj: Record<string, any> | null | undefined): Record<string, any> {
  if (!obj) return {}
  const out: Record<string, any> = {}
  for (const [key, value] of Object.entries(obj)) {
    if (isSensitiveKey(key)) {
      out[key] = '***REDACTED***'
    } else if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
      out[key] = sanitizeObject(value as Record<string, any>)
    } else if (typeof value === 'string') {
      out[key] = sanitizeText(value)
    } else {
      out[key] = value
    }
  }
  return out
}

function emptyHint(kind: string): string {
  return `当前筛选条件下没有${kind}调用记录。可以切换 Source=all，点击一键检测 MCP / IBKR，或先运行一次 AI 决策任务后刷新。`
}

function failureKey(row: { key: string }): string {
  return row.key
}

function toggleFailure(row: { key: string }): void {
  expandedFailure.value = expandedFailure.value === row.key ? null : row.key
}

function toggleProbeRow(row: CopilotToolProbeResult): void {
  expandedProbeRow.value = expandedProbeRow.value === row.id ? null : row.id
}

function probeStatusSeverity(status: string): 'success' | 'danger' | 'warn' | 'secondary' {
  switch (status) {
    case 'pass': return 'success'
    case 'fail': return 'danger'
    case 'partial': return 'warn'
    default: return 'secondary'
  }
}
</script>

<template>
  <section class="agent-monitoring">
    <LoadingBlock v-if="loading" />

    <template v-else>
      <ErrorBlock v-if="errorMessage" :message="errorMessage" />

      <section class="agent-monitoring__toolbar surface-panel">
        <div class="surface-panel__content agent-monitoring__toolbar-content">
          <div>
            <p class="eyebrow">RECENT CALLS</p>
            <h3 class="panel-title">运行监控</h3>
            <p class="panel-subtitle">每个点代表一次真实调用；成功率为最近 10 次滚动值。</p>
          </div>
          <div class="agent-monitoring__toolbar-controls">
            <label>
              Agent
              <select v-model="selectedAgent">
                <option v-for="option in agentOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
            </label>
            <label>
              Source
              <select v-model="selectedSource">
                <option v-for="option in sourceOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
            </label>
            <label>
              类型
              <select v-model="selectedType">
                <option v-for="option in typeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
            </label>
            <label>
              Limit
              <select v-model.number="selectedLimit">
                <option v-for="option in limitOptions" :key="option" :value="option">{{ option }}</option>
              </select>
            </label>
            <Button label="刷新" icon="pi pi-refresh" class="p-button p-button--ghost" @click="loadAll" />
          </div>
        </div>
      </section>

      <section class="agent-monitoring__status-grid">
        <article
          v-for="card in statusCards"
          :key="card.key"
          class="agent-monitoring__status-card"
          :class="`agent-monitoring__status-card--${card.recent.status}`"
        >
          <div class="agent-monitoring__status-header">
            <span class="agent-monitoring__status-icon"><i :class="card.icon"></i></span>
            <div>
              <h3>{{ card.title }}</h3>
              <Tag :value="statusLabel(card.recent.status)" :severity="statusSeverity(card.recent.status)" />
            </div>
          </div>
          <dl class="agent-monitoring__status-metrics">
            <div>
              <dt>最近 10 次成功率</dt>
              <dd>{{ formatPct(card.recent.successRate) }}</dd>
            </div>
            <div>
              <dt>当前列表调用数</dt>
              <dd>{{ card.recent.count }}</dd>
            </div>
            <div>
              <dt>P95 耗时</dt>
              <dd>{{ formatMs(card.recent.p95 || getLegacySummaryMetric(card.summary, 'p95_latency_ms')) }}</dd>
            </div>
          </dl>
          <div v-if="'models' in card && card.models?.length" class="agent-monitoring__models">
            <span v-for="model in card.models" :key="model">{{ model }}</span>
          </div>
        </article>
      </section>

      <section class="surface-panel">
        <div class="surface-panel__content">
          <div class="section-header agent-monitoring__actions-header">
            <div>
              <h3 class="panel-title">一键检测</h3>
              <p class="panel-subtitle">检测只会调用只读工具，不会下单、撤单、转账或修改账户。</p>
            </div>
            <div class="agent-monitoring__probe-actions">
              <Button
                label="一键检测 MCP"
                icon="pi pi-link"
                class="p-button p-button--accent"
                :loading="probing === 'mcp'"
                :disabled="probing !== null"
                @click="runOneClickProbe('mcp')"
              />
              <Button
                label="一键检测 IBKR"
                icon="pi pi-database"
                class="p-button p-button--ghost"
                :loading="probing === 'ibkr'"
                :disabled="probing !== null"
                @click="runOneClickProbe('ibkr')"
              />
            </div>
          </div>
          <p v-if="probeMessage" class="agent-monitoring__probe-message">{{ probeMessage }}</p>
        </div>
      </section>

      <section class="agent-monitoring__chart-grid">
        <article v-if="selectedType === 'all' || selectedType === 'ibkr'" class="agent-monitoring__chart-card">
          <div v-if="!ibkrCalls.length" class="agent-monitoring__empty-chart">{{ emptyHint(' IBKR 工具') }}</div>
          <div ref="ibkrChartRef" class="agent-monitoring__chart"></div>
        </article>
        <article v-if="selectedType === 'all' || selectedType === 'mcp'" class="agent-monitoring__chart-card">
          <div v-if="!mcpCalls.length" class="agent-monitoring__empty-chart">{{ emptyHint(' MCP 工具') }}</div>
          <div ref="mcpChartRef" class="agent-monitoring__chart"></div>
        </article>
        <article v-if="selectedType === 'all' || selectedType === 'llm'" class="agent-monitoring__chart-card agent-monitoring__chart-card--wide">
          <div v-if="!llmCalls.length" class="agent-monitoring__empty-chart">{{ emptyHint(' LLM') }}</div>
          <div ref="llmChartRef" class="agent-monitoring__chart"></div>
        </article>
      </section>

      <section class="surface-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h3 class="panel-title">结构化输出最近调用</h3>
              <p class="panel-subtitle">每个点代表一次结构化输出处理结果；横轴是最近 N 次调用。</p>
            </div>
            <Tag :value="`${soEvents.length} 条`" severity="info" />
          </div>
          <div v-if="soEvents.length" class="agent-monitoring__chart-card agent-monitoring__chart-card--wide">
            <div ref="soChartRef" class="agent-monitoring__chart"></div>
          </div>
          <div v-else class="empty-state">当前还没有结构化输出监控记录。请先运行一次 Account Copilot / AI 决策 / 每日复盘 / 交易复盘，然后刷新。</div>
        </div>
      </section>

      <section v-if="soFailures.length" class="surface-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h3 class="panel-title">结构化输出异常记录</h3>
              <p class="panel-subtitle">最近失败、repair 或 fallback 的结构化输出事件。</p>
            </div>
            <Tag :value="`${soFailures.length} 条`" severity="warn" />
          </div>
          <div class="table-shell">
            <table class="agent-monitoring__table">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>Contract</th>
                  <th>Agent / 节点</th>
                  <th>状态</th>
                  <th>Repair</th>
                  <th>Fallback</th>
                  <th>错误码</th>
                  <th>run_id</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in soFailures" :key="row.id">
                  <td>{{ formatTime(row.created_at) }}</td>
                  <td class="agent-monitoring__mono">{{ row.contract_name }}</td>
                  <td>{{ row.agent_name }} / {{ row.node_name }}</td>
                  <td>
                    <Tag
                      :value="row.ok ? (row.fallback_used ? 'fallback' : row.repaired ? 'repaired' : 'success') : 'failed'"
                      :severity="row.ok ? (row.fallback_used ? 'warn' : row.repaired ? 'info' : 'success') : 'danger'"
                    />
                  </td>
                  <td>{{ row.repaired ? `${row.repair_attempts}次` : '--' }}</td>
                  <td>{{ row.fallback_used ? '是' : '--' }}</td>
                  <td>{{ row.error_code || '--' }}</td>
                  <td class="agent-monitoring__mono">{{ row.run_id || '--' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section class="surface-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h3 class="panel-title">最近失败与部分结果</h3>
              <p class="panel-subtitle">基于最近调用明细生成；字段缺失标记为 partial，不等同于调用失败。</p>
            </div>
            <Tag :value="`${recentFailures.length} 条`" severity="danger" />
          </div>

          <div v-if="recentFailures.length" class="table-shell">
            <table class="agent-monitoring__table">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>Agent / 节点</th>
                  <th>类型</th>
                  <th>名称</th>
                  <th>错误码</th>
                  <th>错误信息</th>
                  <th>耗时</th>
                  <th>Source</th>
                  <th>run / task</th>
                </tr>
              </thead>
              <tbody>
                <template v-for="row in recentFailures" :key="failureKey(row)">
                  <tr class="agent-monitoring__failure-row" @click="toggleFailure(row)">
                    <td>{{ formatTime(row.created_at) }}</td>
                    <td>{{ row.agent_name }} / {{ row.node_name }}</td>
                    <td><Tag :value="row.partial ? 'partial' : row.kind" :severity="row.partial ? 'warn' : row.kind === 'llm' ? 'danger' : 'info'" /></td>
                    <td class="agent-monitoring__mono">{{ row.name }}</td>
                    <td>{{ row.error_code || '--' }}</td>
                    <td>{{ truncateText(row.error_message) || '--' }}</td>
                    <td>{{ formatMs(row.latency_ms) }}</td>
                    <td>{{ row.source || '--' }}</td>
                    <td class="agent-monitoring__mono">{{ row.run_id || '--' }}<br />{{ row.task_id || '--' }}</td>
                  </tr>
                  <tr v-if="expandedFailure === failureKey(row)" class="agent-monitoring__detail-row">
                    <td colspan="9">
                      <pre>{{ sanitizeText(row.error_message) || '无错误详情' }}</pre>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>
          <div v-else class="empty-state">当前筛选条件下没有失败或部分结果。</div>
        </div>
      </section>

      <section class="surface-panel">
        <div class="surface-panel__content">
          <button type="button" class="agent-monitoring__collapse-button" @click="showProbeDetails = !showProbeDetails">
            <i :class="showProbeDetails ? 'pi pi-chevron-down' : 'pi pi-chevron-right'"></i>
            最近主动检测明细
          </button>

          <div v-if="showProbeDetails" class="agent-monitoring__probe-details">
            <div v-if="hasVisibleProbeResults" class="table-shell">
              <table class="agent-monitoring__table">
                <thead>
                  <tr>
                    <th>Tool</th>
                    <th>Domain</th>
                    <th>Status</th>
                    <th>Latency</th>
                    <th>Error Code</th>
                    <th>Created At</th>
                  </tr>
                </thead>
                <tbody>
                  <template v-for="row in visibleProbeResults" :key="row.id">
                    <tr class="agent-monitoring__failure-row" @click="toggleProbeRow(row)">
                      <td class="agent-monitoring__mono">{{ row.tool_name }}</td>
                      <td>{{ row.tool_domain }}</td>
                      <td><Tag :value="row.status.toUpperCase()" :severity="probeStatusSeverity(row.status)" /></td>
                      <td>{{ formatMs(row.latency_ms) }}</td>
                      <td>{{ row.error_code || '--' }}</td>
                      <td>{{ formatTime(row.created_at) }}</td>
                    </tr>
                    <tr v-if="expandedProbeRow === row.id" class="agent-monitoring__detail-row">
                      <td colspan="6">
                        <div v-if="row.error_message">
                          <strong>Error Message</strong>
                          <pre>{{ sanitizeText(row.error_message) }}</pre>
                        </div>
                        <div>
                          <strong>Arguments Preview</strong>
                          <pre>{{ JSON.stringify(sanitizeObject(row.arguments_preview), null, 2) }}</pre>
                        </div>
                        <div>
                          <strong>Metadata</strong>
                          <pre>{{ JSON.stringify(sanitizeObject(row.metadata), null, 2) }}</pre>
                        </div>
                      </td>
                    </tr>
                  </template>
                </tbody>
              </table>
            </div>
            <div v-else class="empty-state">暂无失败、部分成功或跳过的主动检测明细。</div>
          </div>
        </div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.agent-monitoring {
  display: grid;
  gap: var(--space-4);
}

.agent-monitoring__toolbar-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.agent-monitoring__toolbar-controls {
  display: flex;
  align-items: end;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.agent-monitoring__toolbar-controls label {
  display: grid;
  gap: 5px;
  color: var(--color-text-secondary);
  font-size: 0.76rem;
}

.agent-monitoring__toolbar-controls select {
  min-height: 34px;
  border: 1px solid rgba(129, 160, 207, 0.18);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.78);
  color: var(--color-text-primary);
  padding: 0 10px;
}

.agent-monitoring__status-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.agent-monitoring__status-card {
  display: grid;
  gap: 16px;
  padding: 18px;
  border: 1px solid rgba(129, 160, 207, 0.16);
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.62);
}

.agent-monitoring__status-card--healthy {
  border-color: rgba(34, 197, 94, 0.35);
}

.agent-monitoring__status-card--degraded {
  border-color: rgba(245, 158, 11, 0.38);
}

.agent-monitoring__status-card--down {
  border-color: rgba(239, 68, 68, 0.42);
}

.agent-monitoring__status-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.agent-monitoring__status-header h3 {
  margin: 0 0 6px;
  font-size: 1rem;
}

.agent-monitoring__status-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border-radius: var(--radius-sm);
  background: rgba(129, 160, 207, 0.13);
  color: #bfdbfe;
}

.agent-monitoring__status-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin: 0;
}

.agent-monitoring__status-metrics dt {
  color: var(--color-text-secondary);
  font-size: 0.76rem;
}

.agent-monitoring__status-metrics dd {
  margin: 5px 0 0;
  font-weight: 700;
}

.agent-monitoring__models {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.agent-monitoring__models span {
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  background: rgba(129, 160, 207, 0.12);
  color: var(--color-text-secondary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.74rem;
}

.agent-monitoring__actions-header {
  align-items: center;
}

.agent-monitoring__probe-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.agent-monitoring__probe-message {
  margin: 12px 0 0;
  padding: 10px 12px;
  border: 1px solid rgba(34, 197, 94, 0.22);
  border-radius: var(--radius-sm);
  background: rgba(20, 83, 45, 0.18);
  color: #bbf7d0;
}

.agent-monitoring__chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.agent-monitoring__chart-card {
  position: relative;
  min-height: 340px;
  border: 1px solid rgba(129, 160, 207, 0.14);
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.54);
  padding: 14px;
}

.agent-monitoring__chart-card--wide {
  grid-column: 1 / -1;
}

.agent-monitoring__chart {
  width: 100%;
  height: 310px;
}

.agent-monitoring__empty-chart {
  position: absolute;
  inset: 108px 28px auto;
  z-index: 1;
  display: flex;
  justify-content: center;
  text-align: center;
  color: var(--color-text-secondary);
  pointer-events: none;
}

.agent-monitoring__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.86rem;
}

.agent-monitoring__table th,
.agent-monitoring__table td {
  padding: 10px 12px;
  border-bottom: 1px solid rgba(129, 160, 207, 0.12);
  text-align: left;
  vertical-align: top;
}

.agent-monitoring__table th {
  color: var(--color-text-secondary);
  font-weight: 600;
}

.agent-monitoring__failure-row {
  cursor: pointer;
}

.agent-monitoring__failure-row:hover {
  background: rgba(129, 160, 207, 0.06);
}

.agent-monitoring__detail-row pre {
  max-height: 280px;
  overflow: auto;
  margin: 8px 0;
  padding: 12px;
  border: 1px solid rgba(129, 160, 207, 0.12);
  border-radius: var(--radius-sm);
  background: rgba(2, 6, 23, 0.5);
  color: var(--color-text-secondary);
  white-space: pre-wrap;
}

.agent-monitoring__mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.78rem;
}

.agent-monitoring__collapse-button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 36px;
  border: 1px solid rgba(129, 160, 207, 0.18);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.5);
  color: var(--color-text-secondary);
  cursor: pointer;
  font: inherit;
  padding: 0 12px;
}

.agent-monitoring__probe-details {
  margin-top: 14px;
}

.empty-state {
  padding: 28px;
  border: 1px dashed rgba(129, 160, 207, 0.18);
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  text-align: center;
}

@media (max-width: 960px) {
  .agent-monitoring__status-grid,
  .agent-monitoring__chart-grid {
    grid-template-columns: 1fr;
  }

  .agent-monitoring__toolbar-controls {
    justify-content: flex-start;
  }
}
</style>
