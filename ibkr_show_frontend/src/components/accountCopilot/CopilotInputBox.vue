<script setup lang="ts">
import { ref, watch } from 'vue'
import Button from 'primevue/button'
import Textarea from 'primevue/textarea'

const props = defineProps<{
  modelValue: string
  loading?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  send: []
}>()

const draft = ref(props.modelValue)

watch(
  () => props.modelValue,
  (value) => {
    draft.value = value
  },
)

watch(draft, (value) => emit('update:modelValue', value))

function submit(): void {
  if (props.loading || !draft.value.trim()) return
  emit('send')
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    submit()
  }
}
</script>

<template>
  <div class="copilot-input">
    <Textarea
      v-model="draft"
      rows="3"
      auto-resize
      class="copilot-input__textarea"
      placeholder="问问你的 IBKR 账户、持仓、交易、风险或公开市场信息..."
      :disabled="loading"
      @keydown="handleKeydown"
    />
    <Button
      icon="pi pi-send"
      label="发送"
      class="copilot-input__button"
      :loading="loading"
      :disabled="loading || !draft.trim()"
      @click="submit"
    />
  </div>
</template>

<style scoped>
.copilot-input {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 12px;
  align-items: end;
  padding: 14px;
  border: 1px solid rgba(125, 211, 252, 0.18);
  border-radius: 16px;
  background: rgba(7, 16, 32, 0.86);
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.22);
}

.copilot-input__textarea {
  width: 100%;
  color: #dff7ff;
  border-color: rgba(125, 211, 252, 0.22);
  background: rgba(15, 23, 42, 0.78);
}

.copilot-input__button {
  min-width: 96px;
}

@media (max-width: 720px) {
  .copilot-input {
    grid-template-columns: 1fr;
  }
}
</style>
