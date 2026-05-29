<script setup lang="ts">
import { computed, ref } from 'vue'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Tag from 'primevue/tag'
import type { CopilotSession } from '@/types/accountCopilot'

const MAX_VISIBLE = 6

const props = defineProps<{
  sessions: CopilotSession[]
  activeSessionId?: string
  loading?: boolean
  renameTitle: string
}>()

const emit = defineEmits<{
  create: []
  select: [sessionId: string]
  rename: []
  archive: []
  'update:renameTitle': [value: string]
}>()

const showAll = ref(false)

const activeIsHidden = computed(() => {
  if (!props.activeSessionId || showAll.value) return false
  const idx = props.sessions.findIndex((s) => s.id === props.activeSessionId)
  return idx >= MAX_VISIBLE
})

const visibleSessions = computed(() => {
  if (showAll.value || activeIsHidden.value) return props.sessions
  return props.sessions.slice(0, MAX_VISIBLE)
})

const hiddenCount = computed(() => Math.max(0, props.sessions.length - MAX_VISIBLE))

function toggleShowAll(): void {
  showAll.value = !showAll.value
}

function formatDate(value?: string | null): string {
  if (!value) return '--'
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}
</script>

<template>
  <aside class="session-sidebar">
    <div class="session-sidebar__header">
      <div>
        <p class="session-sidebar__eyebrow">Account Copilot</p>
        <h2>多会话</h2>
      </div>
      <Button icon="pi pi-plus" rounded aria-label="新建会话" @click="emit('create')" />
    </div>

    <div class="session-sidebar__editor">
      <InputText
        :model-value="renameTitle"
        placeholder="当前会话标题"
        @update:model-value="emit('update:renameTitle', String($event))"
      />
      <div class="session-sidebar__editor-actions">
        <Button label="重命名" icon="pi pi-pencil" size="small" @click="emit('rename')" />
        <Button label="归档" icon="pi pi-box" size="small" class="p-button p-button--ghost" @click="emit('archive')" />
      </div>
    </div>

    <div v-if="loading" class="session-sidebar__state">加载会话中...</div>
    <button
      v-for="session in visibleSessions"
      v-else
      :key="session.id"
      class="session-item"
      :class="{ 'is-active': session.id === activeSessionId, 'is-archived': session.status === 'archived' }"
      @click="emit('select', session.id)"
    >
      <span class="session-item__title">{{ session.title }}</span>
      <span class="session-item__meta">
        {{ formatDate(session.updated_at) }}
        <Tag v-if="session.status === 'archived'" value="archived" severity="secondary" />
      </span>
    </button>

    <button
      v-if="hiddenCount > 0 && !activeIsHidden"
      class="session-toggle"
      @click="toggleShowAll"
    >
      {{ showAll ? '收起历史会话' : `展开更多会话 (${hiddenCount})` }}
    </button>
  </aside>
</template>

<style scoped>
.session-sidebar {
  width: 280px;
  min-width: 280px;
  height: 100%;
  min-height: 0;
  flex-shrink: 0;
  border-right: 1px solid rgba(125, 211, 252, 0.14);
  background: rgba(2, 8, 23, 0.86);
  padding: 18px;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.session-sidebar__header {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}

.session-sidebar__header h2 {
  margin: 0;
}

.session-sidebar__eyebrow {
  margin: 0 0 4px;
  color: #22d3ee;
  font-size: 0.72rem;
  letter-spacing: 0;
  text-transform: uppercase;
}

.session-sidebar__editor {
  display: grid;
  gap: 10px;
  margin: 18px 0;
}

.session-sidebar__editor-actions {
  display: flex;
  gap: 8px;
}

.session-sidebar__state {
  color: #94a3b8;
}

.session-item {
  display: grid;
  width: 100%;
  gap: 8px;
  margin-bottom: 10px;
  padding: 12px;
  text-align: left;
  color: #e2e8f0;
  border: 1px solid rgba(125, 211, 252, 0.12);
  border-radius: 14px;
  background: rgba(15, 23, 42, 0.72);
  cursor: pointer;
}

.session-item.is-active {
  border-color: rgba(34, 211, 238, 0.78);
  background: rgba(14, 116, 144, 0.34);
}

.session-item.is-archived {
  opacity: 0.62;
}

.session-item__title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-item__meta {
  display: flex;
  justify-content: space-between;
  color: #94a3b8;
  font-size: 0.76rem;
}

.session-toggle {
  width: 100%;
  margin-top: 6px;
  padding: 10px;
  color: #7dd3fc;
  text-align: center;
  border: 1px dashed rgba(125, 211, 252, 0.22);
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.52);
  cursor: pointer;
  font-size: 0.82rem;
}

.session-toggle:hover {
  border-color: rgba(34, 211, 238, 0.55);
  background: rgba(14, 116, 144, 0.22);
}

@media (max-width: 820px) {
  .session-sidebar {
    width: auto;
    min-width: 0;
    max-height: 150px;
    border-right: 0;
    border-bottom: 1px solid rgba(125, 211, 252, 0.14);
  }
}
</style>
