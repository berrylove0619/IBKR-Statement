<script setup lang="ts">
import { ref } from 'vue'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'

defineProps<{
  visible: boolean
  header: string
}>()

const emit = defineEmits<{ 'update:visible': [value: boolean] }>()

const jsonBlocks = ref<Array<{ setCollapsed: (v: boolean) => void }>>([])

function registerBlock(block: { setCollapsed: (v: boolean) => void } | null): void {
  if (block && !jsonBlocks.value.includes(block)) {
    jsonBlocks.value.push(block)
  }
}

function expandAll(): void {
  jsonBlocks.value.forEach((b) => b.setCollapsed(false))
}

function collapseAll(): void {
  jsonBlocks.value.forEach((b) => b.setCollapsed(true))
}

function close(): void {
  emit('update:visible', false)
}

defineExpose({ registerBlock, expandAll, collapseAll })
</script>

<template>
  <Dialog
    :visible="visible"
    modal
    :header="header"
    class="harness-detail-dialog"
    :style="{ width: 'min(1340px, 92vw)', maxHeight: '90vh' }"
    :content-style="{ padding: 0, display: 'flex', flexDirection: 'column', maxHeight: 'calc(90vh - 64px)', overflow: 'hidden' }"
    @update:visible="emit('update:visible', $event)"
  >
    <template #header>
      <div class="harness-detail-dialog__header">
        <span class="harness-detail-dialog__title">{{ header }}</span>
        <div class="harness-detail-dialog__actions">
          <Button label="全部展开" icon="pi pi-angle-double-down" size="small" severity="secondary" @click="expandAll" />
          <Button label="全部折叠" icon="pi pi-angle-double-up" size="small" severity="secondary" @click="collapseAll" />
          <Button icon="pi pi-times" size="small" severity="secondary" rounded text @click="close" />
        </div>
      </div>
    </template>

    <div class="harness-detail-dialog__body">
      <slot :register-block="registerBlock" />
      <div class="harness-detail-dialog__footer">
        <Button label="关闭" icon="pi pi-times" severity="secondary" @click="close" />
      </div>
    </div>
  </Dialog>
</template>

<style>
/* Global overrides for the dialog — not scoped so they apply to PrimeVue portal */
.harness-detail-dialog .p-dialog-content {
  padding: 0 !important;
}
</style>

<style scoped>
.harness-detail-dialog__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}

.harness-detail-dialog__title {
  font-weight: 700;
  font-size: 1.05rem;
}

.harness-detail-dialog__actions {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-shrink: 0;
}

.harness-detail-dialog__body {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 18px 20px;
  display: grid;
  gap: var(--space-4);
}

.harness-detail-dialog__footer {
  display: flex;
  justify-content: flex-end;
  padding-top: 8px;
  border-top: 1px solid rgba(129, 160, 207, 0.12);
  margin-top: 4px;
}
</style>
