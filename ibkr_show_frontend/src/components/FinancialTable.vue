<script setup lang="ts">
import type { SymbolFinancialsResponse } from '@/types/symbolAnalysis'

const props = defineProps<{
  financials: SymbolFinancialsResponse
  metricLabels: Record<string, string>
  formatValue: (key: string, value: number | null | undefined) => string
  formatChange: (key: string, value: number | null | undefined, previous: number | null | undefined) => string | null
  compact?: boolean
}>()

function periodChange(key: string, periodIndex: number, offset: number): string | null {
  const current = props.financials.periods[periodIndex]?.metrics[key]
  const previous = props.financials.periods[periodIndex + offset]?.metrics[key]
  return props.formatChange(key, current, previous)
}
</script>

<template>
  <div class="financial-table-wrap">
    <table class="financial-table" :class="{ 'financial-table--compact': compact }">
      <thead>
        <tr>
          <th>指标</th>
          <th v-for="period in financials.periods" :key="period.label">{{ period.label }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(label, key) in metricLabels" :key="key">
          <td>{{ label }}</td>
          <td v-for="(period, periodIndex) in financials.periods" :key="`${key}-${period.label}`">
            <span class="financial-table__value">{{ formatValue(String(key), period.metrics[String(key)]) }}</span>
            <span v-if="periodChange(String(key), periodIndex, 1)" class="financial-table__change">
              环比 {{ periodChange(String(key), periodIndex, 1) }}
            </span>
            <span v-if="periodChange(String(key), periodIndex, 4)" class="financial-table__change">
              同比 {{ periodChange(String(key), periodIndex, 4) }}
            </span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.financial-table-wrap {
  overflow-x: auto;
}

.financial-table {
  width: 100%;
  min-width: 760px;
  border-collapse: collapse;
}

.financial-table--compact {
  min-width: 620px;
}

.financial-table th,
.financial-table td {
  padding: 10px 12px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
  text-align: right;
  white-space: nowrap;
}

.financial-table__value,
.financial-table__change {
  display: block;
}

.financial-table__change {
  margin-top: 3px;
  color: var(--color-text-secondary);
  font-size: 0.72rem;
}

.financial-table th:first-child,
.financial-table td:first-child {
  position: sticky;
  left: 0;
  z-index: 1;
  text-align: left;
  background: rgba(15, 31, 52, 0.96);
}

.financial-table th {
  color: var(--color-text-secondary);
  font-size: 0.82rem;
  font-weight: 600;
}
</style>
