<template>
  <div class="auth-container">
    <div class="glass-card auth-card">
      <div class="auth-header">
        <h1><span class="gradient-text">BelZakupki</span></h1>
        <p>Вход в личный кабинет</p>
      </div>

      <form @submit.prevent="handleLogin">
        <div class="form-group">
          <label class="form-label" for="email">E-mail</label>
          <input
            id="email"
            v-model="email"
            type="email"
            class="form-input"
            placeholder="name@company.by"
            required
            auto-complete="email"
          />
        </div>

        <div class="form-group">
          <label class="form-label" for="password">Пароль</label>
          <input
            id="password"
            v-model="password"
            type="password"
            class="form-input"
            placeholder="••••••••"
            required
            auto-complete="current-password"
          />
        </div>

        <div v-if="error" class="error-msg">
          {{ error }}
        </div>

        <button type="submit" class="btn btn-primary btn-block" :disabled="loading">
          {{ loading ? 'Вход...' : 'Войти' }}
        </button>
      </form>

      <div class="auth-footer">
        Нет аккаунта?
        <router-link to="/register" class="auth-link">Зарегистрироваться</router-link>
      </div>
    </div>
  </div>
</template>

<script>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { store } from '../store.js'

export default {
  name: 'Login',
  setup() {
    const email = ref('')
    const password = ref('')
    const error = ref('')
    const loading = ref(false)
    const router = useRouter()

    const handleLogin = async () => {
      error.value = ''
      loading.value = true

      try {
        const data = await store.fetch('/api/auth/login', {
          method: 'POST',
          body: JSON.stringify({
            email: email.value,
            password: password.value
          })
        })

        store.setToken(data.access_token)
        const success = await store.loadUser()
        if (success) {
          router.push({ name: 'Dashboard' })
        } else {
          error.value = 'Ошибка загрузки профиля'
        }
      } catch (err) {
        error.value = err.message || 'Ошибка входа'
      } finally {
        loading.value = false
      }
    }

    return {
      email,
      password,
      error,
      loading,
      handleLogin
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
