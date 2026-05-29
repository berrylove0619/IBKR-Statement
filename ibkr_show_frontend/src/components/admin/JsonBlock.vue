<script setup lang="ts">
import { computed, ref } from 'vue'
import { sanitizeJsonValue } from '@/utils/sanitizeJson'

const props = withDefaults(
  defineProps<{
    value: unknown
    collapsed?: boolean
    title?: string
  }>(),
  {
    collapsed: false,
    title: '',
  },
)

const collapsedState = ref(props.collapsed)

const jsonText = computed(() => JSON.stringify(sanitizeJsonValue(props.value ?? null), null, 2))
</script>

<template>
  <div class="json-block">
    <button v-if="title || collapsed" type="button" class="json-block__toggle" @click="collapsedState = !collapsedState">
      <span>{{ title || 'JSON' }}</span>
      <span class="pi" :class="collapsedState ? 'pi-chevron-down' : 'pi-chevron-up'" />
    </button>
    <pre v-if="!collapsedState">{{ jsonText }}</pre>
  </div>
</template>

<style scoped>
.json-block {
  min-width: 0;
}

.json-block__toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  margin-bottom: 8px;
  padding: 8px 10px;
  border: 1px solid rgba(129, 160, 207, 0.14);
  border-radius: var(--radius-sm);
  background: rgba(10, 18, 32, 0.6);
  color: var(--color-text-primary);
  cursor: pointer;
}

pre {
  max-height: 420px;
  margin: 0;
  padding: 12px;
  overflow: auto;
  border: 1px solid rgba(129, 160, 207, 0.14);
  border-radius: var(--radius-sm);
  background: rgba(4, 10, 20, 0.72);
  color: var(--color-text-secondary);
  font-size: 0.8rem;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
