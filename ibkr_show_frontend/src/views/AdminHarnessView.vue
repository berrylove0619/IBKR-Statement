<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import Tag from 'primevue/tag'

import {
  createEvalCaseFromReplay,
  exportAgentReplay,
  getAgentReplay,
  getAgentReplayByRun,
  getAgentRun,
  getEvalCase,
  getEvalRun,
  listAgentReplays,
  listAgentRuns,
  listEvalCases,
  listEvalRuns,
  listLlmCalls,
  runEval,
  seedEvalCases,
} from '@/api/adminHarness'
import JsonBlock from '@/components/admin/JsonBlock.vue'
import type {
  AgentReplaySnapshot,
  AgentRunTraceDetail,
  AgentRunTraceListItem,
  EvalCase,
  EvalCaseResult,
  EvalRun,
  LLMCallMetric,
} from '@/types/adminHarness'

type HarnessTab = 'overview' | 'llm-calls' | 'agent-runs' | 'replays' | 'eval-cases' | 'eval-runs'

const router = useRouter()
const activeTab = ref<HarnessTab>('overview')
const loading = ref(false)
const errorMessage = ref('')
const noticeMessage = ref('')

const llmCalls = ref<LLMCallMetric[]>([])
const llmSummary = ref<Record<string, unknown>>({})
const agentRuns = ref<AgentRunTraceListItem[]>([])
const agentRunSummary = ref<Record<string, unknown>>({})
const replays = ref<AgentReplaySnapshot[]>([])
const replaySummary = ref<Record<string, unknown>>({})
const evalCases = ref<EvalCase[]>([])
const evalRuns = ref<EvalRun[]>([])
const evalRunSummary = ref<Record<string, unknown>>({})

const selectedLlmCall = ref<LLMCallMetric | null>(null)
const selectedRun = ref<AgentRunTraceDetail | null>(null)
const selectedReplay = ref<AgentReplaySnapshot | null>(null)
const selectedEvalCase = ref<EvalCase | null>(null)
const selectedEvalRun = ref<EvalRun | null>(null)
const selectedEvalChecks = ref<Record<string, unknown>[] | null>(null)
const exportPackage = ref<Record<string, unknown> | null>(null)

const llmFilters = reactive({ hours: 24, agent_name: '', prompt_key: '', model: '', ok: '', limit: 100 })
const runFilters = reactive({ hours: 24, agent_name: '', final_status: '', limit: 100 })
const replayFilters = reactive({ hours: 24, agent_name: '', final_status: '', limit: 100 })
const caseFilters = reactive({ agent_name: '', source: '', limit: 100 })
const evalRunFilters = reactive({ hours: 24, agent_name: '', limit: 100 })

const harnessTabs: { key: HarnessTab; label: string; description: string }[] = [
  {
    key: 'overview',
    label: '总览',
    description: '展示 Agent Harness 的整体运行概况，包括 Agent 执行状态、LLM 调用、工具调用、评测运行和近期异常等核心指标。',
  },
  {
    key: 'llm-calls',
    label: 'LLM 调用',
    description: '展示 LLM 调用记录，包括模型、Provider、调用类型、耗时、Token 消耗、调用状态和错误信息，用于分析模型调用成本与稳定性。',
  },
  {
    key: 'agent-runs',
    label: 'Agent 运行',
    description: '展示 Agent Run 记录，包括运行状态、执行耗时、调用链路、fallback、data limitations 和错误信息，用于排查单次 Agent 执行过程。',
  },
  {
    key: 'replays',
    label: '回放记录',
    description: '展示 Replay 快照，用于还原某次 Agent 运行时的输入、上下文、工具结果和最终输出，支持问题复现与回归评测。',
  },
  {
    key: 'eval-cases',
    label: '评测用例',
    description: '管理 Agent Evaluation 的测试用例，包括输入、期望字段、禁用行为、预期工具调用和评分规则，用于沉淀 bad case 和标准样本。',
  },
  {
    key: 'eval-runs',
    label: '评测运行',
    description: '展示 Eval Run 执行结果，包括通过率、失败用例、评分明细和错误原因，用于验证 Prompt、模型、工具或工作流变更后是否发生回归。',
  },
]

const activeHarnessTab = computed(() => harnessTabs.find((tab) => tab.key === activeTab.value) ?? harnessTabs[0])

const overviewCards = computed(() => [
  { label: 'LLM 调用次数', value: formatNumber(summaryNumber(llmSummary.value, 'call_count', llmCalls.value.length)) },
  { label: 'LLM 成功率', value: formatRate(summaryNumber(llmSummary.value, 'success_rate', successRate(llmCalls.value, 'ok'))) },
  { label: '总 Tokens', value: formatNumber(summaryNumber(llmSummary.value, 'total_tokens', sum(llmCalls.value, 'total_tokens'))) },
  { label: '平均延迟', value: formatLatency(summaryNumber(llmSummary.value, 'avg_latency_ms', average(llmCalls.value, 'latency_ms'))) },
  { label: 'Agent Runs', value: formatNumber(summaryNumber(agentRunSummary.value, 'run_count', agentRuns.value.length)) },
  { label: 'Run 成功率', value: formatRate(summaryNumber(agentRunSummary.value, 'success_rate', statusRate(agentRuns.value, 'success'))) },
  { label: 'Replay 数量', value: formatNumber(summaryNumber(replaySummary.value, 'snapshot_count', replays.value.length)) },
  { label: 'Eval Runs', value: formatNumber(summaryNumber(evalRunSummary.value, 'run_count', evalRuns.value.length)) },
  { label: 'Eval Pass Rate', value: formatRate(latestEvalPassRate.value) },
])

const latestEvalPassRate = computed(() => {
  const latest = evalRuns.value[0]
  const summary = latest?.summary ?? {}
  return summaryNumber(summary, 'pass_rate', 0)
})

function setTab(tab: HarnessTab): void {
  activeTab.value = tab
}

async function loadCurrentTab(): Promise<void> {
  if (activeTab.value === 'overview') return loadOverview()
  if (activeTab.value === 'llm-calls') return loadLlmCalls()
  if (activeTab.value === 'agent-runs') return loadAgentRuns()
  if (activeTab.value === 'replays') return loadReplays()
  if (activeTab.value === 'eval-cases') return loadEvalCases()
  return loadEvalRuns()
}

async function loadOverview(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  const [llm, runs, replayList, evalRunList] = await Promise.allSettled([
    listLlmCalls({ hours: 24, limit: 100 }),
    listAgentRuns({ hours: 24, limit: 100 }),
    listAgentReplays({ hours: 24, limit: 100 }),
    listEvalRuns({ hours: 24, limit: 100 }),
  ])
  if (llm.status === 'fulfilled') {
    llmCalls.value = llm.value.items
    llmSummary.value = llm.value.summary ?? {}
  }
  if (runs.status === 'fulfilled') {
    agentRuns.value = runs.value.items
    agentRunSummary.value = runs.value.summary ?? {}
  }
  if (replayList.status === 'fulfilled') {
    replays.value = replayList.value.items
    replaySummary.value = replayList.value.summary ?? {}
  }
  if (evalRunList.status === 'fulfilled') {
    evalRuns.value = evalRunList.value.items
    evalRunSummary.value = evalRunList.value.summary ?? {}
  }
  const failed = [llm, runs, replayList, evalRunList].filter((item) => item.status === 'rejected')
  errorMessage.value = failed.length ? `${failed.length} 个 Harness 接口加载失败，其余数据已显示` : ''
  loading.value = false
}

async function loadLlmCalls(): Promise<void> {
  await withLoading(async () => {
    const response = await listLlmCalls({
      ...llmFilters,
      ok: llmFilters.ok === '' ? null : llmFilters.ok === 'true',
    })
    llmCalls.value = response.items
    llmSummary.value = response.summary ?? {}
  })
}

async function loadAgentRuns(): Promise<void> {
  await withLoading(async () => {
    const response = await listAgentRuns(runFilters)
    agentRuns.value = response.items
    agentRunSummary.value = response.summary ?? {}
  })
}

async function loadReplays(): Promise<void> {
  await withLoading(async () => {
    const response = await listAgentReplays(replayFilters)
    replays.value = response.items
    replaySummary.value = response.summary ?? {}
  })
}

async function loadEvalCases(): Promise<void> {
  await withLoading(async () => {
    const response = await listEvalCases(caseFilters)
    evalCases.value = response.items
  })
}

async function loadEvalRuns(): Promise<void> {
  await withLoading(async () => {
    const response = await listEvalRuns(evalRunFilters)
    evalRuns.value = response.items
    evalRunSummary.value = response.summary ?? {}
  })
}

async function withLoading(action: () => Promise<void>): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    await action()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Harness 数据加载失败'
  } finally {
    loading.value = false
  }
}

async function openRun(row: AgentRunTraceListItem): Promise<void> {
  selectedRun.value = await getAgentRun(row.run_id)
}

async function openReplay(row: AgentReplaySnapshot): Promise<void> {
  if (!row.replay_id) return
  exportPackage.value = null
  selectedReplay.value = await getAgentReplay(row.replay_id)
}

async function openReplayByRun(runId?: string | null): Promise<void> {
  if (!runId) return
  try {
    const replay = await getAgentReplayByRun(runId)
    activeTab.value = 'replays'
    selectedReplay.value = replay
    noticeMessage.value = `已找到 Replay ${replay.replay_id}`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '该 run 暂无 Replay'
  }
}

async function openEvalCase(row: EvalCase): Promise<void> {
  if (!row.case_id) return
  selectedEvalCase.value = await getEvalCase(row.case_id)
}

async function openEvalRun(row: EvalRun): Promise<void> {
  if (!row.eval_run_id) return
  selectedEvalChecks.value = null
  selectedEvalRun.value = await getEvalRun(row.eval_run_id)
}

async function exportReplay(): Promise<void> {
  if (!selectedReplay.value?.replay_id) return
  exportPackage.value = await exportAgentReplay(selectedReplay.value.replay_id)
}

async function createCaseFromSelectedReplay(): Promise<void> {
  if (!selectedReplay.value?.replay_id) return
  const created = await createEvalCaseFromReplay(selectedReplay.value.replay_id, true)
  noticeMessage.value = `已创建 Eval Case: ${created.case_id}`
  await loadEvalCases()
}

async function runEvalForReplay(): Promise<void> {
  if (!selectedReplay.value?.replay_id) return
  const run = await runEval({
    replay_ids: [selectedReplay.value.replay_id],
    mode: 'static',
    name: `Static eval from replay ${selectedReplay.value.replay_id}`,
  })
  selectedEvalRun.value = run
  activeTab.value = 'eval-runs'
  noticeMessage.value = `Eval Run 已完成: ${run.eval_run_id}`
  await loadEvalRuns()
}

async function seedCases(): Promise<void> {
  const result = await seedEvalCases(false)
  noticeMessage.value = `Seed 完成: created=${result.created_count ?? 0}, skipped=${result.skipped_count ?? 0}`
  await loadEvalCases()
}

async function runEvalForCase(caseId?: string): Promise<void> {
  if (!caseId) return
  const run = await runEval({
    case_ids: [caseId],
    mode: 'static',
    name: `Static eval case ${caseId}`,
  })
  selectedEvalRun.value = run
  activeTab.value = 'eval-runs'
  noticeMessage.value = `Eval Run 已完成: ${run.eval_run_id}`
  await loadEvalRuns()
}

function openChecks(result: EvalCaseResult): void {
  selectedEvalChecks.value = (result.checks as Record<string, unknown>[] | undefined) ?? []
}

function formatDateTime(value?: string | null): string {
  return value ? value.slice(0, 19).replace('T', ' ') : '-'
}

function formatNumber(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-'
  return new Intl.NumberFormat('zh-CN').format(value)
}

function formatLatency(value?: number | null): string {
  return value === null || value === undefined ? '-' : `${formatNumber(Math.round(value))} ms`
}

function formatCost(value?: number | null): string {
  return value === null || value === undefined ? '-' : `$${value.toFixed(6)}`
}

function formatRate(value?: number | null): string {
  return value === null || value === undefined || Number.isNaN(value) ? '-' : `${(value * 100).toFixed(1)}%`
}

function summaryNumber(summary: Record<string, unknown>, key: string, fallback = 0): number {
  const value = summary[key]
  return typeof value === 'number' ? value : fallback
}

function sum<T extends Record<string, unknown>>(items: T[], key: string): number {
  return items.reduce((total, item) => total + (typeof item[key] === 'number' ? (item[key] as number) : 0), 0)
}

function average<T extends Record<string, unknown>>(items: T[], key: string): number {
  return items.length ? sum(items, key) / items.length : 0
}

function successRate<T extends Record<string, unknown>>(items: T[], key: string): number {
  return items.length ? items.filter((item) => item[key] === true).length / items.length : 0
}

function statusRate(items: AgentRunTraceListItem[], status: string): number {
  return items.length ? items.filter((item) => item.final_status === status).length / items.length : 0
}

function statusClass(status?: string | null): string {
  if (status === 'success' || status === 'passed' || status === 'completed') return 'p-tag--positive'
  if (status === 'warning' || status === 'partial') return 'p-tag--warning'
  if (status === 'failed' || status === 'error') return 'p-tag--negative'
  return 'p-tag--accent'
}

function compactList(value?: unknown[]): string {
  return value?.length ? value.join(', ') : '-'
}

function closeLlmCallDialog(visible: boolean): void {
  if (!visible) selectedLlmCall.value = null
}

function closeRunDialog(visible: boolean): void {
  if (!visible) selectedRun.value = null
}

function closeReplayDialog(visible: boolean): void {
  if (!visible) {
    selectedReplay.value = null
    exportPackage.value = null
  }
}

function closeEvalCaseDialog(visible: boolean): void {
  if (!visible) selectedEvalCase.value = null
}

function closeEvalRunDialog(visible: boolean): void {
  if (!visible) {
    selectedEvalRun.value = null
    selectedEvalChecks.value = null
  }
}

onMounted(() => {
  void loadOverview()
})

watch(activeTab, () => {
  void loadCurrentTab()
})
</script>

<template>
  <section class="page-section admin-harness-page">
    <section class="surface-panel">
      <div class="surface-panel__content">
        <div class="section-header">
          <div>
            <p class="eyebrow">ADMIN</p>
            <h2 class="panel-title admin-harness-page__title">Harness 控制台</h2>
            <p class="panel-subtitle">观察 Agent 的 LLM 调用、运行链路、Replay 快照和 Eval 结果。</p>
          </div>
        </div>

        <nav class="admin-tabs">
          <Button label="LLM 配置" icon="pi pi-sparkles" class="terminal-nav__button" @click="router.push('/admin/llm')" />
          <Button label="IBKR 数据源" icon="pi pi-database" class="terminal-nav__button" @click="router.push('/admin/ibkr')" />
          <Button label="邮件配置" icon="pi pi-envelope" class="terminal-nav__button" @click="router.push('/admin/email')" />
          <Button label="Longbridge MCP" icon="pi pi-link" class="terminal-nav__button" @click="router.push('/admin/longbridge-mcp')" />
          <Button label="系统状态" icon="pi pi-heart" class="terminal-nav__button" @click="router.push('/admin/system')" />
          <Button label="Agent 监控" icon="pi pi-chart-line" class="terminal-nav__button" @click="router.push('/admin/agent-monitoring')" />
          <Button label="Prompt 管理" icon="pi pi-file-edit" class="terminal-nav__button" @click="router.push('/admin/prompts')" />
          <Button label="Harness 控制台" icon="pi pi-sitemap" class="terminal-nav__button is-active" />
        </nav>
      </div>
    </section>

    <section class="surface-panel">
      <div class="surface-panel__content harness-tab-panel">
        <div class="harness-toolbar">
          <div class="harness-tabs">
            <button
              v-for="tab in harnessTabs"
              :key="tab.key"
              type="button"
              :class="{ 'is-active': activeTab === tab.key }"
              @click="setTab(tab.key)"
            >
              {{ tab.label }}
            </button>
          </div>
          <Button label="Reload" icon="pi pi-refresh" severity="secondary" :loading="loading" @click="loadCurrentTab" />
        </div>
        <article class="harness-tab-description">
          <strong>{{ activeHarnessTab.label }}</strong>
          <p>{{ activeHarnessTab.description }}</p>
        </article>
      </div>
    </section>

    <p v-if="noticeMessage" class="harness-message harness-message--notice">{{ noticeMessage }}</p>
    <p v-if="errorMessage" class="harness-message harness-message--error">{{ errorMessage }}</p>

    <section v-if="activeTab === 'overview'" class="harness-stack">
      <div class="overview-grid">
        <article v-for="card in overviewCards" :key="card.label" class="surface-panel overview-card">
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
        </article>
      </div>

      <section class="overview-columns">
        <article class="surface-panel">
          <div class="surface-panel__content">
            <h3 class="panel-title">最近 LLM Calls</h3>
            <table class="harness-table">
              <tbody>
                <tr v-for="item in llmCalls.slice(0, 5)" :key="item.call_id" @click="selectedLlmCall = item">
                  <td>{{ formatDateTime(item.created_at) }}</td>
                  <td>{{ item.agent_name || '-' }}</td>
                  <td>{{ item.model || '-' }}</td>
                  <td>{{ formatNumber(item.total_tokens) }}</td>
                </tr>
              </tbody>
            </table>
            <div v-if="!llmCalls.length" class="empty-state">暂无 LLM 调用</div>
          </div>
        </article>
        <article class="surface-panel">
          <div class="surface-panel__content">
            <h3 class="panel-title">最近 Agent Runs</h3>
            <table class="harness-table">
              <tbody>
                <tr v-for="item in agentRuns.slice(0, 5)" :key="item.run_id" @click="openRun(item)">
                  <td>{{ formatDateTime(item.started_at) }}</td>
                  <td>{{ item.agent_name || '-' }}</td>
                  <td><Tag :value="item.final_status || '-'" :class="statusClass(item.final_status)" /></td>
                  <td>{{ formatLatency(item.latency_ms) }}</td>
                </tr>
              </tbody>
            </table>
            <div v-if="!agentRuns.length" class="empty-state">暂无 Agent Run</div>
          </div>
        </article>
        <article class="surface-panel">
          <div class="surface-panel__content">
            <h3 class="panel-title">最近 Eval Runs</h3>
            <table class="harness-table">
              <tbody>
                <tr v-for="item in evalRuns.slice(0, 5)" :key="item.eval_run_id" @click="openEvalRun(item)">
                  <td>{{ formatDateTime(item.started_at) }}</td>
                  <td>{{ item.name || '-' }}</td>
                  <td><Tag :value="item.status || '-'" :class="statusClass(item.status)" /></td>
                  <td>{{ formatRate(summaryNumber(item.summary || {}, 'pass_rate', 0)) }}</td>
                </tr>
              </tbody>
            </table>
            <div v-if="!evalRuns.length" class="empty-state">暂无 Eval Run</div>
          </div>
        </article>
      </section>
    </section>

    <section v-else-if="activeTab === 'llm-calls'" class="surface-panel">
      <div class="surface-panel__content">
        <div class="filter-row">
          <input v-model.number="llmFilters.hours" type="number" placeholder="hours" />
          <InputText v-model="llmFilters.agent_name" placeholder="agent_name" />
          <InputText v-model="llmFilters.prompt_key" placeholder="prompt_key" />
          <InputText v-model="llmFilters.model" placeholder="model" />
          <select v-model="llmFilters.ok"><option value="">ok: all</option><option value="true">success</option><option value="false">failed</option></select>
          <input v-model.number="llmFilters.limit" type="number" placeholder="limit" />
          <Button label="查询" icon="pi pi-search" class="p-button--accent" @click="loadLlmCalls" />
        </div>
        <table class="harness-table">
          <thead><tr><th>created_at</th><th>agent</th><th>node</th><th>model</th><th>prompt</th><th>version</th><th>tokens</th><th>latency</th><th>cost</th><th>ok</th><th>error</th></tr></thead>
          <tbody>
            <tr v-for="item in llmCalls" :key="item.call_id" @click="selectedLlmCall = item">
              <td>{{ formatDateTime(item.created_at) }}</td><td>{{ item.agent_name || '-' }}</td><td>{{ item.node_name || '-' }}</td><td>{{ item.model || '-' }}</td><td>{{ item.prompt_key || '-' }}</td><td>{{ item.prompt_version || '-' }}</td><td>{{ formatNumber(item.total_tokens) }}</td><td>{{ formatLatency(item.latency_ms) }}</td><td>{{ formatCost(item.estimated_cost) }}</td><td><Tag :value="item.ok ? 'SUCCESS' : 'FAILED'" :class="item.ok ? 'p-tag--positive' : 'p-tag--negative'" /></td><td>{{ item.error_code || '-' }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!llmCalls.length" class="empty-state">暂无 LLM 调用</div>
      </div>
    </section>

    <section v-else-if="activeTab === 'agent-runs'" class="surface-panel">
      <div class="surface-panel__content">
        <div class="filter-row">
          <input v-model.number="runFilters.hours" type="number" placeholder="hours" />
          <InputText v-model="runFilters.agent_name" placeholder="agent_name" />
          <InputText v-model="runFilters.final_status" placeholder="final_status" />
          <input v-model.number="runFilters.limit" type="number" placeholder="limit" />
          <Button label="查询" icon="pi pi-search" class="p-button--accent" @click="loadAgentRuns" />
        </div>
        <table class="harness-table">
          <thead><tr><th>started_at</th><th>agent</th><th>status</th><th>latency</th><th>llm</th><th>tools</th><th>tokens</th><th>cost</th><th>prompts</th><th>run_id</th></tr></thead>
          <tbody>
            <tr v-for="item in agentRuns" :key="item.run_id" @click="openRun(item)">
              <td>{{ formatDateTime(item.started_at) }}</td><td>{{ item.agent_name || '-' }}</td><td><Tag :value="item.final_status || '-'" :class="statusClass(item.final_status)" /></td><td>{{ formatLatency(item.latency_ms) }}</td><td>{{ item.llm_call_count ?? 0 }}</td><td>{{ item.tool_call_count ?? 0 }}</td><td>{{ formatNumber(item.total_tokens) }}</td><td>{{ formatCost(item.estimated_cost) }}</td><td>{{ compactList(item.prompt_keys) }}</td><td><code>{{ item.run_id }}</code></td>
            </tr>
          </tbody>
        </table>
        <div v-if="!agentRuns.length" class="empty-state">暂无 Agent Run</div>
      </div>
    </section>

    <section v-else-if="activeTab === 'replays'" class="surface-panel">
      <div class="surface-panel__content">
        <div class="filter-row">
          <input v-model.number="replayFilters.hours" type="number" placeholder="hours" />
          <InputText v-model="replayFilters.agent_name" placeholder="agent_name" />
          <InputText v-model="replayFilters.final_status" placeholder="final_status" />
          <input v-model.number="replayFilters.limit" type="number" placeholder="limit" />
          <Button label="查询" icon="pi pi-search" class="p-button--accent" @click="loadReplays" />
        </div>
        <table class="harness-table">
          <thead><tr><th>created_at</th><th>agent</th><th>status</th><th>run_id</th><th>replay_id</th><th>prompts</th><th>model</th><th>document</th></tr></thead>
          <tbody>
            <tr v-for="item in replays" :key="item.replay_id" @click="openReplay(item)">
              <td>{{ formatDateTime(item.created_at) }}</td><td>{{ item.agent_name || '-' }}</td><td><Tag :value="item.final_status || '-'" :class="statusClass(item.final_status)" /></td><td><code>{{ item.run_id || '-' }}</code></td><td><code>{{ item.replay_id }}</code></td><td>{{ compactList((item.prompt_refs || []).map((p) => String(p.prompt_key || ''))) }}</td><td>{{ item.model_config?.model || '-' }}</td><td>{{ item.persisted_document_id || '-' }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!replays.length" class="empty-state">暂无 Replay Snapshot</div>
      </div>
    </section>

    <section v-else-if="activeTab === 'eval-cases'" class="surface-panel">
      <div class="surface-panel__content">
        <div class="filter-row">
          <InputText v-model="caseFilters.agent_name" placeholder="agent_name" />
          <InputText v-model="caseFilters.source" placeholder="source" />
          <input v-model.number="caseFilters.limit" type="number" placeholder="limit" />
          <Button label="查询" icon="pi pi-search" class="p-button--accent" @click="loadEvalCases" />
          <Button label="Seed 内置 Cases" icon="pi pi-database" severity="secondary" @click="seedCases" />
        </div>
        <table class="harness-table">
          <thead><tr><th>case_id</th><th>agent</th><th>title</th><th>source</th><th>tags</th><th>fields</th><th>created_at</th></tr></thead>
          <tbody>
            <tr v-for="item in evalCases" :key="item.case_id" @click="openEvalCase(item)">
              <td><code>{{ item.case_id }}</code></td><td>{{ item.agent_name || '-' }}</td><td>{{ item.title || '-' }}</td><td>{{ item.source || '-' }}</td><td>{{ compactList(item.tags) }}</td><td>{{ compactList(item.expected_output_fields) }}</td><td>{{ formatDateTime(item.created_at) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!evalCases.length" class="empty-state">暂无 Eval Case</div>
      </div>
    </section>

    <section v-else class="surface-panel">
      <div class="surface-panel__content">
        <div class="filter-row">
          <input v-model.number="evalRunFilters.hours" type="number" placeholder="hours" />
          <InputText v-model="evalRunFilters.agent_name" placeholder="agent_name" />
          <input v-model.number="evalRunFilters.limit" type="number" placeholder="limit" />
          <Button label="查询" icon="pi pi-search" class="p-button--accent" @click="loadEvalRuns" />
        </div>
        <table class="harness-table">
          <thead><tr><th>started_at</th><th>name</th><th>agent</th><th>status</th><th>cases</th><th>passed</th><th>warning</th><th>failed</th><th>error</th><th>pass_rate</th><th>eval_run_id</th></tr></thead>
          <tbody>
            <tr v-for="item in evalRuns" :key="item.eval_run_id" @click="openEvalRun(item)">
              <td>{{ formatDateTime(item.started_at) }}</td><td>{{ item.name || '-' }}</td><td>{{ item.agent_name || '-' }}</td><td><Tag :value="item.status || '-'" :class="statusClass(item.status)" /></td><td>{{ item.summary?.case_count ?? '-' }}</td><td>{{ item.summary?.passed_count ?? '-' }}</td><td>{{ item.summary?.warning_count ?? '-' }}</td><td>{{ item.summary?.failed_count ?? '-' }}</td><td>{{ item.summary?.error_count ?? '-' }}</td><td>{{ formatRate(summaryNumber(item.summary || {}, 'pass_rate', 0)) }}</td><td><code>{{ item.eval_run_id }}</code></td>
            </tr>
          </tbody>
        </table>
        <div v-if="!evalRuns.length" class="empty-state">暂无 Eval Run</div>
      </div>
    </section>

    <Dialog :visible="Boolean(selectedLlmCall)" modal header="LLM Call Detail" class="harness-dialog" @update:visible="closeLlmCallDialog">
      <JsonBlock :value="selectedLlmCall" />
    </Dialog>

    <Dialog :visible="Boolean(selectedRun)" modal header="Agent Run Detail" class="harness-dialog" @update:visible="closeRunDialog">
      <div v-if="selectedRun" class="dialog-stack">
        <div class="dialog-actions"><Button label="查看 Replay" icon="pi pi-history" severity="secondary" @click="openReplayByRun(selectedRun.run_id)" /></div>
        <JsonBlock title="基本信息" :value="{ run_id: selectedRun.run_id, agent_name: selectedRun.agent_name, final_status: selectedRun.final_status, latency_ms: selectedRun.latency_ms }" />
        <JsonBlock title="prompt_metadata" :value="selectedRun.prompt_metadata" />
        <JsonBlock title="llm_calls" :value="selectedRun.llm_calls" />
        <JsonBlock title="tool_calls" :value="selectedRun.tool_calls" />
        <JsonBlock title="validation / fallback" :value="{ validation: selectedRun.validation, fallback: selectedRun.fallback, repair_attempts: selectedRun.repair_attempts }" />
        <JsonBlock title="node_traces" :value="selectedRun.node_traces" collapsed />
        <JsonBlock title="metadata" :value="selectedRun.metadata" collapsed />
      </div>
    </Dialog>

    <Dialog :visible="Boolean(selectedReplay)" modal header="Replay Snapshot" class="harness-dialog" @update:visible="closeReplayDialog">
      <div v-if="selectedReplay" class="dialog-stack">
        <div class="dialog-actions">
          <Button label="导出 Replay" icon="pi pi-download" severity="secondary" @click="exportReplay" />
          <Button label="创建 Eval Case" icon="pi pi-plus" severity="secondary" @click="createCaseFromSelectedReplay" />
          <Button label="运行 Static Eval" icon="pi pi-play" class="p-button--accent" @click="runEvalForReplay" />
        </div>
        <JsonBlock title="request" :value="selectedReplay.request" />
        <JsonBlock title="prompt_refs" :value="selectedReplay.prompt_refs" />
        <JsonBlock title="model_config" :value="selectedReplay.model_config" />
        <JsonBlock title="context_snapshot" :value="selectedReplay.context_snapshot" collapsed />
        <JsonBlock title="tool_snapshots" :value="selectedReplay.tool_snapshots" />
        <JsonBlock title="llm_snapshots" :value="selectedReplay.llm_snapshots" />
        <JsonBlock title="final_output" :value="selectedReplay.final_output" />
        <JsonBlock title="data_limitations / trace_ref" :value="{ data_limitations: selectedReplay.data_limitations, trace_ref: selectedReplay.trace_ref }" />
        <JsonBlock v-if="exportPackage" title="export package" :value="exportPackage" />
      </div>
    </Dialog>

    <Dialog :visible="Boolean(selectedEvalCase)" modal header="Eval Case" class="harness-dialog" @update:visible="closeEvalCaseDialog">
      <div v-if="selectedEvalCase" class="dialog-stack">
        <div class="dialog-actions"><Button label="运行 Static Eval" icon="pi pi-play" class="p-button--accent" @click="runEvalForCase(selectedEvalCase?.case_id)" /></div>
        <JsonBlock title="input" :value="selectedEvalCase.input" />
        <JsonBlock title="mock_context" :value="selectedEvalCase.mock_context" collapsed />
        <JsonBlock title="expected_behavior" :value="selectedEvalCase.expected_behavior" />
        <JsonBlock title="expected_output_fields" :value="selectedEvalCase.expected_output_fields" />
        <JsonBlock title="forbidden_behavior" :value="selectedEvalCase.forbidden_behavior" />
        <JsonBlock title="scoring_rubric" :value="selectedEvalCase.scoring_rubric" />
        <JsonBlock title="metadata" :value="selectedEvalCase.metadata" collapsed />
      </div>
    </Dialog>

    <Dialog :visible="Boolean(selectedEvalRun)" modal header="Eval Run" class="harness-dialog" @update:visible="closeEvalRunDialog">
      <div v-if="selectedEvalRun" class="dialog-stack">
        <JsonBlock title="summary" :value="selectedEvalRun.summary" />
        <JsonBlock title="config" :value="selectedEvalRun.config" />
        <table class="harness-table">
          <thead><tr><th>case_id</th><th>agent</th><th>status</th><th>score</th><th>replay</th><th>run</th><th>error</th></tr></thead>
          <tbody>
            <tr v-for="result in selectedEvalRun.results || []" :key="`${result.case_id}-${result.replay_id}`" @click="openChecks(result)">
              <td><code>{{ result.case_id }}</code></td><td>{{ result.agent_name || '-' }}</td><td><Tag :value="result.status || '-'" :class="statusClass(result.status)" /></td><td>{{ result.score ?? 0 }}/{{ result.max_score ?? 0 }}</td><td>{{ result.replay_id || '-' }}</td><td>{{ result.run_id || '-' }}</td><td>{{ result.error_code || '-' }}</td>
            </tr>
          </tbody>
        </table>
        <JsonBlock v-if="selectedEvalChecks" title="checks" :value="selectedEvalChecks" />
      </div>
    </Dialog>
  </section>
</template>

<style scoped>
.admin-harness-page__title {
  font-size: 1.5rem;
}

.admin-tabs,
.harness-tabs,
.filter-row,
.dialog-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.harness-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.harness-tab-panel {
  display: grid;
  gap: 14px;
}

.harness-tabs button {
  padding: 8px 12px;
  border: 1px solid rgba(129, 160, 207, 0.14);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.5);
  color: var(--color-text-secondary);
  cursor: pointer;
}

.harness-tabs button.is-active,
.harness-tabs button:hover {
  border-color: rgba(86, 213, 255, 0.36);
  color: var(--color-text-primary);
}

.harness-tab-description {
  display: grid;
  gap: 6px;
  padding: 12px 14px;
  border: 1px solid rgba(86, 213, 255, 0.18);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.42);
  color: var(--color-text-secondary);
}

.harness-tab-description strong {
  color: var(--color-text-primary);
  font-size: 0.95rem;
}

.harness-tab-description p {
  margin: 0;
  line-height: 1.7;
  overflow-wrap: anywhere;
}

.harness-message {
  margin: 0;
  padding: 10px 14px;
  border-radius: var(--radius-sm);
}

.harness-message--notice {
  background: rgba(88, 214, 161, 0.12);
  color: var(--color-positive);
}

.harness-message--error {
  background: rgba(255, 107, 122, 0.12);
  color: var(--color-negative);
}

.harness-stack,
.dialog-stack {
  display: grid;
  gap: var(--space-4);
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--space-3);
}

.overview-card {
  display: grid;
  gap: 8px;
  padding: 16px;
}

.overview-card span {
  color: var(--color-text-secondary);
}

.overview-card strong {
  font-size: 1.35rem;
}

.overview-columns {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-4);
}

.filter-row {
  margin-bottom: var(--space-4);
}

.filter-row input,
.filter-row select {
  min-height: 38px;
  max-width: 180px;
  border: 1px solid rgba(129, 160, 207, 0.18);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.72);
  color: var(--color-text-primary);
}

.harness-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.86rem;
}

.harness-table th,
.harness-table td {
  padding: 10px 8px;
  border-bottom: 1px solid rgba(129, 160, 207, 0.1);
  text-align: left;
  vertical-align: top;
}

.harness-table th {
  color: var(--color-text-secondary);
  font-weight: 700;
}

.harness-table tr {
  cursor: pointer;
}

.harness-table tbody tr:hover {
  background: rgba(19, 42, 70, 0.54);
}

code {
  color: var(--color-accent-strong);
  overflow-wrap: anywhere;
}

:deep(.harness-dialog) {
  width: min(1120px, 94vw);
}

@media (max-width: 1100px) {
  .overview-columns {
    grid-template-columns: 1fr;
  }

  .harness-toolbar {
    display: grid;
  }

  .harness-table {
    display: block;
    overflow-x: auto;
    white-space: nowrap;
  }
}
</style>
