<template>
  <div class="auth-container">
    <div class="glass-card auth-card">
      <div class="auth-header">
        <h1><span class="gradient-text">BelZakupki</span></h1>
        <p>Регистрация нового клиента</p>
      </div>

      <form @submit.prevent="handleRegister">
        <div class="form-group">
          <label class="form-label" for="tenant_name">Название компании</label>
          <input
            id="tenant_name"
            v-model="tenantName"
            type="text"
            class="form-input"
            placeholder="ООО Моя Компания"
            required
          />
        </div>

        <div class="form-group">
          <label class="form-label" for="full_name">ФИО представителя</label>
          <input
            id="full_name"
            v-model="fullName"
            type="text"
            class="form-input"
            placeholder="Иванов Иван Иванович"
            required
          />
        </div>

        <div class="form-group">
          <label class="form-label" for="email">E-mail</label>
          <input
            id="email"
            v-model="email"
            type="email"
            class="form-input"
            placeholder="name@company.by"
            required
          />
        </div>

        <div class="form-group">
          <label class="form-label" for="password">Пароль (мин. 6 символов)</label>
          <input
            id="password"
            v-model="password"
            type="password"
            class="form-input"
            placeholder="••••••••"
            required
            minlength="6"
          />
        </div>

        <div v-if="error" class="error-msg">
          {{ error }}
        </div>

        <button type="submit" class="btn btn-primary btn-block" :disabled="loading">
          {{ loading ? 'Регистрация...' : 'Зарегистрироваться' }}
        </button>
      </form>

      <div class="auth-footer">
        Уже зарегистрированы?
        <router-link to="/login" class="auth-link">Войти</router-link>
      </div>
    </div>
  </div>
</template>

<script>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { store } from '../store.js'

export default {
  name: 'Register',
  setup() {
    const tenantName = ref('')
    const fullName = ref('')
    const email = ref('')
    const password = ref('')
    const error = ref('')
    const loading = ref(false)
    const router = useRouter()

    const handleRegister = async () => {
      error.value = ''
      loading.value = true

      try {
        // 1. Register User and Tenant
        await store.fetch('/api/auth/register', {
          method: 'POST',
          body: JSON.stringify({
            email: email.value,
            password: password.value,
            full_name: fullName.value,
            tenant_name: tenantName.value
          })
        })

        // 2. Automatically Log In
        const loginData = await store.fetch('/api/auth/login', {
          method: 'POST',
          body: JSON.stringify({
            email: email.value,
            password: password.value
          })
        })

        store.setToken(loginData.access_token)
        const success = await store.loadUser()
        if (success) {
          router.push({ name: 'Dashboard' })
        } else {
          error.value = 'Ошибка загрузки профиля после входа'
        }
      } catch (err) {
        error.value = err.message || 'Ошибка регистрации'
      } finally {
        loading.value = false
      }
    }

    return {
      tenantName,
      fullName,
      email,
      password,
      error,
      loading,
      handleRegister
    }
  }
}
</script>

<style scoped>
.error-msg {
  background: var(--error-bg);
  color: var(--error);
  padding: 0.75rem 1rem;
  border-radius: var(--radius-md);
  margin-bottom: 1.25rem;
  font-size: 0.9rem;
  border: 1px solid rgba(244, 63, 94, 0.2);
}
.auth-footer {
  margin-top: 1.5rem;
  text-align: center;
  font-size: 0.9rem;
  color: var(--text-muted);
}
.auth-link {
  color: var(--primary);
  text-decoration: none;
  font-weight: 500;
  margin-left: 0.25rem;
}
.auth-link:hover {
  text-decoration: underline;
}
</style>
