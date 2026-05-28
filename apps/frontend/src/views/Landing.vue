<template>
  <div class="landing-page">
    <!-- Header Navigation -->
    <header class="landing-header">
      <div class="logo-section">
        <div class="logo-icon">BZ</div>
        <div class="logo-text"><span class="gradient-text">BelZakupki</span></div>
      </div>
      <div class="nav-actions">
        <router-link to="/login" class="btn btn-secondary btn-sm" style="margin-right: 0.75rem;">Войти</router-link>
        <router-link to="/register" class="btn btn-primary btn-sm">Регистрация</router-link>
      </div>
    </header>

    <!-- Hero Section -->
    <section class="hero-section">
      <div class="hero-content">
        <span class="badge-pill">🤖 ИИ-Ассистент госзакупок</span>
        <h1>Автоматизируйте поиск и экспертизу тендеров Беларуси</h1>
        <p class="hero-subtitle">
          Платформа централизованно собирает закупки с goszakupki.by, icetrade.by, БУТБ и ГИАС. 
          ИИ DeepSeek автоматически считывает файлы спецификаций (ТЗ), оценивает риски и готовит рекомендации для КП.
        </p>
        <div class="hero-cta">
          <router-link to="/register" class="btn btn-primary btn-lg">Зарегистрироваться бесплатно</router-link>
          <a href="#live-feed" class="btn btn-secondary btn-lg" style="margin-left: 1rem;">Смотреть ленту за сегодня</a>
        </div>
      </div>
    </section>

    <!-- Key Features Grid -->
    <section class="features-section">
      <h2 class="section-title">Почему BelZakupki меняет правила игры</h2>
      <div class="features-grid">
        <div class="glass-card feature-card">
          <div class="feature-icon">⚡</div>
          <h3>Централизованный сбор</h3>
          <p>Мониторинг 4 ключевых площадок в реальном времени. Нет риска пропустить выгодный тендер.</p>
        </div>
        <div class="glass-card feature-card">
          <div class="feature-icon">🔍</div>
          <h3>Умная фильтрация</h3>
          <p>Морфологический скоринг по ключевым и минус-словам отсекает до 95% мусора на лету.</p>
        </div>
        <div class="glass-card feature-card">
          <div class="feature-icon">🧠</div>
          <h3>ИИ-экспертиза ТЗ</h3>
          <p>DeepSeek автоматически читает PDF, Word и Excel спецификации, выявляет скрытые штрафы и пени.</p>
        </div>
        <div class="glass-card feature-card">
          <div class="feature-icon">💼</div>
          <h3>Интеграция с CRM</h3>
          <p>Экспорт лидов в amoCRM и Bitrix24 в один клик с полным ИИ-отчетом и ссылками на документы.</p>
        </div>
      </div>
    </section>

    <!-- Live Preview Feed Section -->
    <section id="live-feed" class="live-feed-section">
      <div class="section-header">
        <h2 class="section-title">Общая лента закупок за сегодня</h2>
        <p class="section-subtitle">
          Ниже транслируется поток свежих тендеров, собранных системой за последние 24 часа. 
          Выберите любой тендер для ознакомления.
        </p>
      </div>

      <div class="glass-card feed-container">
        <div class="table-container" v-if="tenders.length > 0">
          <table class="custom-table">
            <thead>
              <tr>
                <th>Источник</th>
                <th>Предмет закупки</th>
                <th>Заказчик</th>
                <th>Окончание подачи</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in tenders" :key="t.id" @click="openPreview(t)" class="clickable-row">
                <td>
                  <span class="source-tag">{{ t.source_name || t.source }}</span>
                </td>
                <td>
                  <strong class="tender-title-link">{{ t.title }}</strong>
                  <div class="tender-num" v-if="t.source_number">№ {{ t.source_number }}</div>
                </td>
                <td class="customer-cell">{{ truncateText(t.customer_name || 'Не указан', 40) }}</td>
                <td style="white-space: nowrap;">{{ formatDate(t.deadline_at) || 'Не указан' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty-state" style="padding: 4rem; text-align: center;">
          <div class="spinner" style="margin: 0 auto 1rem auto; width: 40px; height: 40px;"></div>
          <h3>Загрузка свежих тендеров...</h3>
        </div>
      </div>
    </section>

    <!-- Blurred Preview Modal -->
    <div v-if="selectedTender" class="modal-overlay" @click.self="selectedTender = null">
      <div class="glass-card modal-content preview-modal">
        <div class="modal-header">
          <h3 style="font-size: 1.15rem; font-weight: 700;">Детали закупки</h3>
          <button @click="selectedTender = null" class="modal-close">×</button>
        </div>
        <div class="modal-body">
          <h2 style="font-size: 1.3rem; line-height: 1.4; margin-bottom: 1.5rem;">{{ selectedTender.title }}</h2>
          
          <div class="info-blocks-grid" style="margin-bottom: 1.5rem;">
            <div class="info-block">
              <span class="label">Заказчик</span>
              <span class="value">{{ selectedTender.customer_name || 'Не указан' }}</span>
            </div>
            <div class="info-block">
              <span class="label">Ориентировочная стоимость</span>
              <span class="value">{{ selectedTender.estimated_value || 'Не указана' }}</span>
            </div>
          </div>

          <!-- Blurred specifications & CTA Overlay -->
          <div class="blurred-zone-wrapper">
            <div class="blurred-content">
              <h4>Техническое задание и лоты</h4>
              <p>Лот №1: Поставка кондиционеров канального типа с мощностью охлаждения не менее 5 кВт - 3 шт.</p>
              <p>Условия оплаты: Безналичный расчет, оплата в течение 30 календарных дней после монтажа.</p>
              <p>Прикрепленные файлы: Спецификация_оборудования.xlsx, Проект_договора.pdf</p>
            </div>
            <div class="cta-overlay">
              <div class="cta-box">
                <span class="cta-icon">🔓</span>
                <h3>Детальный анализ заблокирован</h3>
                <p>Зарегистрируйтесь бесплатно, чтобы получить полный доступ к ТЗ, скачать вложения и открыть ИИ чат-ассистента по условиям договора.</p>
                <router-link to="/register" class="btn btn-primary">Создать аккаунт бесплатно</router-link>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { store } from '../store.js'

const tenders = ref([])
const selectedTender = ref(null)

const loadTodayTenders = async () => {
  try {
    // API returns last 24h tenders for Guest/unauthenticated requests automatically
    const res = await store.fetch('/api/tenders?limit=15')
    tenders.value = res.items
  } catch (e) {
    console.error('Failed to load today tenders:', e)
  }
}

const openPreview = (tender) => {
  selectedTender.value = tender
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

onMounted(() => {
  loadTodayTenders()
})
</script>

<style scoped>
.landing-page {
  background: radial-gradient(circle at 50% 0%, rgba(59, 130, 246, 0.08), rgba(0, 0, 0, 0) 50%),
              radial-gradient(circle at 10% 40%, rgba(139, 92, 246, 0.05), rgba(0, 0, 0, 0) 40%),
              #030712;
  color: var(--text-main);
  min-height: 100vh;
  padding: 0 2rem 4rem 2rem;
  overflow-x: hidden;
}

.landing-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.5rem 0;
  max-width: 1200px;
  margin: 0 auto 3rem auto;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.hero-section {
  max-width: 900px;
  margin: 0 auto 6rem auto;
  text-align: center;
}

.badge-pill {
  background: rgba(59, 130, 246, 0.1);
  border: 1px solid rgba(59, 130, 246, 0.3);
  color: #60a5fa;
  padding: 0.4rem 1rem;
  border-radius: 20px;
  font-size: 0.85rem;
  font-weight: 700;
  display: inline-block;
  margin-bottom: 1.5rem;
}

h1 {
  font-family: var(--font-display);
  font-size: 3rem;
  font-weight: 800;
  line-height: 1.2;
  margin-bottom: 1.5rem;
  background: linear-gradient(135deg, #fff 30%, #9ca3af 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.hero-subtitle {
  font-size: 1.15rem;
  color: var(--text-muted);
  line-height: 1.6;
  margin-bottom: 2.5rem;
}

.hero-cta {
  display: flex;
  justify-content: center;
}

.features-section {
  max-width: 1200px;
  margin: 0 auto 6rem auto;
}

.section-title {
  text-align: center;
  font-size: 2rem;
  font-weight: 700;
  margin-bottom: 3rem;
  background: linear-gradient(135deg, #fff, #9ca3af);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.features-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 2rem;
}

.feature-card {
  padding: 2rem;
  transition: transform 0.3s ease, border-color 0.3s ease;
  border-color: rgba(255, 255, 255, 0.05);
}

.feature-card:hover {
  transform: translateY(-5px);
  border-color: rgba(59, 130, 246, 0.2);
}

.feature-icon {
  font-size: 2.5rem;
  margin-bottom: 1.5rem;
}

.feature-card h3 {
  font-size: 1.25rem;
  font-weight: 600;
  margin-bottom: 0.75rem;
}

.feature-card p {
  color: var(--text-muted);
  font-size: 0.9rem;
  line-height: 1.5;
}

.live-feed-section {
  max-width: 1200px;
  margin: 0 auto;
}

.section-header {
  text-align: center;
  margin-bottom: 2.5rem;
}

.section-subtitle {
  color: var(--text-muted);
}

.feed-container {
  padding: 0;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.clickable-row {
  cursor: pointer;
  transition: background-color 0.2s;
}

.clickable-row:hover {
  background-color: rgba(255, 255, 255, 0.03);
}

.tender-num {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin-top: 0.25rem;
}

.customer-cell {
  color: var(--text-muted);
}

/* Blurred preview styles */
.preview-modal {
  max-width: 700px;
}

.blurred-zone-wrapper {
  position: relative;
  border-radius: var(--radius-md);
  overflow: hidden;
  border: 1px solid var(--border-card);
  margin-top: 1rem;
}

.blurred-content {
  padding: 1.5rem;
  filter: blur(5px);
  user-select: none;
  pointer-events: none;
  background: rgba(255, 255, 255, 0.02);
}

.cta-overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: linear-gradient(180deg, rgba(3, 7, 18, 0.4), rgba(3, 7, 18, 0.95));
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 2rem;
  text-align: center;
}

.cta-box {
  max-width: 450px;
  animation: fadeIn 0.3s ease-out;
}

.cta-icon {
  font-size: 2.5rem;
  margin-bottom: 1rem;
  display: inline-block;
}

.cta-box h3 {
  font-size: 1.25rem;
  font-weight: 700;
  margin-bottom: 0.5rem;
}

.cta-box p {
  color: var(--text-muted);
  font-size: 0.9rem;
  line-height: 1.5;
  margin-bottom: 1.5rem;
}
</style>
