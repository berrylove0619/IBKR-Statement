<script setup lang="ts">
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import Tag from 'primevue/tag'

import type { TradeItem } from '@/types/trades'

defineProps<{
  items: TradeItem[]
  formatNumber: (value: number | null, digits?: number) => string
  sortKey: 'proceeds' | 'fifo_pnl_realized' | null
  sortOrder: 'asc' | 'desc'
  onSort: (key: 'proceeds' | 'fifo_pnl_realized') => void
}>()

const emit = defineEmits<{
  reviewTrade: [tradeId: string]
}>()

function formatSide(value: string | null): string {
  if (value === 'BUY') {
    return '买入'
  }
  if (value === 'SELL') {
    return '卖出'
  }
  return value ?? '--'
}

function sideClass(value: string | null): string {
  if (value === 'BUY') {
    return 'p-tag--positive'
  }
  if (value === 'SELL') {
    return 'p-tag--negative'
  }
  return 'p-tag--accent'
}

function pnlClass(value: number | null): string {
  if (value === null || value === 0) {
    return 'table-pnl--neutral'
  }
  return value > 0 ? 'table-pnl--positive' : 'table-pnl--negative'
}

function reviewTradeId(data: TradeItem): string {
  return data.trade_id || data.transaction_id || ''
}

async function copyTradeId(data: TradeItem): Promise<void> {
  const value = reviewTradeId(data)
  if (!value) {
    return
  }
  await navigator.clipboard.writeText(value)
}

function reviewThisTrade(data: TradeItem): void {
  const value = reviewTradeId(data)
  if (value) {
    emit('reviewTrade', value)
  }
}

function sortLabel(key: 'proceeds' | 'fifo_pnl_realized'): string {
  return key === 'proceeds' ? '成交金额' : '已实现盈亏'
}

function sortIndicator(
  activeKey: 'proceeds' | 'fifo_pnl_realized' | null,
  activeOrder: 'asc' | 'desc',
  key: 'proceeds' | 'fifo_pnl_realized',
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
        <div class="empty-state">当前筛选条件下没有交易数据</div>
      </template>

      <Column header="成交时间" headerClass="table-head--left table-col--datetime" bodyClass="table-col--datetime">
        <template #body="{ data }">
          <div class="table-symbol">
            <span class="table-symbol__code">{{ data.date_time ?? '--' }}</span>
            <span class="table-symbol__desc">{{ data.trade_date ?? '--' }}</span>
          </div>
        </template>
      </Column>

      <Column header="复盘ID" headerClass="table-head--left table-col--review-id" bodyClass="table-col--review-id">
        <template #body="{ data }">
          <div v-if="reviewTradeId(data)" class="review-id-cell">
            <button type="button" class="review-id-value" title="点击复制复盘 ID" @click="copyTradeId(data)">
              <code>{{ reviewTradeId(data) }}</code>
            </button>
            <button type="button" class="review-id-copy" title="跳转到单笔交易复盘" @click="reviewThisTrade(data)">复盘本交易</button>
          </div>
          <span v-else class="terminal-muted">--</span>
        </template>
      </Column>

      <Column header="代码" headerClass="table-head--left table-col--symbol" bodyClass="table-col--symbol">
        <template #body="{ data }">
          <div class="table-symbol">
            <span class="table-symbol__code">{{ data.symbol ?? '--' }}</span>
            <span class="table-symbol__desc">{{ data.description ?? '无名称' }}</span>
          </div>
        </template>
      </Column>

      <Column header="资产类型" headerClass="table-head--center table-col--asset" bodyClass="table-col--asset">
        <template #body="{ data }">
          <Tag :value="data.asset_class ?? '--'" class="p-tag p-tag--accent" />
        </template>
      </Column>

      <Column header="方向" headerClass="table-head--center table-col--side" bodyClass="table-col--side">
        <template #body="{ data }">
          <Tag :value="formatSide(data.buy_sell)" class="p-tag" :class="sideClass(data.buy_sell)" />
        </template>
      </Column>

      <Column header="数量" headerClass="table-head--number table-col--qty" bodyClass="table-number table-col--qty">
        <template #body="{ data }">
          <span class="cell-number">{{ formatNumber(data.quantity, 4) }}</span>
        </template>
      </Column>

      <Column header="成交价" headerClass="table-head--number table-col--price" bodyClass="table-number table-col--price">
        <template #body="{ data }">
          <span class="cell-number">{{ formatNumber(data.trade_price, 2) }}</span>
        </template>
      </Column>

      <Column headerClass="table-head--number table-col--value" bodyClass="table-number table-col--value">
        <template #header>
          <button type="button" class="sort-button" @click="onSort('proceeds')">
            <span>{{ sortLabel('proceeds') }}</span>
            <span class="sort-button__indicator">{{ sortIndicator(sortKey, sortOrder, 'proceeds') }}</span>
          </button>
        </template>
        <template #body="{ data }">
          <span class="cell-number">{{ formatNumber(data.proceeds, 2) }}</span>
        </template>
      </Column>

      <Column header="佣金" headerClass="table-head--number table-col--fee" bodyClass="table-number table-col--fee">
        <template #body="{ data }">
          <span class="cell-number" :class="pnlClass(data.ib_commission)">
            {{ formatNumber(data.ib_commission, 4) }}
          </span>
        </template>
      </Column>

      <Column headerClass="table-head--number table-col--pnl" bodyClass="table-number table-col--pnl">
        <template #header>
          <button type="button" class="sort-button" @click="onSort('fifo_pnl_realized')">
            <span>{{ sortLabel('fifo_pnl_realized') }}</span>
            <span class="sort-button__indicator">{{ sortIndicator(sortKey, sortOrder, 'fifo_pnl_realized') }}</span>
          </button>
        </template>
        <template #body="{ data }">
          <span class="cell-number" :class="pnlClass(data.fifo_pnl_realized)">
            {{ formatNumber(data.fifo_pnl_realized, 2) }}
          </span>
        </template>
      </Column>

      <Column header="交易所" headerClass="table-head--left table-col--exchange" bodyClass="table-col--exchange">
        <template #body="{ data }">
          <span class="terminal-muted">{{ data.exchange ?? '--' }}</span>
        </template>
      </Column>
    </DataTable>
  </div>

  <div class="mobile-data-list">
    <article v-for="item in items" :key="reviewTradeId(item) || `${item.date_time}-${item.symbol}`" class="mobile-data-card">
      <div class="mobile-data-card__header">
        <div class="mobile-data-card__title">
          <strong>{{ item.symbol ?? '--' }}</strong>
          <small>{{ item.description ?? '无名称' }}</small>
        </div>
        <Tag :value="formatSide(item.buy_sell)" class="p-tag" :class="sideClass(item.buy_sell)" />
      </div>

      <div class="mobile-data-grid">
        <div class="mobile-data-row">
          <span>成交时间</span>
          <strong>{{ item.date_time ?? item.trade_date ?? '--' }}</strong>
        </div>
        <div class="mobile-data-row">
          <span>数量</span>
          <strong>{{ formatNumber(item.quantity, 4) }}</strong>
        </div>
        <div class="mobile-data-row">
          <span>成交价</span>
          <strong>{{ formatNumber(item.trade_price, 2) }}</strong>
        </div>
        <div class="mobile-data-row">
          <span>成交金额</span>
          <strong>{{ formatNumber(item.proceeds, 2) }}</strong>
        </div>
        <div class="mobile-data-row">
          <span>佣金</span>
          <strong :class="pnlClass(item.ib_commission)">{{ formatNumber(item.ib_commission, 4) }}</strong>
        </div>
        <div class="mobile-data-row">
          <span>已实现盈亏</span>
          <strong :class="pnlClass(item.fifo_pnl_realized)">{{ formatNumber(item.fifo_pnl_realized, 2) }}</strong>
        </div>
      </div>

      <div class="mobile-data-row">
        <span>交易所</span>
        <strong>{{ item.exchange ?? '--' }}</strong>
      </div>
      <button v-if="reviewTradeId(item)" type="button" class="review-id-copy mobile-review-button" @click="reviewThisTrade(item)">复盘本交易</button>
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

.sort-button__indicator {
  color: var(--color-accent-strong);
  font-size: 0.88rem;
}

.review-id-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.review-id-value {
  display: inline-flex;
  min-width: 0;
  max-width: 118px;
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  padding: 0;
}

.review-id-value code {
  max-width: 112px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-primary);
}

.review-id-value:hover code {
  color: var(--color-accent-strong);
}

.review-id-copy {
  flex: 0 0 auto;
  border: 1px solid rgba(86, 213, 255, 0.22);
  border-radius: 8px;
  background: rgba(18, 31, 52, 0.82);
  color: var(--color-accent-strong);
  cursor: pointer;
  font-size: 0.78rem;
  padding: 4px 8px;
  white-space: nowrap;
}

.review-id-copy:hover {
  border-color: rgba(86, 213, 255, 0.42);
  background: rgba(24, 40, 66, 0.94);
}

.mobile-review-button {
  justify-self: start;
}
</style>
