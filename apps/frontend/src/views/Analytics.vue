<template>
  <div class="analytics-view">
    <div class="page-header">
      <div class="page-title">
        <h2>Аналитика рынка</h2>
        <p>Анализ конкурентной среды, активности заказчиков и ценового дисконта в вашей нише.</p>
      </div>
    </div>

    <!-- Loading State -->
    <div v-if="loading" class="analytics-loading-state">
      <div class="spinner"></div>
      <p>Загрузка аналитических данных...</p>
    </div>

    <div v-else class="analytics-content">
      <!-- Key Performance Indicators (KPIs) -->
      <div class="grid-stats">
        <div class="glass-card stat-card border-glow">
          <div class="stat-icon warning">📉</div>
          <div class="stat-info">
            <span class="stat-value text-warning">{{ metrics.average_discount_percentage ?? 0 }}%</span>
            <span class="stat-label">Средний дисконт (снижение цены)</span>
          </div>
        </div>

        <div class="glass-card stat-card border-glow">
          <div class="stat-icon success">💰</div>
          <div class="stat-info">
            <span class="stat-value text-success">{{ formatMoney(metrics.total_discount_amount) }} BYN</span>
            <span class="stat-label">Суммарная экономия бюджетов</span>
          </div>
        </div>

        <div class="glass-card stat-card border-glow">
          <div class="stat-icon info">🔬</div>
          <div class="stat-info">
            <span class="stat-value text-info">{{ metrics.analyzed_count ?? 0 }}</span>
            <span class="stat-label">Проанализировано результатов</span>
          </div>
        </div>
      </div>

      <!-- Main Analytics Layout -->
      <div class="analytics-layout-grid">
        <!-- Top Winners (Competitors) -->
        <div class="glass-card chart-panel">
          <div class="panel-header">
            <h3>🏆 Топ-10 победителей (Конкуренты)</h3>
            <p class="subtitle">Лидеры по сумме контрактов и количеству выигранных лотов</p>
          </div>

          <div v-if="topWinners.length === 0" class="empty-data-msg">
            Данные по победителям закупок пока отсутствуют.
          </div>
          <div v-else class="bar-chart-list">
            <div v-for="(winner, idx) in topWinners" :key="idx" class="bar-item">
              <div class="bar-item-info">
                <span class="bar-name">
                  <strong>{{ idx + 1 }}. {{ winner.name }}</strong>
                  <span v-if="winner.unp" class="unp-badge">УНП {{ winner.unp }}</span>
                </span>
                <span class="bar-values">
                  <strong>{{ winner.wins_count }} {{ getWinsDeclension(winner.wins_count) }}</strong>
                  <span class="separator">|</span>
                  <span class="amount">{{ formatMoney(winner.total_amount) }} BYN</span>
                </span>
              </div>
              <div class="bar-track">
                <div
                  class="bar-fill primary-fill"
                  :style="{ width: getWinnerBarWidth(winner) + '%' }"
                ></div>
              </div>
            </div>
          </div>
        </div>

        <!-- Top Customers -->
        <div class="glass-card chart-panel">
          <div class="panel-header">
            <h3>🏢 Топ-10 заказчиков (Спрос)</h3>
            <p class="subtitle">Наиболее активные организаторы тендеров по вашей тематике</p>
          </div>

          <div v-if="topCustomers.length === 0" class="empty-data-msg">
            Данные по заказчикам закупок пока отсутствуют.
          </div>
          <div v-else class="bar-chart-list">
            <div v-for="(customer, idx) in topCustomers" :key="idx" class="bar-item">
              <div class="bar-item-info">
                <span class="bar-name">
                  <strong>{{ idx + 1 }}. {{ customer.name }}</strong>
                </span>
                <span class="bar-values">
                  <strong>{{ customer.tenders_count }} {{ getTendersDeclension(customer.tenders_count) }}</strong>
                  <span class="separator">|</span>
                  <span class="amount">{{ formatMoney(customer.total_amount) }} BYN</span>
                </span>
              </div>
              <div class="bar-track">
                <div
                  class="bar-fill success-fill"
                  :style="{ width: getCustomerBarWidth(customer) + '%' }"
                ></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { store } from '../store.js'

export default {
  name: 'Analytics',
  setup() {
    const loading = ref(true)
    const metrics = ref({
      average_discount_percentage: 0,
      total_discount_amount: 0,
      analyzed_count: 0
    })
    const topWinners = ref([])
    const topCustomers = ref([])

    const fetchAnalytics = async () => {
      loading.value = true
      try {
        const data = await store.fetch('/api/analytics/competitors')
        metrics.value = data.metrics || {}
        topWinners.value = data.top_winners || []
        topCustomers.value = data.top_customers || []
      } catch (err) {
        console.error('Failed to load analytics:', err)
      } finally {
        loading.value = false
      }
    }

    const formatMoney = (val) => {
      if (val === undefined || val === null) return '0'
      return Number(val).toLocaleString('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
    }

    const getWinsDeclension = (count) => {
      const mod10 = count % 10
      const mod100 = count % 100
      if (mod10 === 1 && mod100 !== 11) return 'победа'
      if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'победы'
      return 'побед'
    }

    const getTendersDeclension = (count) => {
      const mod10 = count % 10
      const mod100 = count % 100
      if (mod10 === 1 && mod100 !== 11) return 'тендер'
      if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'тендера'
      return 'тендеров'
    }

    // Chart bar width calculators
    const getWinnerBarWidth = (winner) => {
      if (topWinners.value.length === 0) return 0
      // Calculate relative to the max amount in winners list
      const maxAmount = Math.max(...topWinners.value.map(w => w.total_amount), 1)
      const pct = (winner.total_amount / maxAmount) * 100
      return Math.max(pct, 4) // Ensure tiny amounts are still visible
    }

    const getCustomerBarWidth = (customer) => {
      if (topCustomers.value.length === 0) return 0
      // Calculate relative to the max amount in customers list
      const maxAmount = Math.max(...topCustomers.value.map(c => c.total_amount), 1)
      const pct = (customer.total_amount / maxAmount) * 100
      return Math.max(pct, 4) // Ensure tiny amounts are still visible
    }

    onMounted(() => {
      fetchAnalytics()
    })

    return {
      loading,
      metrics,
      topWinners,
      topCustomers,
      formatMoney,
      getWinsDeclension,
      getTendersDeclension,
      getWinnerBarWidth,
      getCustomerBarWidth
    }
  }
}
</script>

<style scoped>
.analytics-view {
  animation: fadeIn 0.4s ease-out;
}
.analytics-loading-state {
  text-align: center;
  padding: 8rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
}
.border-glow {
  border-color: var(--border-card-focus);
}

/* Colors helpers */
.text-warning { color: var(--warning); }
.text-success { color: var(--success); }
.text-info { color: var(--info); }

.analytics-layout-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.5rem;
  margin-top: 1.5rem;
}
@media (max-width: 992px) {
  .analytics-layout-grid {
    grid-template-columns: 1fr;
  }
}

.chart-panel {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}
.chart-panel .panel-header h3 {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 1.25rem;
}
.chart-panel .panel-header .subtitle {
  font-size: 0.8rem;
  color: var(--text-muted);
  margin-top: 0.15rem;
}

.empty-data-msg {
  padding: 3rem;
  text-align: center;
  color: var(--text-muted);
  font-style: italic;
  font-size: 0.9rem;
}

/* Relative bar charts list */
.bar-chart-list {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}
.bar-item {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.bar-item-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.85rem;
  gap: 1rem;
}
.bar-name {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.unp-badge {
  font-size: 0.7rem;
  color: var(--text-muted);
  background: rgba(255, 255, 255, 0.05);
  padding: 0.05rem 0.3rem;
  border-radius: 4px;
}
.bar-values {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
}
.bar-values .separator {
  color: rgba(255, 255, 255, 0.1);
}
.bar-values .amount {
  font-weight: 700;
  color: #f3f4f6;
  font-family: var(--font-display);
}

.bar-track {
  height: 8px;
  background: rgba(255, 255, 255, 0.02);
  border-radius: 4px;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.04);
}
.bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 1s cubic-bezier(0.1, 0.8, 0.25, 1);
}
.bar-fill.primary-fill {
  background: linear-gradient(90deg, var(--primary), var(--secondary));
  box-shadow: 0 0 10px rgba(59, 130, 246, 0.3);
}
.bar-fill.success-fill {
  background: linear-gradient(90deg, var(--success), var(--info));
  box-shadow: 0 0 10px rgba(16, 185, 129, 0.3);
}
</style>
