<template>
  <div class="admin-dashboard-view">
    <div class="page-header">
      <div class="page-title">
        <h2>Панель администратора</h2>
        <p>Мониторинг работоспособности парсеров, управление клиентами и просмотр общей очереди тендеров.</p>
      </div>
    </div>

    <!-- Quick Metrics Cards -->
    <div class="grid-stats" v-if="stats">
      <div class="glass-card stat-card">
        <div class="stat-icon primary">👥</div>
        <div class="stat-info">
          <span class="stat-value">{{ stats.user_count }}</span>
          <span class="stat-label">Пользователей</span>
        </div>
      </div>
      <div class="glass-card stat-card">
        <div class="stat-icon info">🏢</div>
        <div class="stat-info">
          <span class="stat-value">{{ stats.tenant_count }}</span>
          <span class="stat-label">Организаций</span>
        </div>
      </div>
      <div class="glass-card stat-card">
        <div class="stat-icon success">📋</div>
        <div class="stat-info">
          <span class="stat-value">{{ stats.tender_count }}</span>
          <span class="stat-label">Всего тендеров</span>
        </div>
      </div>
      <div class="glass-card stat-card">
        <div class="stat-icon warning">🎯</div>
        <div class="stat-info">
          <span class="stat-value">{{ stats.match_count }}</span>
          <span class="stat-label">Всего совпадений</span>
        </div>
      </div>
    </div>

    <!-- Dashboard Tabs -->
    <div class="status-tabs">
      <button 
        v-for="tab in tabs" 
        :key="tab.value" 
        :class="['tab-btn', { active: activeTab === tab.value }]"
        @click="activeTab = tab.value"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- Tab 1: General Tenders Queue -->
    <div v-if="activeTab === 'queue'" class="glass-card matches-card">
      <div style="padding: 1.5rem; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border-card);">
        <h3 style="font-size: 1.15rem; font-weight: 600;">Общая лента парсинга (база тендеров)</h3>
        <div class="search-input-wrapper" style="width: 320px;">
          <input 
            type="text" 
            v-model="searchQuery" 
            @input="debouncedSearch" 
            class="form-input" 
            placeholder="Поиск по названию или УНП..." 
          />
          <span v-if="searchQuery" @click="clearSearch" class="clear-search-btn">×</span>
        </div>
      </div>

      <div class="table-container" v-if="tenders.length > 0">
        <table class="custom-table">
          <thead>
            <tr>
              <th>Источник</th>
              <th>Заголовок</th>
              <th>Заказчик</th>
              <th>Дедлайн</th>
              <th>Статус</th>
              <th>Собрано</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in tenders" :key="t.id">
              <td>
                <span class="source-tag">{{ t.source_name || t.source }}</span>
              </td>
              <td>
                <a :href="t.url" target="_blank" class="tender-title-link" :title="t.title">
                  {{ truncateText(t.title, 80) }}
                </a>
              </td>
              <td>
                <span class="customer-name" :title="t.customer_name">{{ truncateText(t.customer_name || 'Не указан', 35) }}</span>
              </td>
              <td>{{ formatDate(t.deadline_at) || 'Не указан' }}</td>
              <td>
                <span :class="['status-badge', t.status]">{{ formatStatus(t.status) }}</span>
              </td>
              <td style="font-size: 0.8rem; color: var(--text-muted);">{{ formatDateTime(t.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-state" style="padding: 4rem; text-align: center;">
        <div class="empty-icon">📂</div>
        <h3>Тендеры не найдены</h3>
        <p>Общая очередь пока пуста или нет подходящих результатов поиска.</p>
      </div>

      <div class="pagination-bar" v-if="tenders.length > 0">
        <button @click="prevPage" :disabled="offset === 0" class="btn btn-secondary btn-sm">◄ Назад</button>
        <span class="pagination-info">Показано {{ offset + 1 }} - {{ offset + tenders.length }}</span>
        <button @click="nextPage" :disabled="tenders.length < limit" class="btn btn-secondary btn-sm">Вперед ►</button>
      </div>
    </div>

    <!-- Tab 2: Crawler Activity -->
    <div v-if="activeTab === 'crawlers'" class="glass-card matches-card" style="padding: 1.5rem;">
      <h3 style="font-size: 1.15rem; font-weight: 600; margin-bottom: 1.5rem;">Источники и активность парсеров</h3>
      <div class="table-container" v-if="stats && stats.sources">
        <table class="custom-table">
          <thead>
            <tr>
              <th>Площадка</th>
              <th>Код источника</th>
              <th>Всего собрано тендеров</th>
              <th>Последний запуск</th>
              <th>Статус парсера</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="src in stats.sources" :key="src.code">
              <td><strong>{{ src.name }}</strong></td>
              <td><code>{{ src.code }}</code></td>
              <td>{{ src.total_tenders }}</td>
              <td>{{ src.latest_fetch ? formatDateTime(src.latest_fetch) : 'Никогда' }}</td>
              <td>
                <span class="status-badge" style="background: rgba(16, 185, 129, 0.15); color: #10b981;">
                  Активен (OK)
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Tab 3: Tenants & Subscriptions -->
    <div v-if="activeTab === 'tenants'" class="glass-card matches-card" style="padding: 1.5rem;">
      <h3 style="font-size: 1.15rem; font-weight: 600; margin-bottom: 1.5rem;">Клиенты и тарифные планы</h3>
      <div class="table-container" v-if="stats && stats.tenants">
        <table class="custom-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Компания (Tenant)</th>
              <th>Тариф подписки</th>
              <th>Использовано ИИ кредитов</th>
              <th>Активных профилей</th>
              <th>Дата регистрации</th>
              <th>Статус</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="tenant in stats.tenants" :key="tenant.id">
              <td><code>#{{ tenant.id }}</code></td>
              <td><strong>{{ tenant.name }}</strong></td>
              <td>
                <span :class="['plan-badge', tenant.plan]" style="text-transform: uppercase; font-weight: 700; font-size: 0.75rem; padding: 0.2rem 0.5rem; border-radius: 4px;">
                  {{ tenant.plan }}
                </span>
              </td>
              <td>{{ tenant.ai_credits_used }}</td>
              <td>{{ tenant.active_profiles }}</td>
              <td>{{ formatDate(tenant.created_at) }}</td>
              <td>
                <span :class="['status-badge', tenant.is_active ? 'accepted' : 'rejected']">
                  {{ tenant.is_active ? 'Активен' : 'Заблокирован' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Tab 4: System Logs -->
    <div v-if="activeTab === 'logs'" class="glass-card matches-card" style="padding: 1.5rem;">
      <h3 style="font-size: 1.15rem; font-weight: 600; margin-bottom: 1rem;">Лог-поток парсинга системы</h3>
      <div class="logs-console">
        <div v-for="(log, idx) in (stats?.logs || [])" :key="idx" class="log-line">
          <span class="log-time">[{{ formatDateTime(log.timestamp) }}]</span>
          <span :class="['log-level', log.level.toLowerCase()]">{{ log.level }}</span>
          <span class="log-msg">{{ log.message }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { store } from '../store.js'

const stats = ref(null)
const tenders = ref([])
const activeTab = ref('queue')
const searchQuery = ref('')
const limit = ref(20)
const offset = ref(0)

const tabs = [
  { label: 'Общая очередь', value: 'queue' },
  { label: 'Статус парсеров', value: 'crawlers' },
  { label: 'Клиенты и подписки', value: 'tenants' },
  { label: 'Логи воркера', value: 'logs' }
]

const loadAdminStats = async () => {
  try {
    stats.value = await store.fetch('/api/admin/stats')
  } catch (e) {
    console.error('Failed to load admin stats:', e)
  }
}

const loadTenders = async () => {
  try {
    let url = `/api/tenders?limit=${limit.value}&offset=${offset.value}`
    if (searchQuery.value) {
      url += `&q=${encodeURIComponent(searchQuery.value)}`
    }
    const res = await store.fetch(url)
    tenders.value = res.items
  } catch (e) {
    console.error('Failed to load tenders:', e)
  }
}

let searchTimeout = null
const debouncedSearch = () => {
  if (searchTimeout) clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => {
    offset.value = 0
    loadTenders()
  }, 350)
}

const clearSearch = () => {
  searchQuery.value = ''
  offset.value = 0
  loadTenders()
}

const nextPage = () => {
  offset.value += limit.value
  loadTenders()
}

const prevPage = () => {
  if (offset.value >= limit.value) {
    offset.value -= limit.value
    loadTenders()
  }
}

const truncateText = (text, len) => {
  if (!text) return ''
  return text.length > len ? text.substring(0, len) + '...' : text
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr)
    return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
  } catch {
    return dateStr
  }
}

const formatDateTime = (dateStr) => {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr)
    return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) + ' ' + d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
  } catch {
    return dateStr
  }
}

const formatStatus = (status) => {
  const mapping = {
    'posted': 'Размещен',
    'closed': 'Архив',
    'canceled': 'Отменен',
    'in_work': 'В работе'
  }
  return mapping[status] || status
}

onMounted(() => {
  loadAdminStats()
  loadTenders()
})
</script>

<style scoped>
.admin-dashboard-view {
  animation: 0.4s ease-out fadeIn;
}

.stat-icon {
  font-size: 2rem;
  margin-right: 1rem;
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

.logs-console {
  background: rgba(0, 0, 0, 0.6);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-md);
  font-family: 'Courier New', Courier, monospace;
  padding: 1rem;
  max-height: 400px;
  overflow-y: auto;
  color: #10b981;
}

.log-line {
  margin-bottom: 0.4rem;
  font-size: 0.85rem;
  line-height: 1.4;
}

.log-time {
  color: var(--text-muted);
  margin-right: 0.5rem;
}

.log-level {
  font-weight: bold;
  margin-right: 0.5rem;
}

.log-level.info {
  color: #3b82f6;
}

.log-level.warn {
  color: #f59e0b;
}

.log-level.error {
  color: #ef4444;
}
</style>
