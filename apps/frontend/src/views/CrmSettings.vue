<template>
  <div class="crm-settings-view animate-fade-in">
    <div class="page-header">
      <div class="page-title">
        <h2>B2B CRM Интеграция</h2>
        <p>Экспортируйте выигранные закупки и высокорелевантные совпадения тендеров в вашу CRM-систему в один клик.</p>
      </div>
    </div>

    <!-- Active CRM indicator -->
    <div class="glass-card active-indicator-card">
      <div class="indicator-details">
        <span class="indicator-icon">🚀</span>
        <div>
          <strong>Текущий статус интеграции:</strong>
          <span v-if="activeCrm" class="active-crm-text">
            Активна интеграция с <span class="active-name">{{ activeCrmName }}</span>
          </span>
          <span v-else class="inactive-crm-text">Не настроена (выключена)</span>
        </div>
      </div>
    </div>

    <div class="crm-grid">
      <!-- Bitrix24 Card -->
      <div class="glass-card crm-card" :class="{ 'active-glow': activeCrm === 'bitrix24' }">
        <div class="crm-logo-header">
          <div class="crm-logo-icon bitrix24">B24</div>
          <div class="crm-title-meta">
            <h3>Битрикс24</h3>
            <span class="status-badge" :class="configs.bitrix24?.is_active ? 'active' : 'inactive'">
              {{ configs.bitrix24?.is_active ? 'Активно' : 'Отключено' }}
            </span>
          </div>
        </div>
        
        <p class="crm-desc">
          Интеграция через <strong>входящий вебхук</strong>. Позволяет создавать Лиды или Сделки в вашей CRM со стоимостью закупки, детальным ИИ-анализом и ссылкой на первоисточник.
        </p>

        <form @submit.prevent="saveConfig('bitrix24')" class="crm-form">
          <div class="form-group">
            <label class="form-label">Входящий вебхук URL <span class="required">*</span></label>
            <input
              type="url"
              v-model="forms.bitrix24.webhook_url"
              class="form-input"
              placeholder="https://your-domain.bitrix24.ru/rest/1/webhook-code/"
              required
            />
            <span class="form-help">
              В вебхуке Битрикс24 должны быть выданы права на CRM (crm.deal.add).
            </span>
          </div>

          <div class="toggle-group mt-3">
            <label class="switch-container">
              <input type="checkbox" v-model="forms.bitrix24.is_active" />
              <span class="switch-slider"></span>
              <span class="switch-label">Включить эту интеграцию</span>
            </label>
          </div>

          <div class="crm-actions mt-4">
            <button
              type="button"
              @click="testConnection('bitrix24')"
              class="btn btn-secondary"
              :disabled="loading.testBitrix || !forms.bitrix24.webhook_url"
            >
              <span v-if="loading.testBitrix" class="spinner-sm"></span>
              <span v-else>🧪 Проверить связь</span>
            </button>
            <button
              type="submit"
              class="btn btn-primary"
              :disabled="loading.saveBitrix"
            >
              <span v-if="loading.saveBitrix" class="spinner-sm"></span>
              <span v-else>Сохранить настройки</span>
            </button>
          </div>
        </form>
      </div>

      <!-- amoCRM Card -->
      <div class="glass-card crm-card" :class="{ 'active-glow': activeCrm === 'amocrm' }">
        <div class="crm-logo-header">
          <div class="crm-logo-icon amocrm">amo</div>
          <div class="crm-title-meta">
            <h3>amoCRM</h3>
            <span class="status-badge" :class="configs.amocrm?.is_active ? 'active' : 'inactive'">
              {{ configs.amocrm?.is_active ? 'Активно' : 'Отключено' }}
            </span>
          </div>
        </div>
        
        <p class="crm-desc">
          Интеграция через <strong>долгоживущий токен (REST API v4)</strong>. Создает сделку в неразобранном с текстовым примечанием, содержащим всю спецификацию закупки и ИИ-анализ.
        </p>

        <form @submit.prevent="saveConfig('amocrm')" class="crm-form">
          <div class="form-group">
            <label class="form-label">Субдомен аккаунта amoCRM <span class="required">*</span></label>
            <div class="input-prefix-wrapper">
              <input
                type="text"
                v-model="forms.amocrm.subdomain"
                class="form-input text-right"
                placeholder="your-company"
                required
              />
              <span class="input-suffix">.amocrm.ru</span>
            </div>
            <span class="form-help">Укажите только техническое имя субдомена.</span>
          </div>

          <div class="form-group mt-3">
            <label class="form-label">Долгоживущий токен доступа (API Token) <span class="required">*</span></label>
            <textarea
              v-model="forms.amocrm.api_token"
              class="form-input textarea-token"
              placeholder="Вставьте длинный токен интеграции amoCRM..."
              rows="4"
              required
            ></textarea>
            <span class="form-help">
              Перейдите в amoCRM -> АмоМаркет -> Установленные -> Создать интеграцию. Скопируйте «Токен доступа».
            </span>
          </div>

          <div class="toggle-group mt-3">
            <label class="switch-container">
              <input type="checkbox" v-model="forms.amocrm.is_active" />
              <span class="switch-slider"></span>
              <span class="switch-label">Включить эту интеграцию</span>
            </label>
          </div>

          <div class="crm-actions mt-4">
            <button
              type="button"
              @click="testConnection('amocrm')"
              class="btn btn-secondary"
              :disabled="loading.testAmo || !forms.amocrm.subdomain || !forms.amocrm.api_token"
            >
              <span v-if="loading.testAmo" class="spinner-sm"></span>
              <span v-else>🧪 Проверить связь</span>
            </button>
            <button
              type="submit"
              class="btn btn-primary"
              :disabled="loading.saveAmo"
            >
              <span v-if="loading.saveAmo" class="spinner-sm"></span>
              <span v-else>Сохранить настройки</span>
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Notification system for tests/save -->
    <div v-if="toast.show" class="toast-notification" :class="toast.type">
      <span class="toast-icon">{{ toast.type === 'success' ? '✅' : '⚠️' }}</span>
      <div class="toast-body">
        <strong>{{ toast.title }}</strong>
        <p>{{ toast.message }}</p>
      </div>
      <button @click="toast.show = false" class="toast-close">×</button>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { store } from '../store.js'

const configs = reactive({
  bitrix24: null,
  amocrm: null
})

const forms = reactive({
  bitrix24: {
    webhook_url: '',
    is_active: false
  },
  amocrm: {
    subdomain: '',
    api_token: '',
    is_active: false
  }
})

const loading = reactive({
  testBitrix: false,
  testAmo: false,
  saveBitrix: false,
  saveAmo: false
})

const toast = reactive({
  show: false,
  type: 'success',
  title: '',
  message: ''
})

const showToast = (type, title, message) => {
  toast.type = type
  toast.title = title
  toast.message = message
  toast.show = true
  setTimeout(() => {
    toast.show = false;
  }, 6000)
}

const activeCrm = computed(() => {
  if (configs.bitrix24?.is_active) return 'bitrix24'
  if (configs.amocrm?.is_active) return 'amocrm'
  return null
})

const activeCrmName = computed(() => {
  if (activeCrm.value === 'bitrix24') return 'Битрикс24'
  if (activeCrm.value === 'amocrm') return 'amoCRM'
  return ''
})

const fetchSettings = async () => {
  try {
    const data = await store.fetch('/api/crm/settings')
    configs.bitrix24 = null
    configs.amocrm = null
    
    // Clear forms initially
    forms.bitrix24.webhook_url = ''
    forms.bitrix24.is_active = false
    forms.amocrm.subdomain = ''
    forms.amocrm.api_token = ''
    forms.amocrm.is_active = false

    data.forEach(config => {
      if (config.crm_type === 'bitrix24') {
        configs.bitrix24 = config
        forms.bitrix24.webhook_url = config.webhook_url || ''
        forms.bitrix24.is_active = config.is_active
      } else if (config.crm_type === 'amocrm') {
        configs.amocrm = config
        forms.amocrm.subdomain = config.subdomain || ''
        forms.amocrm.api_token = config.api_token || ''
        forms.amocrm.is_active = config.is_active
      }
    })
  } catch (e) {
    showToast('error', 'Ошибка загрузки настроек', e.message)
  }
}

const saveConfig = async (type) => {
  const isBitrix = type === 'bitrix24'
  const loadKey = isBitrix ? 'saveBitrix' : 'saveAmo'
  loading[loadKey] = true
  
  try {
    const payload = {
      crm_type: type,
      is_active: forms[type].is_active,
      webhook_url: isBitrix ? forms.bitrix24.webhook_url : null,
      subdomain: !isBitrix ? forms.amocrm.subdomain : null,
      api_token: !isBitrix ? forms.amocrm.api_token : null,
    }

    await store.fetch('/api/crm/settings', {
      method: 'POST',
      body: JSON.stringify(payload)
    })

    showToast('success', 'Настройки сохранены', `Интеграция с ${isBitrix ? 'Битрикс24' : 'amoCRM'} успешно обновлена.`)
    await fetchSettings()
  } catch (e) {
    showToast('error', 'Не удалось сохранить настройки', e.message)
  } finally {
    loading[loadKey] = false
  }
}

const testConnection = async (type) => {
  const isBitrix = type === 'bitrix24'
  const loadKey = isBitrix ? 'testBitrix' : 'testAmo'
  loading[loadKey] = true

  try {
    const payload = {
      crm_type: type,
      is_active: forms[type].is_active,
      webhook_url: isBitrix ? forms.bitrix24.webhook_url : null,
      subdomain: !isBitrix ? forms.amocrm.subdomain : null,
      api_token: !isBitrix ? forms.amocrm.api_token : null,
    }

    const res = await store.fetch('/api/crm/settings/test', {
      method: 'POST',
      body: JSON.stringify(payload)
    })

    if (res.success) {
      showToast('success', 'Связь успешно проверена!', `Тестовая сделка создана в CRM. ID сущности: ${res.deal_id}`)
    } else {
      showToast('error', 'Связь не установлена', 'Неизвестная ошибка')
    }
  } catch (e) {
    showToast('error', 'Связь не установлена', e.message)
  } finally {
    loading[loadKey] = false
  }
}

onMounted(() => {
  fetchSettings()
})
</script>

<style scoped>
.crm-settings-view {
  max-width: 1200px;
  margin: 0 auto;
}

.active-indicator-card {
  padding: 1rem 1.5rem;
  margin-bottom: 2rem;
  border-left: 4px solid var(--primary);
}

.indicator-details {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.indicator-icon {
  font-size: 1.5rem;
}

.active-crm-text {
  color: var(--text);
  margin-left: 0.5rem;
}

.active-crm-text .active-name {
  color: var(--primary);
  font-weight: 600;
  text-decoration: underline;
}

.inactive-crm-text {
  color: var(--text-secondary);
  margin-left: 0.5rem;
}

.crm-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 2rem;
}

@media (max-width: 900px) {
  .crm-grid {
    grid-template-columns: 1fr;
  }
}

.crm-card {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 2rem;
  transition: transform 0.3s ease, border-color 0.3s ease;
}

.crm-card:hover {
  transform: translateY(-2px);
}

.active-glow {
  border-color: rgba(59, 130, 246, 0.4);
  box-shadow: 0 0 15px rgba(59, 130, 246, 0.15);
}

.crm-logo-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1.25rem;
}

.crm-logo-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
  font-size: 1.2rem;
  color: #fff;
  box-shadow: 0 4px 10px rgba(0, 0, 0, 0.2);
}

.crm-logo-icon.bitrix24 {
  background: linear-gradient(135deg, #00b4e6, #007fa5);
}

.crm-logo-icon.amocrm {
  background: linear-gradient(135deg, #fc4a1a, #f7b733);
}

.crm-title-meta {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.crm-title-meta h3 {
  margin: 0;
  font-size: 1.4rem;
}

.status-badge {
  font-size: 0.75rem;
  padding: 0.1rem 0.5rem;
  border-radius: 6px;
  font-weight: 600;
  display: inline-block;
  align-self: flex-start;
}

.status-badge.active {
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
  border: 1px solid rgba(16, 185, 129, 0.2);
}

.status-badge.inactive {
  background: rgba(244, 63, 94, 0.1);
  color: #f43f5e;
  border: 1px solid rgba(244, 63, 94, 0.2);
}

.crm-desc {
  font-size: 0.95rem;
  color: var(--text-secondary);
  line-height: 1.5;
  margin-bottom: 2rem;
}

.crm-form {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.input-prefix-wrapper {
  display: flex;
  align-items: center;
  position: relative;
}

.input-prefix-wrapper input {
  padding-right: 6.5rem;
}

.input-suffix {
  position: absolute;
  right: 1rem;
  color: var(--text-secondary);
  font-size: 0.9rem;
  pointer-events: none;
}

.textarea-token {
  font-family: monospace;
  font-size: 0.8rem;
  resize: vertical;
}

.switch-container {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  cursor: pointer;
}

.switch-slider {
  position: relative;
  width: 44px;
  height: 22px;
  background-color: rgba(255, 255, 255, 0.1);
  border: 1px solid var(--border-card);
  border-radius: 20px;
  transition: 0.3s;
}

.switch-container input {
  display: none;
}

.switch-slider::before {
  content: "";
  position: absolute;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  left: 2px;
  top: 2px;
  background-color: var(--text-secondary);
  transition: 0.3s;
}

.switch-container input:checked + .switch-slider {
  background-color: rgba(59, 130, 246, 0.2);
  border-color: var(--primary);
}

.switch-container input:checked + .switch-slider::before {
  transform: translateX(22px);
  background-color: var(--primary);
}

.switch-label {
  font-size: 0.95rem;
  color: var(--text);
}

.crm-actions {
  display: flex;
  gap: 1rem;
}

.crm-actions .btn {
  flex: 1;
}

.spinner-sm {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.2);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  display: inline-block;
}

/* Toast notifications */
.toast-notification {
  position: fixed;
  bottom: 2rem;
  right: 2rem;
  z-index: 9999;
  display: flex;
  align-items: flex-start;
  gap: 1rem;
  padding: 1.25rem;
  border-radius: 12px;
  backdrop-filter: blur(12px);
  min-width: 320px;
  max-width: 450px;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.3);
  animation: slide-in 0.3s ease;
}

.toast-notification.success {
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(16, 185, 129, 0.3);
  color: #e6fcf5;
}

.toast-notification.error {
  background: rgba(244, 63, 94, 0.15);
  border: 1px solid rgba(244, 63, 94, 0.3);
  color: #ffeef1;
}

.toast-icon {
  font-size: 1.25rem;
}

.toast-body {
  flex: 1;
}

.toast-body strong {
  display: block;
  font-size: 0.95rem;
  margin-bottom: 0.25rem;
}

.toast-body p {
  margin: 0;
  font-size: 0.85rem;
  opacity: 0.9;
  line-height: 1.4;
}

.toast-close {
  background: none;
  border: none;
  color: inherit;
  font-size: 1.2rem;
  cursor: pointer;
  padding: 0;
  opacity: 0.7;
}

.toast-close:hover {
  opacity: 1;
}

@keyframes slide-in {
  from {
    transform: translateY(20px);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}

.animate-fade-in {
  animation: fade-in 0.4s ease;
}

@keyframes fade-in {
  from { opacity: 0; transform: translateY(5px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
