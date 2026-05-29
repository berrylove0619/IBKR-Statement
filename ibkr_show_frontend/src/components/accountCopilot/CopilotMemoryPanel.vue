<script setup lang="ts">
import Button from 'primevue/button'
import Dropdown from 'primevue/dropdown'
import Tag from 'primevue/tag'
import type { CopilotMemory } from '@/types/accountCopilot'

defineProps<{
  memories: CopilotMemory[]
  loading?: boolean
  rebuilding?: boolean
  memoryType: string
}>()

const emit = defineEmits<{
  rebuild: []
  'update:memoryType': [value: string]
}>()

const filters = [
  { label: 'all', value: 'all' },
  { label: 'conversation_segment', value: 'conversation_segment' },
  { label: 'pinned_fact', value: 'pinned_fact' },
  { label: 'tool_fact', value: 'tool_fact' },
  { label: 'skill_fact', value: 'skill_fact' },
  { label: 'constraint', value: 'constraint' },
]
</script>

<template>
  <section class="memory-panel">
    <div class="memory-panel__toolbar">
      <div>
        <p class="memory-panel__eyebrow">Session Memory</p>
        <h3>记忆</h3>
      </div>
      <Button icon="pi pi-refresh" label="重建" size="small" :loading="rebuilding" @click="emit('rebuild')" />
    </div>
    <Dropdown
      :model-value="memoryType"
      :options="filters"
      option-label="label"
      option-value="value"
      class="memory-panel__filter"
      @update:model-value="emit('update:memoryType', String($event))"
    />
    <div v-if="loading" class="memory-panel__empty">加载记忆中...</div>
    <div v-else-if="memories.length === 0" class="memory-panel__empty">暂无结构化记忆。</div>
    <article v-for="memory in memories" v-else :key="memory.id" class="memory-card">
      <div class="memory-card__top">
        <Tag :value="memory.memory_type" severity="info" />
        <span>{{ memory.source_message_ids?.length || 0 }} messages</span>
      </div>
      <p class="memory-card__summary">{{ memory.summary || '--' }}</p>
      <div class="memory-card__tags">
        <span v-for="symbol in memory.symbols" :key="symbol">{{ symbol }}</span>
        <span v-for="topic in memory.topics" :key="topic">{{ topic }}</span>
      </div>
      <p v-if="memory.user_intent" class="memory-card__intent">{{ memory.user_intent }}</p>
      <details>
        <summary>facts / preferences / open questions</summary>
        <div class="memory-card__details">
          <strong>重要事实</strong>
          <ul><li v-for="item in memory.important_facts" :key="item">{{ item }}</li></ul>
          <strong>用户偏好</strong>
          <ul><li v-for="item in memory.user_preferences" :key="item">{{ item }}</li></ul>
          <strong>开放问题</strong>
          <ul><li v-for="item in memory.open_questions" :key="item">{{ item }}</li></ul>
          <strong>不可压缩约束</strong>
          <ul><li v-for="item in memory.non_compressible_constraints" :key="item">{{ item }}</li></ul>
        </div>
      </details>
    </article>
  </section>
</template>

<style scoped>
.memory-panel {
  display: grid;
  gap: 12px;
}

.memory-panel__toolbar {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}

.memory-panel__toolbar h3 {
  margin: 0;
}

.memory-panel__eyebrow {
  margin: 0 0 4px;
  color: #22d3ee;
  font-size: 0.72rem;
  text-transform: uppercase;
}

.memory-panel__filter {
  width: 100%;
}

.memory-panel__empty,
.memory-card {
  padding: 12px;
  border: 1px solid rgba(125, 211, 252, 0.14);
  border-radius: 14px;
  background: rgba(15, 23, 42, 0.58);
}

.memory-panel__empty {
  color: #94a3b8;
}

.memory-card__top {
  display: flex;
  justify-content: space-between;
  color: #94a3b8;
  font-size: 0.78rem;
}

.memory-card__summary {
  color: #e2e8f0;
  line-height: 1.55;
}

.memory-card__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.memory-card__tags span {
  padding: 3px 8px;
  color: #a5f3fc;
  border-radius: 999px;
  background: rgba(14, 116, 144, 0.34);
  font-size: 0.72rem;
}

.memory-card__intent,
summary,
.memory-card__details {
  color: #94a3b8;
  font-size: 0.78rem;
}

ul {
  padding-left: 18px;
}
</style>
