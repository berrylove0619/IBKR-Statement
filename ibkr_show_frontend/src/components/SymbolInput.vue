<script setup lang="ts">
import { ref, watch } from 'vue'
import AutoComplete from 'primevue/autocomplete'
import { fetchSymbolSuggestions } from '@/api/symbols'
import type { SymbolSuggestion, SymbolCorrection } from '@/api/symbols'

const props = withDefaults(
  defineProps<{
    modelValue: string
    placeholder?: string
    required?: boolean
  }>(),
  { placeholder: '', required: false },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  correct: [correction: SymbolCorrection]
}>()

const suggestions = ref<SymbolSuggestion[]>([])
const correction = ref<SymbolCorrection | null>(null)
const loading = ref(false)
let debounceTimer: ReturnType<typeof setTimeout> | null = null

watch(
  () => props.modelValue,
  () => {
    correction.value = null
  },
)

async function onInput(event: { value: string }) {
  const q = event.value?.trim() ?? ''
  emit('update:modelValue', event.value ?? '')

  if (debounceTimer) clearTimeout(debounceTimer)
  if (q.length < 1) {
    suggestions.value = []
    correction.value = null
    return
  }

  debounceTimer = setTimeout(async () => {
    loading.value = true
    try {
      const result = await fetchSymbolSuggestions(q)
      suggestions.value = result.suggestions
      correction.value = result.corrected
    } catch {
      suggestions.value = []
      correction.value = null
    } finally {
      loading.value = false
    }
  }, 300)
}

function onSelect(event: { value: string | SymbolSuggestion }) {
  const val = event.value
  if (typeof val === 'string') {
    emit('update:modelValue', val)
  } else if (val && typeof val === 'object' && 'symbol' in val) {
    emit('update:modelValue', val.symbol)
  }
  suggestions.value = []
  correction.value = null
}

function applyCorrection() {
  if (correction.value) {
    emit('update:modelValue', correction.value.symbol)
    emit('correct', correction.value)
    correction.value = null
    suggestions.value = []
  }
}

function fieldMethod(event: { query: string }) {
  return suggestions.value.map((s) => s.symbol)
}
</script>

<template>
  <div class="symbol-input-wrap">
    <AutoComplete
      :model-value="modelValue"
      :suggestions="suggestions.map((s) => s.symbol)"
      :loading="loading"
      :placeholder="placeholder"
      :force-selection="false"
      :delay="0"
      :min-length="1"
      dropdown
      @complete="fieldMethod"
      @item-select="onSelect"
      @update:model-value="(v: string) => onInput({ value: v })"
    />
    <p v-if="correction" class="symbol-input-correction">
      是否想输入
      <button type="button" class="symbol-input-correction__link" @click="applyCorrection">
        {{ correction.symbol }}
      </button>
      ？
      <span class="symbol-input-correction__reason">{{ correction.reason }}</span>
    </p>
  </div>
</template>

<style scoped>
.symbol-input-wrap {
  position: relative;
}

.symbol-input-correction {
  margin-top: 4px;
  font-size: 0.8rem;
  color: var(--color-text-secondary, #94a3b8);
}

.symbol-input-correction__link {
  background: none;
  border: none;
  color: #48a9ff;
  cursor: pointer;
  font-weight: 600;
  font-size: 0.8rem;
  padding: 0;
  text-decoration: underline;
}

.symbol-input-correction__link:hover {
  color: #7cc2ff;
}

.symbol-input-correction__reason {
  opacity: 0.7;
  margin-left: 4px;
}
</style>
