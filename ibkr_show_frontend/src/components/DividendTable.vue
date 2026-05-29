<script setup lang="ts">
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import Tag from 'primevue/tag'

import type { DividendItem } from '@/types/dividends'

defineProps<{
  items: DividendItem[]
  formatNumber: (value: number | null, digits?: number) => string
  sortKey: 'date_time' | 'ex_date' | 'amount' | null
  sortOrder: 'asc' | 'desc'
  onSort: (key: 'date_time' | 'ex_date' | 'amount') => void
}>()

function amountClass(value: number | null): string {
  if (value === null || value === 0) {
    return 'table-pnl--neutral'
  }
  return value > 0 ? 'table-pnl--positive' : 'table-pnl--negative'
}

function flowTypeLabel(value: string | null): string {
  if (value === 'Dividends' || value === 'Ordinary Dividend') {
    return '股息'
  }
  if (value === 'Withholding Tax') {
    return '预扣税'
  }
  if (value?.includes('Payment In Lieu')) {
    return 'PIL'
  }
  return value ?? '--'
}

function flowTypeClass(value: string | null): string {
  if (value === 'Withholding Tax') {
    return 'p-tag--negative'
  }
  if (value?.includes('Payment In Lieu')) {
    return 'p-tag--accent'
  }
  if (value?.includes('Dividend')) {
    return 'p-tag--positive'
  }
  return 'p-tag--accent'
}

function sortLabel(key: 'date_time' | 'ex_date' | 'amount'): string {
  if (key === 'date_time') {
    return '到账时间'
  }
  if (key === 'ex_date') {
    return '除息日'
  }
  return '金额'
}

function sortIndicator(
  activeKey: 'date_time' | 'ex_date' | 'amount' | null,
  activeOrder: 'asc' | 'desc',
  key: 'date_time' | 'ex_date' | 'amount',
): string {
  if (activeKey !== key) {
    return '↕'
  }
  return activeOrder === 'desc' ? '↓' : '↑'
}
</script>

<template>
  <div class="table-shell table-shell--desktop">
    <DataTable :value="items" class="terminal-datatable">
      <template #empty>
        <div class="empty-state">当前筛选条件下没有股息记录</div>
      </template>

      <Column headerClass="table-head--left table-col--datetime" bodyClass="table-col--datetime">
        <template #header>
          <button type="button" class="sort-button sort-button--left" @click="onSort('date_time')">
            <span>{{ sortLabel('date_time') }}</span>
            <span class="sort-button__indicator">{{ sortIndicator(sortKey, sortOrder, 'date_time') }}</span>
          </button>
        </template>
        <template #body="{ data }">
          <div class="table-symbol">
            <span class="table-symbol__code">{{ data.date_time ?? '--' }}</span>
            <span class="table-symbol__desc">{{ data.settle_date ?? data.report_date ?? '--' }}</span>
          </div>
        </template>
      </Column>

      <Column headerClass="table-head--left table-col--price" bodyClass="table-col--price">
        <template #header>
          <button type="button" class="sort-button sort-button--left" @click="onSort('ex_date')">
            <span>{{ sortLabel('ex_date') }}</span>
            <span class="sort-button__indicator">{{ sortIndicator(sortKey, sortOrder, 'ex_date') }}</span>
          </button>
        </template>
        <template #body="{ data }">
          <span class="terminal-muted">{{ data.ex_date ?? '--' }}</span>
        </template>
      </Column>

      <Column header="标的" headerClass="table-head--left table-col--symbol" bodyClass="table-col--symbol">
        <template #body="{ data }">
          <div class="table-symbol">
            <span class="table-symbol__code">{{ data.symbol ?? '--' }}</span>
            <span class="table-symbol__desc">{{ data.description ?? '--' }}</span>
          </div>
        </template>
      </Column>

      <Column header="类型" headerClass="table-head--center table-col--asset" bodyClass="table-col--asset">
        <template #body="{ data }">
          <Tag :value="flowTypeLabel(data.flow_type)" class="p-tag" :class="flowTypeClass(data.flow_type)" />
        </template>
      </Column>

      <Column header="币种" headerClass="table-head--center table-col--side" bodyClass="table-col--side">
        <template #body="{ data }">
          <Tag :value="data.currency ?? '--'" class="p-tag p-tag--accent" />
        </template>
      </Column>

      <Column headerClass="table-head--number table-col--value" bodyClass="table-number table-col--value">
        <template #header>
          <button type="button" class="sort-button" @click="onSort('amount')">
            <span>{{ sortLabel('amount') }}</span>
            <span class="sort-button__indicator">{{ sortIndicator(sortKey, sortOrder, 'amount') }}</span>
          </button>
        </template>
        <template #body="{ data }">
          <span class="cell-number" :class="amountClass(data.amount)">{{ formatNumber(data.amount, 2) }}</span>
        </template>
      </Column>
    </DataTable>
  </div>

  <div class="mobile-data-list">
    <article v-for="item in items" :key="item.transaction_id || `${item.date_time}-${item.symbol}-${item.amount}`" class="mobile-data-card">
      <div class="mobile-data-card__header">
        <div class="mobile-data-card__title">
          <strong>{{ item.symbol ?? '--' }}</strong>
          <small>{{ item.description ?? '--' }}</small>
        </div>
        <Tag :value="flowTypeLabel(item.flow_type)" class="p-tag" :class="flowTypeClass(item.flow_type)" />
      </div>

      <div class="mobile-data-grid">
        <div class="mobile-data-row">
          <span>金额</span>
          <strong :class="amountClass(item.amount)">{{ formatNumber(item.amount, 2) }}</strong>
        </div>
        <div class="mobile-data-row">
          <span>币种</span>
          <strong>{{ item.currency ?? '--' }}</strong>
        </div>
        <div class="mobile-data-row">
          <span>到账时间</span>
          <strong>{{ item.date_time ?? item.settle_date ?? '--' }}</strong>
        </div>
        <div class="mobile-data-row">
          <span>除息日</span>
          <strong>{{ item.ex_date ?? '--' }}</strong>
        </div>
      </div>
    </article>
  </div>
</template>

<style scoped>
.sort-button {
  width: 100%;
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.38rem;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  font-weight: 700;
  cursor: pointer;
  padding: 0;
}

.sort-button--left {
  justify-content: flex-start;
}

.sort-button__indicator {
  color: var(--color-accent-strong);
  font-size: 0.88rem;
}
</style>
