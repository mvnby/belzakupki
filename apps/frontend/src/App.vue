<template>
  <div v-if="isAuthPage || isLandingPage" class="auth-wrapper">
    <router-view />
  </div>
  <div v-else class="app-layout">
    <!-- Sidebar -->
    <aside class="sidebar">
      <div class="logo-section">
        <div class="logo-icon">BZ</div>
        <div class="logo-text"><span class="gradient-text">BelZakupki</span></div>
      </div>
      
      <ul class="sidebar-menu">
        <li class="menu-item">
          <router-link to="/dashboard" class="menu-link" active-class="active">
            <span class="menu-icon">📊</span>
            Панель управления
          </router-link>
        </li>
        <!-- Admin Menu Items -->
        <template v-if="store.user?.role === 'admin'">
          <li class="menu-item">
            <router-link to="/admin" class="menu-link" active-class="active">
              <span class="menu-icon">🛠️</span>
              Админ-Панель
            </router-link>
          </li>
        </template>
        <!-- Manager (Subscriber) Menu Items -->
        <template v-else>
          <li class="menu-item">
            <router-link to="/profiles" class="menu-link" active-class="active">
              <span class="menu-icon">🔍</span>
              Профили поиска
            </router-link>
          </li>
          <li class="menu-item">
            <router-link to="/matches" class="menu-link" active-class="active">
              <span class="menu-icon">🎯</span>
              Совпадения
            </router-link>
          </li>
          <li class="menu-item">
            <router-link to="/analytics" class="menu-link" active-class="active">
              <span class="menu-icon">📈</span>
              Аналитика рынка
            </router-link>
          </li>
          <li class="menu-item">
            <router-link to="/crm-settings" class="menu-link" active-class="active">
              <span class="menu-icon">💼</span>
              Интеграция CRM
            </router-link>
          </li>
        </template>
      </ul>

      <!-- User Profile Card -->
      <div class="user-profile-section" v-if="store.user">
        <div class="user-details">
          <div class="username" :title="store.user.full_name || store.user.email">
            {{ store.user.full_name || store.user.email }}
          </div>
          <div class="company-name" :title="store.tenant?.name || 'Моя организация'">
            {{ store.tenant?.name || 'Моя организация' }}
          </div>
          <div class="plan-badge-wrapper" v-if="store.tenant?.plan && store.user?.role !== 'admin'">
            <span :class="['plan-badge', store.tenant.plan]">{{ store.tenant.plan === 'free' ? 'Гость' : store.tenant.plan }}</span>
          </div>
        </div>
        <button @click="handleLogout" class="logout-btn" title="Выйти">
          🚪
        </button>
      </div>
    </aside>

    <!-- Main Viewport -->
    <main class="app-content">
      <!-- Loading spinner -->
      <div v-if="store.isLoading" class="global-loader">
        <div class="spinner"></div>
      </div>
      
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { store } from './store.js'

const route = useRoute()
const router = useRouter()

const isAuthPage = computed(() => {
  return route.name === 'Login' || route.name === 'Register'
})

const isLandingPage = computed(() => {
  return route.name === 'Landing'
})

const handleLogout = () => {
  store.setToken('')
  router.push({ name: 'Landing' })
}
</script>

<style>
.auth-wrapper {
  min-height: 100vh;
  width: 100%;
}

.global-loader {
  position: fixed;
  top: 1.5rem;
  right: 1.5rem;
  z-index: 2000;
  background: rgba(11, 17, 32, 0.8);
  border: 1px solid var(--border-card);
  backdrop-filter: blur(8px);
  padding: 0.5rem;
  border-radius: 50%;
  box-shadow: var(--shadow-glow);
}

.spinner {
  width: 20px;
  height: 20px;
  border: 2px solid rgba(59, 130, 246, 0.2);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Page transitions */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Plan Badges in Sidebar */
.plan-badge-wrapper {
  margin-top: 0.25rem;
}

.plan-badge {
  font-size: 0.7rem;
  font-weight: 700;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  text-transform: uppercase;
  display: inline-block;
}

.plan-badge.free {
  background: rgba(156, 163, 175, 0.15);
  color: #9ca3af;
  border: 1px solid rgba(156, 163, 175, 0.3);
}

.plan-badge.starter {
  background: rgba(59, 130, 246, 0.15);
  color: #3b82f6;
  border: 1px solid rgba(59, 130, 246, 0.3);
}

.plan-badge.professional {
  background: rgba(139, 92, 246, 0.15);
  color: #8b5cf6;
  border: 1px solid rgba(139, 92, 246, 0.3);
}

.plan-badge.enterprise {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
  border: 1px solid rgba(245, 158, 11, 0.3);
}
</style>
