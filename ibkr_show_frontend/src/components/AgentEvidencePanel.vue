<script setup lang="ts">
import { ref } from 'vue'
import Tag from 'primevue/tag'
import type { AgentMetadata, EvidenceSummary, RunTraceSummary } from '@/types/agentEvidence'

interface Props {
  metadata?: Record<string, unknown>
  evidenceSummary?: Record<string, unknown>
  runTraceSummary?: Record<string, unknown>
}

const props = defineProps<Props>()

const visible = ref(false)

const meta = props.metadata as AgentMetadata | undefined
const evidence = props.evidenceSummary as EvidenceSummary | undefined
const trace = props.runTraceSummary as RunTraceSummary | undefined

function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '--'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '--'
  return `${ms}ms`
}

function sectionStatusClass(status: string): string {
  if (status === 'available') return 'p-tag--positive'
  if (status === 'partial') return 'p-tag--accent'
  return 'p-tag--negative'
}
</script>

<template>
  <div v-if="meta || evidence || trace" class="agent-evidence-panel surface-panel">
    <div class="surface-panel__content">
      <button type="button" class="evidence-toggle" @click="visible = !visible">
        <span class="evidence-toggle__label">
          <span class="pi pi-database" style="font-size: 0.85rem; margin-right: 6px;" />
          Agent 运行信息
        </span>
        <span class="evidence-toggle__hint">{{ visible ? '收起' : '展开' }}</span>
        <span class="pi" :class="visible ? 'pi-chevron-up' : 'pi-chevron-down'" />
      </button>

      <div v-if="visible" class="evidence-body">
        <!-- metadata -->
        <div v-if="meta" class="evidence-section">
          <h4 class="evidence-section__title">Agent 版本信息</h4>
          <div class="evidence-meta-grid">
            <div class="evidence-meta-item">
              <span class="evidence-meta-item__label">Harness</span>
              <span class="evidence-meta-item__value">{{ meta.harness_version }}</span>
            </div>
            <div class="evidence-meta-item">
              <span class="evidence-meta-item__label">Agent</span>
              <span class="evidence-meta-item__value">{{ meta.agent_version }}</span>
            </div>
            <div class="evidence-meta-item">
              <span class="evidence-meta-item__label">Prompt</span>
              <span class="evidence-meta-item__value">{{ meta.prompt_version }}</span>
            </div>
            <div class="evidence-meta-item">
              <span class="evidence-meta-item__label">Schema</span>
              <span class="evidence-meta-item__value">{{ meta.schema_version }}</span>
            </div>
            <div class="evidence-meta-item">
              <span class="evidence-meta-item__label">Toolset</span>
              <span class="evidence-meta-item__value">{{ meta.toolset_version }}</span>
            </div>
            <div class="evidence-meta-item">
              <span class="evidence-meta-item__label">Mode</span>
              <span class="evidence-meta-item__value">{{ meta.agent_mode }}</span>
            </div>
            <div v-if="meta.model_provider_snapshot?.provider_name" class="evidence-meta-item">
              <span class="evidence-meta-item__label">LLM</span>
              <span class="evidence-meta-item__value">{{ meta.model_provider_snapshot.provider_name }} / {{ meta.model_provider_snapshot.model }}</span>
            </div>
            <div v-if="meta.generated_at" class="evidence-meta-item">
              <span class="evidence-meta-item__label">生成时间</span>
              <span class="evidence-meta-item__value evidence-meta-item__value--mono">{{ meta.generated_at }}</span>
            </div>
          </div>
        </div>

        <!-- evidence_summary sections -->
        <div v-if="evidence" class="evidence-section">
          <h4 class="evidence-section__title">证据来源</h4>
          <div class="evidence-sections-list">
            <div v-for="section in (evidence.evidence_sections as Array<{section: string, status: string, source: string, item_count: number, summary: string}>)" :key="section.section" class="evidence-section-row">
              <Tag :value="section.status" :class="sectionStatusClass(section.status)" />
              <span class="evidence-section-row__name">{{ section.section }}</span>
              <span class="evidence-section-row__source">{{ section.source }}</span>
              <span class="evidence-section-row__count">{{ section.item_count }} 项</span>
              <span class="evidence-section-row__summary">{{ section.summary }}</span>
            </div>
          </div>

          <div v-if="evidence.missing_data?.length" class="evidence-warnings">
            <p class="evidence-warning-label">缺失数据:</p>
            <span v-for="item in evidence.missing_data" :key="item" class="evidence-warning-item">{{ item }}</span>
          </div>

          <div v-if="evidence.data_limitations?.length" class="evidence-warnings">
            <p class="evidence-warning-label">数据局限:</p>
            <span v-for="item in evidence.data_limitations" :key="item" class="evidence-warning-item">{{ item }}</span>
          </div>

          <div v-if="evidence.budget_summary" class="evidence-budget">
            <span class="evidence-budget__label">上下文预算:</span>
            <span>{{ formatBytes(evidence.budget_summary.total_original_size) }} → {{ formatBytes(evidence.budget_summary.total_final_size) }}</span>
            <span v-if="evidence.budget_summary.truncated_sections?.length" class="evidence-budget__truncated">截断: {{ evidence.budget_summary.truncated_sections.join(', ') }}</span>
          </div>
        </div>

        <!-- run_trace_summary -->
        <div v-if="trace" class="evidence-section">
          <h4 class="evidence-section__title">工具调用摘要</h4>
          <div class="evidence-trace-grid">
            <div class="evidence-trace-stat">
              <span class="evidence-trace-stat__value">{{ trace.llm_rounds }}</span>
              <span class="evidence-trace-stat__label">LLM 轮次</span>
            </div>
            <div class="evidence-trace-stat">
              <span class="evidence-trace-stat__value">{{ trace.tool_call_count }}</span>
              <span class="evidence-trace-stat__label">工具调用</span>
            </div>
            <div class="evidence-trace-stat evidence-trace-stat--ok">
              <span class="evidence-trace-stat__value">{{ trace.tool_success_count }}</span>
              <span class="evidence-trace-stat__label">成功</span>
            </div>
            <div v-if="trace.tool_error_count > 0" class="evidence-trace-stat evidence-trace-stat--error">
              <span class="evidence-trace-stat__value">{{ trace.tool_error_count }}</span>
              <span class="evidence-trace-stat__label">失败</span>
            </div>
            <div v-if="trace.llm_started && trace.llm_finished" class="evidence-trace-stat">
              <span class="evidence-trace-stat__value">{{ formatMs((trace.llm_finished as number) - (trace.llm_started as number)) }}</span>
              <span class="evidence-trace-stat__label">总耗时</span>
            </div>
            <div v-if="trace.truncated_observations > 0" class="evidence-trace-stat evidence-trace-stat--warn">
              <span class="evidence-trace-stat__value">{{ trace.truncated_observations }}</span>
              <span class="evidence-trace-stat__label">截断观察</span>
            </div>
          </div>

          <div v-if="trace.tools?.length" class="evidence-tools-list">
            <div v-for="tool in trace.tools" :key="tool.tool" class="evidence-tool-row" :class="tool.ok ? '' : 'evidence-tool-row--error'">
              <Tag :value="tool.ok ? 'OK' : 'ERR'" :class="tool.ok ? 'p-tag--positive' : 'p-tag--negative'" />
              <span class="evidence-tool-row__name">{{ tool.tool }}</span>
              <span class="evidence-tool-row__summary">{{ tool.summary }}</span>
              <span v-if="tool.original_size" class="evidence-tool-row__size">{{ formatBytes(tool.original_size) }} → {{ formatBytes(tool.final_size) }}</span>
              <Tag v-if="tool.truncated" value="截断" class="p-tag--accent" />
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agent-evidence-panel {
  margin-top: var(--space-3);
}

.evidence-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  color: var(--color-text-secondary);
  font-size: 0.85rem;
}

.evidence-toggle:hover {
  color: var(--color-text-primary);
}

.evidence-toggle__label {
  display: flex;
  align-items: center;
  font-weight: 500;
}

.evidence-toggle__hint {
  margin-left: auto;
  font-size: 0.8rem;
}

.evidence-body {
  margin-top: var(--space-3);
  display: grid;
  gap: var(--space-3);
}

.evidence-section {
  display: grid;
  gap: 8px;
}

.evidence-section__title {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0;
}

.evidence-meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 6px;
}

.evidence-meta-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  background: rgba(129, 160, 207, 0.06);
  border-radius: var(--radius-sm);
}

.evidence-meta-item__label {
  font-size: 0.72rem;
  color: var(--color-text-secondary);
  text-transform: uppercase;
}

.evidence-meta-item__value {
  font-size: 0.82rem;
  color: var(--color-text-primary);
  font-weight: 500;
}

.evidence-meta-item__value--mono {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.78rem;
}

.evidence-sections-list {
  display: grid;
  gap: 4px;
}

.evidence-section-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  background: rgba(129, 160, 207, 0.04);
  font-size: 0.82rem;
}

.evidence-section-row__name {
  font-weight: 500;
  min-width: 140px;
}

.evidence-section-row__source {
  color: var(--color-text-secondary);
  min-width: 80px;
}

.evidence-section-row__count {
  color: var(--color-text-secondary);
  min-width: 50px;
}

.evidence-section-row__summary {
  color: var(--color-text-secondary);
  flex: 1;
}

.evidence-warnings {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.evidence-warning-label {
  font-size: 0.8rem;
  color: var(--color-text-secondary);
  margin: 0;
}

.evidence-warning-item {
  font-size: 0.78rem;
  padding: 2px 8px;
  background: rgba(239, 83, 80, 0.1);
  color: var(--color-negative);
  border-radius: var(--radius-sm);
}

.evidence-budget {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.8rem;
  color: var(--color-text-secondary);
}

.evidence-budget__label {
  font-weight: 500;
}

.evidence-budget__truncated {
  color: var(--color-accent);
}

.evidence-trace-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.evidence-trace-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 16px;
  background: rgba(129, 160, 207, 0.06);
  border-radius: var(--radius-sm);
  min-width: 80px;
}

.evidence-trace-stat--ok .evidence-trace-stat__value {
  color: var(--color-positive);
}

.evidence-trace-stat--error .evidence-trace-stat__value {
  color: var(--color-negative);
}

.evidence-trace-stat--warn .evidence-trace-stat__value {
  color: var(--color-accent);
}

.evidence-trace-stat__value {
  font-size: 1.2rem;
  font-weight: 700;
  color: var(--color-text-primary);
}

.evidence-trace-stat__label {
  font-size: 0.72rem;
  color: var(--color-text-secondary);
  text-transform: uppercase;
}

.evidence-tools-list {
  display: grid;
  gap: 4px;
}

.evidence-tool-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  background: rgba(129, 160, 207, 0.04);
  font-size: 0.82rem;
}

.evidence-tool-row--error {
  background: rgba(239, 83, 80, 0.06);
}

.evidence-tool-row__name {
  font-weight: 500;
  min-width: 200px;
}

.evidence-tool-row__summary {
  color: var(--color-text-secondary);
  flex: 1;
}

.evidence-tool-row__size {
  font-size: 0.75rem;
  color: var(--color-text-secondary);
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
}
</style>