<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'

import { fetchBootstrapStatus, initializeBootstrap } from '@/api/bootstrap'
import { loginWithCredentials } from '@/auth/session'
import { resetBootstrapStatusCache } from '@/router'

const router = useRouter()
const username = ref('admin')
const password = ref('')
const confirmPassword = ref('')
const error = ref('')
const loading = ref(false)
const checking = ref(true)

onMounted(async () => {
  try {
    const status = await fetchBootstrapStatus()
    if (status.initialized) {
      await router.replace('/')
      return
    }
  } catch {
    error.value = '无法检查系统初始化状态，请确认后端服务已启动。'
  } finally {
    checking.value = false
  }
})

async function handleSubmit(): Promise<void> {
  error.value = ''

  const trimmedUsername = username.value.trim()
  if (!trimmedUsername) {
    error.value = '用户名不能为空'
    return
  }
  if (password.value.length < 8) {
    error.value = '密码长度不能少于 8 位'
    return
  }
  if (password.value !== confirmPassword.value) {
    error.value = '两次输入的密码不一致'
    return
  }

  loading.value = true
  try {
    await initializeBootstrap({ username: trimmedUsername, password: password.value })
    resetBootstrapStatusCache()
    await loginWithCredentials(trimmedUsername, password.value)
    await router.replace('/admin/ibkr')
  } catch (err) {
    error.value = err instanceof Error ? err.message : '初始化失败，请稍后重试'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="bootstrap-page">
    <section class="bootstrap-card">
      <div class="bootstrap-card__header">
        <p class="eyebrow">WELCOME</p>
        <h1 class="bootstrap-card__title">欢迎使用 IBKR Show</h1>
        <p class="bootstrap-card__subtitle">首次使用，请创建管理员账号</p>
      </div>

      <div v-if="checking" class="bootstrap-card__loading">正在检查系统状态…</div>

      <form v-else class="bootstrap-card__form" @submit.prevent="handleSubmit">
        <label class="field-stack">
          <span class="field-stack__label">用户名</span>
          <InputText v-model="username" type="text" autocomplete="username" />
        </label>
        <label class="field-stack">
          <span class="field-stack__label">密码</span>
          <InputText v-model="password" type="password" autocomplete="new-password" placeholder="至少 8 位" />
        </label>
        <label class="field-stack">
          <span class="field-stack__label">确认密码</span>
          <InputText v-model="confirmPassword" type="password" autocomplete="new-password" />
        </label>
        <p v-if="error" class="bootstrap-card__error">{{ error }}</p>
        <Button
          label="创建并进入系统"
          icon="pi pi-check"
          type="submit"
          class="p-button p-button--accent bootstrap-card__submit"
          :loading="loading"
        />
      </form>
    </section>
  </div>
</template>

<style scoped>
.bootstrap-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 2rem;
  background: var(--surface-ground, #f8f9fa);
}

.bootstrap-card {
  width: 100%;
  max-width: 400px;
  background: var(--surface-card, #ffffff);
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
  padding: 2rem;
}

.bootstrap-card__header {
  margin-bottom: 1.5rem;
}

.eyebrow {
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--primary-color, #3b82f6);
  margin-bottom: 0.25rem;
}

.bootstrap-card__title {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--text-color, #1e293b);
  margin: 0 0 0.25rem;
}

.bootstrap-card__subtitle {
  font-size: 0.9rem;
  color: var(--text-color-secondary, #64748b);
  margin: 0;
}

.bootstrap-card__loading {
  text-align: center;
  color: var(--text-color-secondary, #64748b);
  padding: 2rem 0;
}

.bootstrap-card__form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.field-stack {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.field-stack__label {
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--text-color, #1e293b);
}

.bootstrap-card__error {
  color: var(--red-500, #ef4444);
  font-size: 0.85rem;
  margin: 0;
}

.bootstrap-card__submit {
  margin-top: 0.5rem;
  width: 100%;
}
</style>
