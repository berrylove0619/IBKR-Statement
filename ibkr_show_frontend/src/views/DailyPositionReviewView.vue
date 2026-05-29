<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import Button from 'primevue/button'
import Dropdown from 'primevue/dropdown'
import Tag from 'primevue/tag'

import {
  fetchDailyPositionReview,
  fetchDailyPositionReviewContext,
  fetchDailyPositionReviewDates,
  fetchDailyPositionReviewHealth,
  fetchDailyPositionReviewTasks,
  fetchRecentDailyPositionReviews,
  startDailyPositionReviewTask,
} from '@/api/dailyPositionReview'
import AgentEvidencePanel from '@/components/AgentEvidencePanel.vue'
import AgentTaskGraph from '@/components/AgentTaskGraph.vue'
import ErrorBlock from '@/components/ErrorBlock.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import type { AgentTask } from '@/types/agentTasks'
import type { DailyPositionReviewContext, DailyPositionReviewHealth, DailyPositionReviewPositionItem, DailyPositionReviewResult } from '@/types/dailyPositionReview'

defineProps<{
  embedded?: boolean
}>()

const loading = ref(true)
const contextLoading = ref(false)
const reviewLoading = ref(false)
const errorMessage = ref('')
const dates = ref<string[]>([])
const selectedDate = ref('')
const health = ref<DailyPositionReviewHealth | null>(null)
const context = ref<DailyPositionReviewContext | null>(null)
const review = ref<DailyPositionReviewResult | null>(null)
const taskItems = ref<AgentTask[]>([])
const expandedTaskId = ref<string | null>(null)
const historyVisible = ref(false)
const historyLoading = ref(false)
const historyItems = ref<DailyPositionReviewResult[]>([])
const now = ref(Date.now())
let taskTimer: number | undefined

const activeTaskCount = computed(() => taskItems.value.filter((task) => task.status === 'queued' || task.status === 'running').length)
const isGenerating = computed(() => activeTaskCount.value > 0)
const visibleTasks = computed(() => {
  const active = taskItems.value.filter((task) => task.status === 'queued' || task.status === 'running')
  const done = taskItems.value.filter((task) => task.status === 'completed' || task.status === 'failed')
  return [...active, ...done.slice(0, 2)]
})
const topContributors = computed(() => context.value?.rankings.profit_contributors?.slice(0, 5) ?? [])
const topDrags = computed(() => context.value?.rankings.loss_drags?.slice(0, 5) ?? [])
const topWeights = computed(() => context.value?.rankings.top_weights?.slice(0, 5) ?? [])
const signedTone = computed(() => ((context.value?.overview.daily_pnl ?? 0) >= 0 ? 'metric-positive' : 'metric-negative'))

function buildOptimisticTask(reportDate: string): AgentTask {
  const timestamp = new Date().toISOString()
  return {
    id: `local-daily-review-${reportDate}-${Date.now()}`,
    agent: 'daily_position_review',
    task_type: 'daily_position_review',
    label: `${reportDate} 每日持仓复盘`,
    status: 'queued',
    payload: { report_date: reportDate },
    result_id: null,
    error_code: null,
    error_message: null,
    created_at: timestamp,
    started_at: timestamp,
    completed_at: null,
    updated_at: timestamp,
    updated_seq: 0,
    graph_snapshot: null,
    graph_progress_summary: {},
    graph_events: [],
  }
}

function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return '--'
  return new Intl.NumberFormat('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value)
}

function formatPct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return '--'
  return `${formatNumber(value * 100, digits)}%`
}

function formatRawPct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return '--'
  return `${formatNumber(value, digits)}%`
}

function itemTone(item: DailyPositionReviewPositionItem): string {
  return (item.daily_pnl ?? 0) >= 0 ? 'metric-positive' : 'metric-negative'
}

function taskElapsedSeconds(task: AgentTask): number {
  const start = Date.parse(task.started_at || task.created_at)
  const end = task.completed_at ? Date.parse(task.completed_at) : now.value
  return Math.max(0, Math.floor((end - start) / 1000))
}

function taskStage(task: AgentTask): string {
  if (task.status === 'completed') return '已完成'
  if (task.status === 'failed') return task.error_message || '运行失败'
  const elapsed = taskElapsedSeconds(task)
  if (elapsed < 6) return '计算账户涨跌和持仓贡献'
  if (elapsed < 24) return '拉取 Longbridge 公开行情和事件'
  if (elapsed < 55) return '调用 LLM 生成复盘报告'
  return '保存报告并刷新页面'
}

function taskStatusLabel(status: AgentTask['status']): string {
  if (status === 'queued') return 'QUEUED'
  if (status === 'running') return 'RUNNING'
  if (status === 'completed') return 'DONE'
  return 'FAILED'
}

function toggleTask(task: AgentTask): void {
  expandedTaskId.value = expandedTaskId.value === task.id ? null : task.id
}

function mergeTaskGraphSnapshot(taskId: string, snapshot: AgentTask['graph_snapshot']): void {
  taskItems.value = taskItems.value.map((task) => (task.id === taskId ? { ...task, graph_snapshot: snapshot } : task))
}

async function viewTaskResult(task: AgentTask): Promise<void> {
  if (!task.result_id) return
  const item = await fetchDailyPositionReview(task.result_id)
  review.value = item
  const savedContext = contextFromSavedReview(item)
  context.value = savedContext || await fetchDailyPositionReviewContext(item.report_date)
}

function textValue(item: Record<string, unknown>, key: string): string {
  const value = item[key]
  if (Array.isArray(value)) return value.map((entry) => String(entry)).join('；')
  return value === undefined || value === null ? '' : String(value)
}

function contextFromSavedReview(item: DailyPositionReviewResult): DailyPositionReviewContext | null {
  const stored = (item.display_context || item.deterministic_context) as Partial<DailyPositionReviewContext> | null
  if (!stored?.overview || !stored.rankings || !stored.risk) {
    return null
  }
  const rankings = stored.rankings as Record<string, DailyPositionReviewPositionItem[]>
  return {
    report_date: String(stored.report_date || item.report_date),
    data_sources: (stored.data_sources as Record<string, string> | undefined) || item.data_source_summary || {},
    overview: stored.overview as DailyPositionReviewContext['overview'],
    positions: Array.isArray(stored.positions) ? stored.positions : rankings.top_weights ?? [],
    rankings,
    risk: stored.risk as DailyPositionReviewContext['risk'],
    benchmarks: (stored.benchmarks as DailyPositionReviewContext['benchmarks'] | undefined) || {
      items: [],
      beta_alpha_note: '已从归档报告读取，未重新拉取公开市场数据。',
    },
    focus_symbols: Array.isArray(stored.focus_symbols) ? stored.focus_symbols : [],
    attribution_quality: stored.attribution_quality || {},
    data_quality: stored.data_quality || {},
  }
}

async function loadSelectedDate(date: string): Promise<void> {
  if (!date) return
  selectedDate.value = date
  errorMessage.value = ''
  contextLoading.value = true
  reviewLoading.value = true
  try {
    const [tasksResponse, reviewResponse] = await Promise.all([
      fetchDailyPositionReviewTasks(20),
      fetchDailyPositionReview(date).catch(() => null),
    ])
    taskItems.value = tasksResponse

    if (reviewResponse) {
      review.value = reviewResponse
      reviewLoading.value = false
      const savedContext = contextFromSavedReview(reviewResponse)
      if (savedContext) {
        context.value = savedContext
        contextLoading.value = false
        return
      }
    }

    review.value = reviewResponse
    reviewLoading.value = false
    context.value = await fetchDailyPositionReviewContext(date)
    contextLoading.value = false
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载每日持仓复盘失败'
    contextLoading.value = false
    reviewLoading.value = false
  }
}

async function openHistory(): Promise<void> {
  historyVisible.value = true
  historyLoading.value = true
  errorMessage.value = ''
  try {
    historyItems.value = await fetchRecentDailyPositionReviews(60)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载复盘历史失败'
  } finally {
    historyLoading.value = false
  }
}

async function chooseHistoryDate(reportDate: string): Promise<void> {
  historyVisible.value = false
  await loadSelectedDate(reportDate)
}

async function loadPage(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const [healthResponse, dateItems] = await Promise.all([
      fetchDailyPositionReviewHealth(),
      fetchDailyPositionReviewDates(90),
    ])
    health.value = healthResponse
    dates.value = dateItems
    if (dateItems[0]) {
      selectedDate.value = dateItems[0]
      void loadSelectedDate(dateItems[0])
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载每日持仓复盘失败'
  } finally {
    loading.value = false
  }
}

async function generateReview(forceRefresh = false): Promise<void> {
  if (!selectedDate.value) return
  errorMessage.value = ''
  const optimisticTask = buildOptimisticTask(selectedDate.value)
  taskItems.value = [optimisticTask, ...taskItems.value.filter((item) => item.id !== optimisticTask.id)].slice(0, 20)
  try {
    const task = await startDailyPositionReviewTask(selectedDate.value, forceRefresh)
    taskItems.value = [task, ...taskItems.value.filter((item) => item.id !== task.id && item.id !== optimisticTask.id)].slice(0, 20)
    await pollTasks()
  } catch (error) {
    taskItems.value = [
      {
        ...optimisticTask,
        status: 'failed' as const,
        error_message: error instanceof Error ? error.message : '生成每日复盘失败',
        completed_at: new Date().toISOString(),
      },
      ...taskItems.value.filter((item) => item.id !== optimisticTask.id),
    ].slice(0, 20)
    errorMessage.value = error instanceof Error ? error.message : '生成每日复盘失败'
  }
}

async function pollTasks(): Promise<void> {
  try {
    const tasks = await fetchDailyPositionReviewTasks(20)
    taskItems.value = tasks
    const completedForDate = tasks.find((task) => task.status === 'completed' && task.result_id === selectedDate.value)
    if (completedForDate) {
      const latestReview = await fetchDailyPositionReview(selectedDate.value)
      review.value = latestReview
      const savedContext = contextFromSavedReview(latestReview)
      if (savedContext) {
        context.value = savedContext
      }
    }
  } catch {
    // Keep current task state; next poll can recover.
  }
}

onMounted(() => {
  taskTimer = window.setInterval(() => {
    now.value = Date.now()
    if (activeTaskCount.value) {
      void pollTasks()
    }
  }, 2000)
  void loadPage()
})

onBeforeUnmount(() => {
  if (taskTimer) {
    window.clearInterval(taskTimer)
  }
})
</script>

<template>
  <section class="page-section daily-review-page">
    <section class="surface-panel">
      <div class="surface-panel__content">
        <div class="section-header daily-review-header">
          <div v-if="!embedded">
            <p class="eyebrow">DAILY POSITION REVIEW</p>
            <h2 class="daily-review-title">每日持仓涨跌复盘</h2>
            <p class="panel-subtitle">账户涨跌归因、个股异动解释、风险提示和明日关注清单。</p>
          </div>
          <div v-else>
            <h3 class="panel-title">每日复盘</h3>
            <p class="panel-subtitle">账户涨跌归因、个股异动解释、风险提示和明日关注清单。</p>
          </div>
          <div class="daily-review-actions">
            <Tag :value="health?.llm_configured ? 'LLM READY' : 'LLM MISSING'" :class="health?.llm_configured ? 'p-tag--positive' : 'p-tag--negative'" />
            <Tag :value="health?.longbridge_configured ? 'LONGBRIDGE READY' : 'LONGBRIDGE LIMITED'" :class="health?.longbridge_configured ? 'p-tag--positive' : 'p-tag--accent'" />
            <Dropdown
              v-model="selectedDate"
              :options="dates"
              class="date-select"
              placeholder="选择日期"
              @change="loadSelectedDate(selectedDate)"
            />
            <div class="review-action-buttons">
              <Button
                label="复盘历史"
                icon="pi pi-history"
                class="p-button p-button--ghost history-button"
                type="button"
                @click="openHistory"
              />
              <Button
                :label="isGenerating ? '生成中' : review ? '重新生成' : '生成复盘'"
                :icon="isGenerating ? 'pi pi-spin pi-spinner' : 'pi pi-sparkles'"
                class="p-button p-button--accent generate-button"
                :disabled="isGenerating || !selectedDate"
                @click="generateReview(Boolean(review))"
              />
            </div>
          </div>
        </div>
      </div>
    </section>

    <LoadingBlock v-if="loading" />
    <template v-else-if="errorMessage && !context && !contextLoading">
      <ErrorBlock :message="errorMessage" />
    </template>

    <template v-else>
      <ErrorBlock v-if="errorMessage" :message="errorMessage" />

      <section v-if="contextLoading || reviewLoading" class="surface-panel">
        <div class="surface-panel__content">
          <LoadingBlock />
          <p class="panel-subtitle" style="text-align:center;margin-top:8px;">
            {{ contextLoading ? '加载持仓上下文…' : '加载复盘报告…' }}
          </p>
        </div>
      </section>

      <template v-if="context">

      <section v-if="visibleTasks.length" class="surface-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h3 class="panel-title">后台任务</h3>
              <p class="panel-subtitle">报告生成完成后会自动刷新。</p>
            </div>
          </div>
          <div class="runner-list">
            <div v-for="task in visibleTasks" :key="task.id" class="runner-item" :class="`runner-item--${task.status}`">
              <button type="button" class="runner-item__summary" @click="toggleTask(task)">
                <span class="runner-item__dot" aria-hidden="true"></span>
                <div class="runner-item__main">
                  <strong>{{ task.label }}</strong>
                  <span>{{ taskStage(task) }}</span>
                </div>
                <div class="runner-item__meta">
                  <Tag :value="taskStatusLabel(task.status)" :class="task.status === 'failed' ? 'p-tag--negative' : task.status === 'completed' ? 'p-tag--positive' : 'p-tag--accent'" />
                  <span>{{ taskElapsedSeconds(task) }}s</span>
                  <span class="pi" :class="expandedTaskId === task.id ? 'pi-chevron-up' : 'pi-chevron-down'" />
                </div>
              </button>
              <AgentTaskGraph
                v-if="expandedTaskId === task.id && !task.id.startsWith('local-')"
                :task="task"
                :expanded="expandedTaskId === task.id"
                @snapshot="mergeTaskGraphSnapshot"
              />
              <div v-if="expandedTaskId === task.id && task.result_id" class="runner-item__actions">
                <Button type="button" label="查看报告" size="small" severity="secondary" @click.stop="viewTaskResult(task)" />
              </div>
            </div>
          </div>
        </div>
      </section>

      <section v-if="historyVisible" class="surface-panel history-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h3 class="panel-title">复盘历史</h3>
              <p class="panel-subtitle">按单个交易日查看已归档的每日持仓复盘。</p>
            </div>
            <Button icon="pi pi-times" class="p-button p-button--ghost history-close-button" aria-label="关闭复盘历史" @click="historyVisible = false" />
          </div>
          <LoadingBlock v-if="historyLoading" />
          <div v-else-if="historyItems.length" class="history-list">
            <button
              v-for="item in historyItems"
              :key="item.id"
              type="button"
              class="history-row"
              :class="{ 'history-row--active': item.report_date === selectedDate }"
              @click="chooseHistoryDate(item.report_date)"
            >
              <span class="history-row__radio" aria-hidden="true"></span>
              <span>
                <strong>{{ item.report_date }}</strong>
                <small>{{ item.summary }}</small>
              </span>
              <Tag :value="item.report_date === selectedDate ? '当前' : '查看'" :class="item.report_date === selectedDate ? 'p-tag--positive' : 'p-tag--accent'" />
            </button>
          </div>
          <div v-else class="empty-state">还没有可查看的历史复盘。</div>
        </div>
      </section>

      <section class="overview-grid">
        <article class="surface-panel overview-card overview-card--wide">
          <div class="surface-panel__content">
            <p class="eyebrow">{{ context.overview.report_date }}</p>
            <h3 :class="signedTone">{{ formatNumber(context.overview.daily_pnl) }}</h3>
            <p>{{ context.overview.summary }}</p>
          </div>
        </article>
        <article class="surface-panel overview-card">
          <div class="surface-panel__content">
            <span>当日收益率</span>
            <strong :class="signedTone">{{ formatRawPct(context.overview.daily_return_percent) }}</strong>
          </div>
        </article>
        <article class="surface-panel overview-card">
          <div class="surface-panel__content">
            <span>总权益</span>
            <strong>{{ formatNumber(context.overview.total_equity) }}</strong>
          </div>
        </article>
        <article class="surface-panel overview-card">
          <div class="surface-panel__content">
            <span>现金比例</span>
            <strong>{{ formatPct(context.overview.cash_ratio) }}</strong>
          </div>
        </article>
      </section>

      <section class="surface-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h3 class="panel-title">LLM 复盘报告</h3>
              <p class="panel-subtitle">LLM 只解释和归因，确定性数字来自后端计算。</p>
            </div>
          </div>

          <div v-if="review" class="report-grid">
            <article>
              <h4>今日账户结论</h4>
              <p>{{ review.account_conclusion }}</p>
            </article>
            <article>
              <h4>涨跌归因</h4>
              <p>{{ review.attribution_summary }}</p>
            </article>
            <article>
              <h4>市场和行业背景</h4>
              <p>{{ review.market_context }}</p>
            </article>
            <article>
              <h4>风险变化</h4>
              <p>{{ review.risk_analysis }}</p>
            </article>
            <article>
              <h4>操作观察建议</h4>
              <p>{{ review.operation_observation }}</p>
            </article>
            <article>
              <h4>明日关注清单</h4>
              <ul class="plain-list">
                <li v-for="(item, index) in review.tomorrow_watchlist" :key="index">
                  <strong>{{ textValue(item, 'symbol') || '观察项' }}</strong>
                  {{ textValue(item, 'reason') }} {{ textValue(item, 'conditions') }}
                </li>
              </ul>
            </article>
          </div>
          <div v-else class="empty-state">还没有生成这一天的 LLM 复盘报告。</div>
        </div>
      </section>

      <AgentEvidencePanel
        v-if="review"
        :metadata="review.metadata"
        :evidence-summary="review.evidence_summary"
        :run-trace-summary="review.run_trace_summary"
      />

      <section class="review-layout">
        <section class="surface-panel">
          <div class="surface-panel__content">
            <div class="section-header">
              <div>
                <h3 class="panel-title">贡献 Top 5</h3>
                <p class="panel-subtitle">按对账户当日盈亏的真实贡献排序。</p>
              </div>
            </div>
            <div class="ranking-list">
              <div v-for="item in topContributors" :key="item.symbol" class="ranking-row">
                <div>
                  <strong>{{ item.symbol }}</strong>
                  <span>{{ item.name ?? item.normalized_symbol }}</span>
                </div>
                <div>
                  <strong :class="itemTone(item)">{{ formatNumber(item.daily_pnl) }}</strong>
                  <span>{{ formatPct(item.contribution_ratio) }} / {{ formatRawPct(item.daily_change_percent) }}</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section class="surface-panel">
          <div class="surface-panel__content">
            <div class="section-header">
              <div>
                <h3 class="panel-title">拖累 Top 5</h3>
                <p class="panel-subtitle">仓位影响优先于单纯涨跌幅。</p>
              </div>
            </div>
            <div class="ranking-list">
              <div v-for="item in topDrags" :key="item.symbol" class="ranking-row">
                <div>
                  <strong>{{ item.symbol }}</strong>
                  <span>{{ item.name ?? item.normalized_symbol }}</span>
                </div>
                <div>
                  <strong :class="itemTone(item)">{{ formatNumber(item.daily_pnl) }}</strong>
                  <span>{{ formatPct(item.contribution_ratio) }} / {{ formatRawPct(item.daily_change_percent) }}</span>
                </div>
              </div>
            </div>
          </div>
        </section>
      </section>

      <section class="review-layout review-layout--wide">
        <section class="surface-panel">
          <div class="surface-panel__content">
            <div class="section-header">
              <div>
                <h3 class="panel-title">仓位风险</h3>
                <p class="panel-subtitle">当前账户偏{{ context.risk.account_posture ?? '未知' }}，最大持仓下跌 5% 对账户影响约 {{ formatRawPct(context.risk.max_position_down_5pct_account_impact_percent) }}。</p>
              </div>
            </div>
            <div class="risk-grid">
              <div>
                <span>最大单一持仓</span>
                <strong>{{ formatPct(context.risk.max_single_position_weight) }}</strong>
              </div>
              <div>
                <span>前三大持仓</span>
                <strong>{{ formatPct(context.risk.top3_weight) }}</strong>
              </div>
              <div>
                <span>前五大持仓</span>
                <strong>{{ formatPct(context.risk.top5_weight) }}</strong>
              </div>
              <div>
                <span>半导体/AI/科技</span>
                <strong>{{ formatPct(context.risk.semiconductor_ai_tech_weight) }}</strong>
              </div>
            </div>
            <ul class="plain-list">
              <li v-for="item in context.risk.risk_flags" :key="item">{{ item }}</li>
              <li v-if="!context.risk.risk_flags.length">暂无明显集中度警报。</li>
            </ul>
          </div>
        </section>

        <section class="surface-panel">
          <div class="surface-panel__content">
            <div class="section-header">
              <div>
                <h3 class="panel-title">指数对比</h3>
                <p class="panel-subtitle">{{ context.benchmarks.beta_alpha_note }}</p>
              </div>
            </div>
            <div class="benchmark-grid">
              <div v-for="item in context.benchmarks.items" :key="item.symbol">
                <span>{{ item.symbol }}</span>
                <strong :class="(item.account_excess_return_percent ?? 0) >= 0 ? 'metric-positive' : 'metric-negative'">
                  {{ formatRawPct(item.account_excess_return_percent) }}
                </strong>
                <small>指数 {{ formatRawPct(item.return_percent) }}</small>
              </div>
            </div>
          </div>
        </section>
      </section>

      <section class="surface-panel">
        <div class="surface-panel__content">
          <div class="section-header">
            <div>
              <h3 class="panel-title">当前仓位 Top 5</h3>
              <p class="panel-subtitle">用于观察账户集中度和主要风险来源。</p>
            </div>
          </div>
          <div class="position-table">
            <div class="position-table__head">
              <span>股票</span><span>市值</span><span>权重</span><span>当日盈亏</span><span>浮盈亏</span>
            </div>
            <div v-for="item in topWeights" :key="item.symbol" class="position-table__row">
              <span><strong>{{ item.symbol }}</strong><small>{{ item.name }}</small></span>
              <span>{{ formatNumber(item.market_value) }}</span>
              <span>{{ formatPct(item.weight) }}</span>
              <span :class="itemTone(item)">{{ formatNumber(item.daily_pnl) }}</span>
              <span :class="(item.unrealized_pnl ?? 0) >= 0 ? 'metric-positive' : 'metric-negative'">{{ formatNumber(item.unrealized_pnl) }}</span>
            </div>
          </div>
        </div>
      </section>
      </template>
    </template>
  </section>
</template>

<style scoped>
.daily-review-title {
  margin: 0;
  font-size: 1.55rem;
}

.daily-review-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  align-items: center;
  gap: 10px;
  max-width: min(900px, 100%);
}

.date-select {
  width: 180px;
}

.review-action-buttons {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 10px;
  width: 220px;
}

:deep(.generate-button) {
  width: 100%;
  min-width: 0;
  height: 44px;
  min-height: 44px;
  max-height: 44px;
  justify-content: center;
  white-space: nowrap;
}

:deep(.history-button) {
  width: 100%;
  min-width: 0;
  height: 44px;
  min-height: 44px;
  max-height: 44px;
  justify-content: center;
  white-space: nowrap;
}

:deep(.generate-button .p-button-label),
:deep(.history-button .p-button-label) {
  overflow: visible;
  white-space: nowrap;
}

:deep(.history-close-button) {
  width: 40px;
  min-width: 40px;
  height: 40px;
  padding: 0;
}

.history-panel {
  border-color: rgba(87, 182, 255, 0.2);
}

.history-list {
  display: grid;
  gap: 10px;
}

.history-row {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  width: 100%;
  padding: 12px 14px;
  border: 1px solid rgba(129, 160, 207, 0.12);
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.58);
  color: var(--color-text-primary);
  text-align: left;
  cursor: pointer;
}

.history-row--active {
  border-color: rgba(87, 182, 255, 0.45);
  background: rgba(87, 182, 255, 0.1);
}

.history-row__radio {
  width: 14px;
  height: 14px;
  border: 1px solid rgba(171, 198, 235, 0.6);
  border-radius: 999px;
}

.history-row--active .history-row__radio {
  border: 4px solid var(--color-accent);
}

.history-row span:nth-child(2) {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.history-row small {
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.overview-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) repeat(3, minmax(160px, 0.7fr));
  gap: var(--space-4);
}

.overview-card h3 {
  margin: 0;
  font-size: 2.4rem;
}

.overview-card p {
  margin: 8px 0 0;
  color: var(--color-text-secondary);
}

.overview-card span,
.ranking-row span,
.risk-grid span,
.benchmark-grid span,
.benchmark-grid small {
  color: var(--color-text-secondary);
}

.overview-card strong {
  display: block;
  margin-top: 8px;
  font-size: 1.55rem;
}

.review-layout {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-4);
}

.review-layout--wide {
  grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.8fr);
}

.ranking-list,
.runner-list {
  display: grid;
  gap: 10px;
}

.ranking-row,
.runner-item,
.risk-grid > div,
.benchmark-grid > div,
.report-grid article {
  border: 1px solid rgba(129, 160, 207, 0.12);
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.58);
}

.ranking-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  padding: 14px;
}

.ranking-row > div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.ranking-row > div:last-child {
  text-align: right;
}

.runner-item {
  width: 100%;
  padding: 12px 14px;
  border: 1px solid rgba(129, 160, 207, 0.14);
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.48);
}

.runner-item__summary {
  display: grid;
  grid-template-columns: 12px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--color-text-primary);
  cursor: pointer;
  text-align: left;
}

.runner-item__dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: var(--color-accent);
}

.runner-item--queued .runner-item__dot,
.runner-item--running .runner-item__dot {
  animation: runner-pulse 1.2s ease-in-out infinite;
}

.runner-item--completed .runner-item__dot {
  background: var(--color-positive);
}

.runner-item--failed .runner-item__dot {
  background: var(--color-negative);
}

.runner-item__main {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.runner-item__main span,
.runner-item__meta span {
  color: var(--color-text-secondary);
}

.runner-item__meta {
  display: flex;
  align-items: center;
  gap: 10px;
}

.runner-item__actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 10px;
}

@keyframes runner-pulse {
  0%,
  100% {
    opacity: 0.45;
  }
  50% {
    opacity: 1;
  }
}

.risk-grid,
.benchmark-grid,
.report-grid {
  display: grid;
  gap: var(--space-3);
}

.risk-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.risk-grid > div,
.benchmark-grid > div,
.report-grid article {
  display: grid;
  gap: 6px;
  padding: 14px;
}

.benchmark-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.position-table {
  display: grid;
  gap: 8px;
}

.position-table__head,
.position-table__row {
  display: grid;
  grid-template-columns: minmax(160px, 1.3fr) repeat(4, minmax(90px, 1fr));
  gap: 12px;
  align-items: center;
}

.position-table__head {
  color: var(--color-text-secondary);
  font-size: 0.82rem;
}

.position-table__row {
  padding: 12px 14px;
  border: 1px solid rgba(129, 160, 207, 0.12);
  border-radius: var(--radius-md);
  background: rgba(10, 18, 32, 0.58);
}

.position-table__row span:first-child {
  display: grid;
  gap: 3px;
}

.position-table__row small {
  color: var(--color-text-secondary);
  overflow-wrap: anywhere;
}

.report-grid {
  grid-template-columns: minmax(0, 1fr);
}

.report-grid h4 {
  margin: 0;
}

.report-grid p {
  margin: 0;
  color: var(--color-text-secondary);
  line-height: 1.7;
}

.plain-list {
  margin: 12px 0 0;
  padding-left: 18px;
  color: var(--color-text-secondary);
  line-height: 1.7;
}

@media (max-width: 980px) {
  .daily-review-header,
  .review-layout,
  .review-layout--wide,
  .overview-grid,
  .report-grid {
    grid-template-columns: 1fr;
  }

  .daily-review-header {
    display: grid;
  }

  .daily-review-actions {
    justify-content: flex-start;
  }

  .review-action-buttons {
    width: min(260px, 100%);
  }

  .risk-grid,
  .benchmark-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .position-table {
    overflow-x: auto;
  }

  .position-table__head,
  .position-table__row {
    min-width: 720px;
  }
}
</style>
