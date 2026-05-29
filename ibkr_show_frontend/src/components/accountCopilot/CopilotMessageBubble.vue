<script setup lang="ts">
import Tag from 'primevue/tag'

import type { CopilotMessage, CopilotRun } from '@/types/accountCopilot'

defineProps<{
  message: CopilotMessage
  run?: CopilotRun
  selected?: boolean
}>()

const emit = defineEmits<{
  selectRun: [runId: string]
}>()

function statusSeverity(status?: string): 'success' | 'info' | 'warn' | 'danger' | 'secondary' {
  if (status === 'completed') return 'success'
  if (status === 'awaiting_approval') return 'warn'
  if (status === 'failed') return 'danger'
  if (status === 'cancelled') return 'secondary'
  if (status === 'running') return 'info'
  return 'secondary'
}

function statusLabel(status?: string): string {
  const labels: Record<string, string> = {
    queued: '排队中',
    running: '分析中',
    awaiting_approval: '等待审批',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return status ? labels[status] || status : ''
}
</script>

<template>
  <article class="message-row" :class="[`is-${message.role}`, { 'is-selected': selected }]">
    <div class="message-bubble" @click="run?.id && emit('selectRun', run.id)">
      <div class="message-bubble__meta">
        <span>{{ message.role === 'user' ? '你' : 'Account Copilot' }}</span>
        <Tag
          v-if="run"
          :value="statusLabel(run.status)"
          :severity="statusSeverity(run.status)"
          class="message-bubble__tag"
        />
      </div>
      <p class="message-bubble__content">{{ message.content }}</p>
    </div>
  </article>
</template>

<style scoped>
.message-row {
  display: flex;
  margin: 14px 0;
}

.message-row.is-user {
  justify-content: flex-end;
}

.message-row.is-assistant {
  justify-content: flex-start;
}

.message-bubble {
  max-width: min(720px, 84%);
  padding: 14px 16px;
  border: 1px solid rgba(125, 211, 252, 0.14);
  border-radius: 16px;
  background: rgba(15, 23, 42, 0.82);
  box-shadow: 0 16px 32px rgba(0, 0, 0, 0.18);
  cursor: default;
}

.is-user .message-bubble {
  color: #e0f2fe;
  background: linear-gradient(135deg, rgba(14, 116, 144, 0.82), rgba(37, 99, 235, 0.58));
}

.is-selected .message-bubble {
  border-color: rgba(34, 211, 238, 0.8);
}

.message-bubble__meta {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 6px;
  color: #93c5fd;
  font-size: 0.76rem;
}

.message-bubble__content {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.7;
}

.message-bubble__tag {
  transform: scale(0.88);
}
</style>
