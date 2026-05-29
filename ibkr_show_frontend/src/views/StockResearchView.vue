<script setup lang="ts">
import { ref } from 'vue'
import ErrorBlock from '@/components/ErrorBlock.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import SymbolAnalysisPanel from '@/components/SymbolAnalysisPanel.vue'

const loading = ref(false)
const errorMessage = ref('')
</script>

<template>
  <section class="page-section stock-research-page">
    <section class="surface-panel">
      <div class="surface-panel__content">
        <div class="section-header">
          <div>
            <p class="eyebrow">AGENT</p>
            <h2 class="stock-research-title">标的研究</h2>
            <p class="panel-subtitle">查看标的财报、估值、行情和横向分析，为 AI 决策提供公开市场信息参考。</p>
          </div>
        </div>
      </div>
    </section>

    <LoadingBlock v-if="loading" />
    <ErrorBlock v-else-if="errorMessage" :message="errorMessage" />

    <template v-else>
      <SymbolAnalysisPanel />
    </template>
  </section>
</template>

<style scoped>
.stock-research-title {
  margin: 0;
  font-size: 1.55rem;
}
</style>
