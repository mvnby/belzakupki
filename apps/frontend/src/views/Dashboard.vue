<template>
  <div>
    <div class="page-header">
      <div class="page-title">
        <h2>Сводная панель</h2>
        <p>Добро пожаловать в систему мониторинга госзакупок BelZakupki.</p>
      </div>
      <div class="page-actions">
        <button
          @click="triggerIngest"
          class="btn btn-primary"
          :disabled="stats.tasks?.ingest === 'running' || store.tenant?.plan === 'free'"
          :title="store.tenant?.plan === 'free' ? 'Доступно только на платных тарифах' : ''"
        >
          <span class="btn-icon">⚡</span>
          {{ stats.tasks?.ingest === 'running' ? 'Сбор идет...' : 'Запустить сбор' }}
        </button>
        <button
          @click="triggerNotify"
          class="btn btn-secondary"
          :disabled="stats.tasks?.notify === 'running' || store.tenant?.plan === 'free'"
          :title="store.tenant?.plan === 'free' ? 'Доступно только на платных тарифах' : ''"
        >
          <span class="btn-icon">✉️</span>
          {{ stats.tasks?.notify === 'running' ? 'Рассылка...' : 'Рассылка Telegram' }}
        </button>
      </div>
    </div>

    <!-- Stats Grid -->
    <div class="grid-stats">
      <div class="glass-card stat-card">
        <div class="stat-icon info">📋</div>
        <div class="stat-info">
          <span class="stat-value">{{ stats.stats?.total_tenders ?? 0 }}</span>
          <span class="stat-label">Всего тендеров</span>
        </div>
      </div>
      <div class="glass-card stat-card">
        <div class="stat-icon primary">🔥</div>
        <div class="stat-info">
          <span class="stat-value">{{ stats.stats?.total_matches ?? 0 }}</span>
          <span class="stat-label">Совпадений</span>
        </div>
      </div>
      <div class="glass-card stat-card">
        <div class="stat-icon warning">✨</div>
        <div class="stat-info">
          <span class="stat-value">{{ stats.stats?.new_matches ?? 0 }}</span>
          <span class="stat-label">Новые (Неразобранные)</span>
        </div>
      </div>
      <div class="glass-card stat-card">
        <div class="stat-icon success">💬</div>
        <div class="stat-info">
          <span class="stat-value">{{ stats.stats?.sent_notifications ?? 0 }}</span>
          <span class="stat-label">Отправлено алертов</span>
        </div>
      </div>
    </div>

    <!-- Premium Upgrade Banner for Free Users -->
    <div v-if="store.tenant?.plan === 'free'" class="glass-card premium-upgrade-banner mt-3">
      <div class="banner-flex-container" style="display: flex; justify-content: space-between; align-items: center; gap: 1.5rem; flex-wrap: wrap;">
        <div class="banner-content" style="flex: 1; min-width: 280px;">
          <span class="banner-badge">🔑 Ознакомительный тариф</span>
          <h3>Активируйте тариф Starter или Pro</h3>
          <p>Вам доступен бесплатный режим: 1 поисковый профиль и локальное сопоставление ключевых слов. Обратитесь к администратору, чтобы подключить платный тариф и открыть ИИ-экспертизу ТЗ, ИИ чат-ассистента, экспорт в CRM и авто-оповещения в Telegram/Viber.</p>
        </div>
        <div class="banner-action">
          <router-link to="/landing#pricing" class="btn btn-primary" style="white-space: nowrap; box-shadow: 0 0 15px rgba(59, 130, 246, 0.4);">
            💎 Выбрать тариф
          </router-link>
        </div>
      </div>
    </div>

    <div class="dashboard-content-layout" style="margin-top: 1.5rem;">
      <!-- Welcome Panel -->
      <div class="glass-card welcome-panel">
        <h3>Состояние системы и источники</h3>
        <p class="desc">Система собирает данные с государственных и коммерческих электронных площадок:</p>
        
        <div class="sources-list">
          <div class="source-item">
            <span class="source-indicator active"></span>
            <div class="source-details">
              <strong>goszakupki.by</strong>
              <span>Государственные закупки</span>
            </div>
          </div>
          <div class="source-item">
            <span class="source-indicator active"></span>
            <div class="source-details">
              <strong>icetrade.by</strong>
              <span>Коммерческие и государственные закупки</span>
            </div>
          </div>
          <div class="source-item">
            <span class="source-indicator active"></span>
            <div class="source-details">
              <strong>zakupki.butb.by</strong>
              <span>Товарная биржа (БУТБ)</span>
            </div>
          </div>
          <div class="source-item">
            <span class="source-indicator active"></span>
            <div class="source-details">
              <strong>gias.by</strong>
              <span>Государственная информационная система</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Quick Tips -->
      <div class="glass-card tips-panel">
        <h3>Быстрые действия</h3>
        <ul class="tips-list">
          <li>
            <strong>Настройте профили:</strong> Перейдите во вкладку 
            <router-link to="/profiles">Профили поиска</router-link> 
            и настройте ключевые и минус-слова для вашей ниши.
          </li>
          <li>
            <strong>Подключите Telegram:</strong> Привяжите Telegram Chat ID к поисковому профилю для получения моментальных карточек тендеров с ИИ-анализом.
          </li>
          <li>
            <strong>Анализируйте ТЗ:</strong> ИИ автоматически считывает требования из прикрепленных файлов спецификаций и дает рекомендации по подготовке коммерческого предложения.
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, onUnmounted } from 'vue'
import { store } from '../store.js'

export default {
  name: 'Dashboard',
  setup() {
    const stats = ref({
      stats: {
        total_tenders: 0,
        total_matches: 0,
        new_matches: 0,
        sent_notifications: 0
      },
      tasks: {
        ingest: 'idle',
        notify: 'idle'
      }
    })

    let pollInterval = null

    const fetchStats = async () => {
      try {
        const data = await store.fetch('/api/stats')
        stats.value = data
      } catch (err) {
        console.error('Failed to load stats:', err)
      }
    }

    const triggerIngest = async () => {
      try {
        await store.fetch('/api/actions/ingest', { method: 'POST' })
        fetchStats()
      } catch (err) {
        alert('Не удалось запустить сбор: ' + err.message)
      }
    }

    const triggerNotify = async () => {
      try {
        await store.fetch('/api/actions/notify', { method: 'POST' })
        fetchStats()
      } catch (err) {
        alert('Не удалось запустить рассылку: ' + err.message)
      }
    }

    onMounted(() => {
      fetchStats()
      // Poll stats every 3 seconds to update task running state
      pollInterval = setInterval(fetchStats, 3000)
    })

    onUnmounted(() => {
      if (pollInterval) clearInterval(pollInterval)
    })

    return {
      stats,
      store,
      triggerIngest,
      triggerNotify
    }
  }
}
</script>

<style scoped>
.btn-icon {
  margin-right: 0.5rem;
}
.dashboard-content-layout {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 1.5rem;
}

@media (max-width: 992px) {
  .dashboard-content-layout {
    grid-template-columns: 1fr;
  }
}

.welcome-panel h3, .tips-panel h3 {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 1.25rem;
  margin-bottom: 1rem;
}

.welcome-panel .desc {
  color: var(--text-muted);
  font-size: 0.95rem;
  margin-bottom: 1.5rem;
}

.sources-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem;
}

.source-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  background: rgba(255, 255, 255, 0.02);
  padding: 0.85rem 1rem;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-card);
}

.source-indicator {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.source-indicator.active {
  background-color: var(--success);
  box-shadow: 0 0 10px var(--success);
}

.source-details {
  display: flex;
  flex-direction: column;
}

.source-details strong {
  font-size: 0.9rem;
}

.source-details span {
  font-size: 0.75rem;
  color: var(--text-muted);
}

.tips-list {
  list-style: none;
}

.tips-list li {
  font-size: 0.9rem;
  color: var(--text-muted);
  margin-bottom: 1rem;
  line-height: 1.4;
  padding-left: 1.25rem;
  position: relative;
}
.tips-list li::before {
  content: "💡";
  position: absolute;
  left: 0;
  top: 0;
}

.tips-list a {
  color: var(--primary);
  text-decoration: none;
}
.tips-list a:hover {
  text-decoration: underline;
}

/* Premium Upgrade Banner */
.premium-upgrade-banner {
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.12), rgba(139, 92, 246, 0.08));
  border: 1px solid rgba(59, 130, 246, 0.25);
  padding: 1.5rem;
  margin-top: 1.5rem;
}

.banner-badge {
  background: rgba(59, 130, 246, 0.15);
  border: 1px solid rgba(59, 130, 246, 0.3);
  color: #60a5fa;
  font-size: 0.8rem;
  font-weight: 700;
  padding: 0.25rem 0.75rem;
  border-radius: 20px;
  display: inline-block;
  margin-bottom: 0.75rem;
}

.premium-upgrade-banner h3 {
  font-size: 1.2rem;
  font-weight: 700;
  margin-bottom: 0.5rem;
}

.premium-upgrade-banner p {
  color: var(--text-muted);
  font-size: 0.9rem;
  line-height: 1.5;
  margin: 0;
}
</style>
