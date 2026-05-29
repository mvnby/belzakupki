<template>
  <div class="matches-view">
    <div class="page-header">
      <div class="page-title">
        <h2>Совпадения тендеров</h2>
        <p>Просматривайте тендеры, прошедшие автоматический скоринг и интеллектуальный ИИ-анализ.</p>
      </div>
      <div class="page-actions">
        <button @click="downloadExcel" class="btn btn-secondary">
          <span class="btn-icon">📥</span> Экспорт в Excel
        </button>
      </div>
    </div>

    <!-- Filters Panel -->
    <div class="glass-card filters-panel">
      <div class="filters-grid">
        <div class="form-group mb-0">
          <label class="form-label">Профиль поиска</label>
          <select v-model="selectedProfile" @change="fetchMatches" class="form-input">
            <option :value="null">Все профили</option>
            <option v-for="prof in profiles" :key="prof.id" :value="prof.id">
              {{ prof.name }}
            </option>
          </select>
        </div>

        <div class="form-group mb-0">
          <label class="form-label">Поиск по ключевым словам или заказчику</label>
          <div class="search-input-wrapper">
            <input
              type="text"
              v-model="searchQuery"
              @input="debouncedSearch"
              class="form-input"
              placeholder="Введите текст для поиска..."
            />
            <span v-if="searchQuery" @click="clearSearch" class="clear-search-btn">&times;</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Status Tabs -->
    <div class="status-tabs">
      <button
        v-for="tab in statusTabs"
        :key="tab.value"
        class="tab-btn"
        :class="{ active: selectedStatus === tab.value }"
        @click="selectStatusTab(tab.value)"
      >
        {{ tab.label }}
        <span v-if="getTabCount(tab.value) !== null" class="tab-count">{{ getTabCount(tab.value) }}</span>
      </button>
    </div>

    <!-- Matches Table -->
    <div v-if="loading && matches.length === 0" class="table-loading-state">
      <div class="spinner"></div>
      <p>Загрузка совпадений...</p>
    </div>
    <div v-else-if="matches.length === 0" class="glass-card empty-state">
      <div class="empty-icon">🎯</div>
      <h3>Совпадений не обнаружено</h3>
      <p>Попробуйте скорректировать поисковые профили или запустить новый сбор на Главной панели.</p>
    </div>
    <div v-else class="glass-card matches-card">
      <div class="table-container">
        <table class="custom-table">
          <thead>
            <tr>
              <th>Тендер</th>
              <th>Заказчик</th>
              <th>Профиль поиска</th>
              <th class="text-center">Релевантность ИИ</th>
              <th class="text-center">Балл</th>
              <th>Дедлайн</th>
              <th>Статус</th>
              <th class="text-center">Действия</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="match in matches" :key="match.id">
              <td class="tender-cell">
                <a @click.prevent="openDetailPanel(match)" href="#" class="tender-title-link" :title="match.tender.title">
                  {{ truncateText(match.tender.title, 60) }}
                </a>
                <div class="tender-subinfo">
                  <span class="source-tag">{{ match.tender.source_name || match.tender.source }}</span>
                  <span v-if="match.tender.source_number" class="number-tag">№ {{ match.tender.source_number }}</span>
                </div>
              </td>
              <td>
                <div class="customer-name" :title="match.tender.customer_name">
                  {{ truncateText(match.tender.customer_name || 'Не указан', 30) }}
                </div>
              </td>
              <td>
                <span class="profile-badge">{{ match.profile.name }}</span>
              </td>
              <td class="text-center">
                <span v-if="match.ai_relevance === true" class="ai-relevance-badge positive">Подходит</span>
                <span v-else-if="match.ai_relevance === false" class="ai-relevance-badge negative">Отклонен ИИ</span>
                <span v-else class="ai-relevance-badge pending">Не проверен</span>
              </td>
              <td class="text-center">
                <span class="score-badge" :class="getScoreClass(match.score)">
                  {{ match.score }}%
                </span>
              </td>
              <td>
                <div class="deadline-cell" :class="{ 'deadline-danger': isDeadlineClose(match.tender.deadline_at) }">
                  {{ formatDate(match.tender.deadline_at) || 'Не указан' }}
                </div>
              </td>
              <td>
                <span class="status-badge" :class="match.status">{{ formatStatusName(match.status) }}</span>
              </td>
              <td class="text-center">
                <div class="action-buttons-cell">
                  <button @click="quickStatusUpdate(match.id, 'accepted')" class="quick-btn accept" title="Принять в работу">✓</button>
                  <button @click="quickStatusUpdate(match.id, 'rejected')" class="quick-btn reject" title="Отклонить">✗</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div class="pagination-bar">
        <button @click="prevPage" :disabled="offset === 0 || loading" class="btn btn-secondary btn-sm">◄ Назад</button>
        <span class="pagination-info">Показано {{ offset + 1 }} - {{ offset + matches.length }}</span>
        <button @click="nextPage" :disabled="matches.length < limit || loading" class="btn btn-secondary btn-sm">Вперед ►</button>
      </div>
    </div>

    <!-- Match Details Modal/Slideout -->
    <div v-if="detailPanelOpen" class="modal-overlay" @click.self="closeDetailPanel">
      <div class="glass-card modal-content detail-panel-content">
        <div class="modal-header">
          <div class="detail-header-title">
            <span class="status-badge" :class="selectedMatch.status">{{ formatStatusName(selectedMatch.status) }}</span>
            <h3>Детальная информация о тендере</h3>
          </div>
          <button @click="closeDetailPanel" class="modal-close">&times;</button>
        </div>

        <div class="detail-grid">
          <!-- Left side: Tender info -->
          <div class="detail-left">
            <h2 class="tender-full-title">{{ selectedMatch.tender.title }}</h2>
            
            <div class="info-blocks-grid">
              <div class="info-block">
                <span class="label">Заказчик</span>
                <span class="value">{{ selectedMatch.tender.customer_name || 'Не указан' }}</span>
              </div>
              <div class="info-block">
                <span class="label">Ориентировочная стоимость</span>
                <span class="value highlight-value">{{ selectedMatch.tender.estimated_value || 'Не указана' }}</span>
              </div>
              <div class="info-block" v-if="selectedMatch.tender.procedure_type">
                <span class="label">Вид процедуры</span>
                <span class="value">{{ selectedMatch.tender.procedure_type }}</span>
              </div>
              <div class="info-block">
                <span class="label">Дедлайн подачи предложений</span>
                <span class="value">{{ formatDate(selectedMatch.tender.deadline_at) || selectedMatch.tender.deadline || 'Не указан' }}</span>
              </div>
            </div>

            <!-- Description / Scope of work -->
            <div class="detail-section" v-if="selectedMatch.tender.search_text">
              <h4>Описание / Предмет закупки</h4>
              <p class="description-text">{{ selectedMatch.tender.search_text }}</p>
            </div>

            <!-- Lots -->
            <div class="detail-section" v-if="selectedMatch.tender.lots && selectedMatch.tender.lots.length > 0">
              <h4>Лоты закупки</h4>
              <div class="lots-list">
                <div v-for="(lot, idx) in selectedMatch.tender.lots" :key="idx" class="lot-item">
                  <strong>Лот №{{ lot.number || idx + 1 }}:</strong> {{ lot.name || lot.title }}
                  <span class="lot-price" v-if="lot.estimated_value">{{ lot.estimated_value }}</span>
                </div>
              </div>
            </div>

            <!-- Documents Attachments -->
            <div class="detail-section" v-if="selectedMatch.tender.attachments && selectedMatch.tender.attachments.length > 0">
              <h4>Прикрепленные файлы</h4>
              <div class="attachments-grid">
                <div v-for="(file, idx) in selectedMatch.tender.attachments" :key="idx" class="attachment-item">
                  <span class="file-icon">📄</span>
                  <div class="file-details">
                    <span class="file-name" :title="file.name">{{ file.name }}</span>
                    <span class="file-size" v-if="file.size">{{ formatFileSize(file.size) }}</span>
                  </div>
                  <a :href="file.url" target="_blank" class="file-download-link" title="Скачать">📥</a>
                </div>
              </div>
            </div>

            <!-- Commercial terms -->
            <div class="detail-section" v-if="selectedMatch.tender.payment_terms || selectedMatch.tender.delivery_terms">
              <h4>Коммерческие условия</h4>
              <div class="terms-grid">
                <div v-if="selectedMatch.tender.payment_terms" class="term-card">
                  <strong>Условия оплаты:</strong>
                  <p>{{ selectedMatch.tender.payment_terms }}</p>
                </div>
                <div v-if="selectedMatch.tender.delivery_terms" class="term-card">
                  <strong>Условия поставки:</strong>
                  <p>{{ selectedMatch.tender.delivery_terms }}</p>
                </div>
              </div>
            </div>

            <!-- Original source link -->
            <div class="mt-4">
              <a :href="selectedMatch.tender.url" target="_blank" class="btn btn-secondary btn-block text-center">
                🌐 Открыть на электронной площадке
              </a>
            </div>
          </div>

          <!-- Right side: AI insights and pipeline status -->
          <div class="detail-right">
            <!-- Pipeline Action Panel -->
            <div class="action-panel glass-card border-glow">
              <h4>Проработка сделки</h4>
              <div class="form-group mt-2">
                <label class="form-label">Текущий статус</label>
                <select :value="selectedMatch.status" @change="updatePipelineStatus($event.target.value)" class="form-input">
                  <option value="new">Новый (Неразобранный)</option>
                  <option value="in_work">В работе</option>
                  <option value="accepted">Принят (Готовим КП)</option>
                  <option value="rejected">Отклонен</option>
                  <option value="expired">Срок истек</option>
                </select>
              </div>

              <!-- CRM Export Section -->
              <div class="crm-export-section mt-3">
                <div v-if="selectedMatch.crm_deal_id" class="crm-exported-status">
                  <span class="crm-exported-icon">📤</span>
                  <div class="crm-exported-info">
                    <span class="crm-export-label">Экспортировано в CRM:</span>
                    <a :href="getCrmEntityUrl(selectedMatch)" target="_blank" class="crm-deal-link">
                      Открыть в {{ activeCrmName }} (ID: {{ selectedMatch.crm_deal_id }}) ↗
                    </a>
                  </div>
                </div>
                <div v-else-if="activeCrm" class="crm-export-actions">
                  <button @click="exportToCrm(selectedMatch)" class="btn btn-primary btn-block text-center" :disabled="exporting" style="display: flex; justify-content: center; align-items: center; gap: 0.5rem; width: 100%;">
                    <span v-if="exporting" class="spinner-sm"></span>
                    <span v-else>💼 Экспорт в {{ activeCrmName }}</span>
                  </button>
                </div>
                <div v-else class="crm-no-integration">
                  <span class="info-text">💡 Интеграция с CRM не настроена.</span>
                  <router-link to="/crm-settings" class="setup-link" style="color: var(--primary); text-decoration: underline; margin-left: 0.25rem;">Настроить</router-link>
                </div>
              </div>

              <!-- Match Scoring Details -->
              <div class="match-score-breakdown">
                <div class="score-header">
                  <span>Балл соответствия профилю:</span>
                  <span class="score-badge" :class="getScoreClass(selectedMatch.score)">{{ selectedMatch.score }}%</span>
                </div>
                <div class="matched-keywords-tags mt-2">
                  <span class="label">Совпавшие ключевые слова:</span>
                  <div class="tags-row mt-1">
                    <span v-for="kw in selectedMatch.matched_keywords" :key="kw" class="tag-badge kw">{{ kw }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- AI Insight Section -->
            <div class="ai-insight-panel mt-3">
              <div class="ai-panel-header">
                <span class="ai-sparkle">🤖</span>
                <h4>Анализ искусственного интеллекта (DeepSeek RAG)</h4>
              </div>

              <div v-if="store.tenant?.plan === 'free'" class="ai-empty-analysis premium-locked-box" style="text-align: center; padding: 3rem 1.5rem;">
                <span class="lock-icon" style="font-size: 2.5rem; display: block; margin-bottom: 0.75rem;">🔒</span>
                <h5 style="font-size: 1.1rem; font-weight: 700; margin-bottom: 0.5rem; color: #fff;">Экспертиза ИИ заблокирована</h5>
                <p style="color: var(--text-muted); font-size: 0.9rem; line-height: 1.5; max-width: 420px; margin: 0 auto;">
                  Автоматический ИИ-анализ требований ТЗ, оценка рисков по неустойкам и чат-ассистент доступны только на платных тарифах. Обратитесь к администратору для подключения подписки.
                </p>
              </div>
              <div v-else-if="!selectedMatch.ai_analysis" class="ai-empty-analysis">
                <p>ИИ-экспертиза по данному тендеру еще не проводилась или спецификации не содержали читаемого текста.</p>
              </div>
              <div v-else>
                <!-- AI Tabs -->
                <div class="ai-tabs">
                  <button class="ai-tab-btn" :class="{ active: activeAiTab === 'summary' }" @click="activeAiTab = 'summary'">
                    Резюме
                  </button>
                  <button class="ai-tab-btn" :class="{ active: activeAiTab === 'risks' }" @click="activeAiTab = 'risks'">
                    Риски & Условия
                  </button>
                  <button class="ai-tab-btn" :class="{ active: activeAiTab === 'proposal' }" @click="activeAiTab = 'proposal'">
                    Инструкция для КП
                  </button>
                  <button class="ai-tab-btn" :class="{ active: activeAiTab === 'chat' }" @click="selectChatTab">
                    🤖 Чат-ассистент
                  </button>
                </div>

                <!-- AI Content Area -->
                <div class="ai-tab-content glass-card">
                  <!-- Summary Tab -->
                  <div v-if="activeAiTab === 'summary'" class="ai-content-summary">
                    <div class="relevance-explanation">
                      <strong>Оценка релевантности:</strong>
                      <p>{{ selectedMatch.ai_analysis.relevance_explanation || selectedMatch.reason }}</p>
                    </div>
                    <div class="ai-key-points mt-3" v-if="selectedMatch.ai_analysis.key_points">
                      <strong>Ключевые моменты ТЗ:</strong>
                      <ul>
                        <li v-for="(pt, idx) in selectedMatch.ai_analysis.key_points" :key="idx">{{ pt }}</li>
                      </ul>
                    </div>
                  </div>

                  <!-- Risks Tab -->
                  <div v-if="activeAiTab === 'risks'" class="ai-content-risks">
                    <div class="risks-warnings" v-if="selectedMatch.ai_analysis.risks && selectedMatch.ai_analysis.risks.length > 0">
                      <strong>Выявленные риски:</strong>
                      <div v-for="(risk, idx) in selectedMatch.ai_analysis.risks" :key="idx" class="risk-alert">
                        <span class="risk-icon">⚠</span>
                        <p>{{ risk }}</p>
                      </div>
                    </div>
                    <div v-else class="no-risks-msg">
                      <span class="icon">🛡️</span> Риски по условиям спецификаций не обнаружены.
                    </div>
                  </div>

                  <!-- Proposal Tab -->
                  <div v-if="activeAiTab === 'proposal'" class="ai-content-proposal">
                    <div class="proposal-info" v-if="selectedMatch.ai_analysis.commercial_proposal_info">
                      <div class="proposal-field" v-if="selectedMatch.ai_analysis.commercial_proposal_info.scope">
                        <strong>Необходимый объем работ/поставки:</strong>
                        <p>{{ selectedMatch.ai_analysis.commercial_proposal_info.scope }}</p>
                      </div>
                      <div class="proposal-field mt-3" v-if="selectedMatch.ai_analysis.commercial_proposal_info.requirements">
                        <strong>Ключевые требования к поставщику:</strong>
                        <p>{{ selectedMatch.ai_analysis.commercial_proposal_info.requirements }}</p>
                      </div>
                      <div class="proposal-field mt-3" v-if="selectedMatch.ai_analysis.commercial_proposal_info.budget_notes">
                        <strong>Бюджетные или платежные особенности:</strong>
                        <p>{{ selectedMatch.ai_analysis.commercial_proposal_info.budget_notes }}</p>
                      </div>
                    </div>
                    <div v-else>
                      <p>Инструкции по подготовке КП отсутствуют.</p>
                    </div>
                  </div>

                  <!-- Chat Assistant Tab -->
                  <div v-if="activeAiTab === 'chat'" class="ai-content-chat">
                    <div class="chat-messages-container" ref="chatScrollContainer">
                      <div v-if="chatMessages.length === 0" class="chat-welcome-state">
                        <span class="chat-welcome-icon">💬</span>
                        <h5>ИИ-ассистент по ТЗ</h5>
                        <p>Задайте вопрос по техническому заданию или условиям договора этого тендера. Например:</p>
                        <div class="quick-prompts-grid">
                          <button @click="sendQuickPrompt('Каковы условия и сроки оплаты? Есть ли авансирование?')" class="quick-prompt-btn">
                            💰 Условия оплаты?
                          </button>
                          <button @click="sendQuickPrompt('Каковы требования к опыту работы или квалификации участника?')" class="quick-prompt-btn">
                            🏆 Требования к опыту?
                          </button>
                          <button @click="sendQuickPrompt('Какие штрафы, пени или неустойки предусмотрены договором за просрочку поставки?')" class="quick-prompt-btn">
                            ⚠️ Штрафы и пени?
                          </button>
                        </div>
                      </div>
                      <div v-else class="chat-messages-list">
                        <div v-for="msg in chatMessages" :key="msg.id" class="chat-bubble-wrapper" :class="msg.role">
                          <div class="chat-bubble">
                            <span class="chat-bubble-sender">{{ msg.role === 'user' ? 'Вы' : 'ИИ-Ассистент' }}</span>
                            <div class="chat-bubble-text" style="white-space: pre-line;" v-html="formatMessageText(msg.message)"></div>
                          </div>
                        </div>
                        <div v-if="chatLoading" class="chat-bubble-wrapper assistant typing">
                          <div class="chat-bubble">
                            <span class="chat-bubble-sender">ИИ-Ассистент</span>
                            <div class="typing-indicator">
                              <span></span><span></span><span></span>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                    
                    <div class="chat-input-wrapper">
                      <input
                        type="text"
                        v-model="newChatMessage"
                        @keyup.enter="sendChatMessage"
                        placeholder="Задать вопрос по ТЗ..."
                        class="form-input chat-input"
                        :disabled="chatLoading"
                      />
                      <button @click="sendChatMessage" class="btn btn-primary btn-chat-send" :disabled="chatLoading || !newChatMessage.trim()">
                        ➔
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Historical Winner Analysis (Winner Intelligence) -->
            <div class="winner-intel-panel mt-3 glass-card" v-if="selectedMatch.tender.result">
              <h4>Протокол выбора победителя</h4>
              <div class="winner-details mt-2">
                <div class="winner-row">
                  <span class="label">Победитель:</span>
                  <span class="value font-bold text-success">{{ selectedMatch.tender.result.winner_name || 'Не указан' }}</span>
                </div>
                <div class="winner-row" v-if="selectedMatch.tender.result.winner_unp">
                  <span class="label">УНП Победителя:</span>
                  <span class="value">{{ selectedMatch.tender.result.winner_unp }}</span>
                </div>
                <div class="winner-row">
                  <span class="label">Сумма контракта:</span>
                  <span class="value highlight-value">{{ selectedMatch.tender.result.contract_price }} {{ selectedMatch.tender.result.currency || 'BYN' }}</span>
                </div>
                <div class="winner-row" v-if="selectedMatch.tender.result.status">
                  <span class="label">Статус:</span>
                  <span class="value">{{ selectedMatch.tender.result.status }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { store } from '../store.js'

export default {
  name: 'Matches',
  setup() {
    const matches = ref([])
    const profiles = ref([])
    const loading = ref(false)
    const limit = ref(20)
    const offset = ref(0)
    
    // Filters states
    const selectedProfile = ref(null)
    const searchQuery = ref('')
    const selectedStatus = ref(null) // null represents "All"
    
    // Detailed inspection panel
    const detailPanelOpen = ref(false)
    const selectedMatch = ref(null)
    const activeAiTab = ref('summary')

    // CRM integrations variables
    const activeCrm = ref(null)
    const exporting = ref(false)
    
    // QA Chat variables
    const chatMessages = ref([])
    const newChatMessage = ref('')
    const chatLoading = ref(false)
    const chatScrollContainer = ref(null)
    
    const activeCrmName = computed(() => {
      if (!activeCrm.value) return ''
      if (activeCrm.value.crm_type === 'bitrix24') return 'Битрикс24'
      if (activeCrm.value.crm_type === 'amocrm') return 'amoCRM'
      return ''
    })

    // System stats (to show match count badges)
    const systemStats = ref({})

    const statusTabs = [
      { label: 'Все', value: null },
      { label: 'Новые', value: 'new' },
      { label: 'В работе', value: 'in_work' },
      { label: 'Принято', value: 'accepted' },
      { label: 'Отклонено', value: 'rejected' },
      { label: 'Истекли', value: 'expired' }
    ]

    const fetchProfiles = async () => {
      try {
        const data = await store.fetch('/api/profiles')
        profiles.value = data
      } catch (err) {
        console.error('Failed to load profiles:', err)
      }
    }

    const fetchCrmSettings = async () => {
      try {
        const data = await store.fetch('/api/crm/settings')
        const active = data.find(c => c.is_active)
        activeCrm.value = active || null
      } catch (err) {
        console.error('Failed to fetch CRM settings:', err)
      }
    }

    const exportToCrm = async (match) => {
      if (!match) return
      exporting.value = true
      try {
        const updatedMatch = await store.fetch(`/api/tenders/matches/${match.id}/export-crm`, {
          method: 'POST'
        })
        match.crm_deal_id = updatedMatch.crm_deal_id
        match.status = updatedMatch.status
        alert(`Успешно экспортировано в ${activeCrmName.value}! ID сделки: ${updatedMatch.crm_deal_id}`)
        fetchMatches() // Refresh counts and lists
      } catch (err) {
        alert('Не удалось экспортировать в CRM: ' + err.message)
      } finally {
        exporting.value = false
      }
    }

    const getCrmEntityUrl = (match) => {
      if (!match || !match.crm_deal_id || !activeCrm.value) return '#'
      const crm = activeCrm.value
      if (crm.crm_type === 'amocrm') {
        return `https://${crm.subdomain}.amocrm.ru/leads/detail/${match.crm_deal_id}`
      } else if (crm.crm_type === 'bitrix24') {
        try {
          const urlObj = new URL(crm.webhook_url)
          return `https://${urlObj.host}/crm/deal/details/${match.crm_deal_id}/`
        } catch (e) {
          return '#'
        }
      }
      return '#'
    }

    const selectChatTab = async () => {
      activeAiTab.value = 'chat'
      if (selectedMatch.value) {
        await fetchChatHistory(selectedMatch.value.id)
      }
    }

    const fetchChatHistory = async (matchId) => {
      chatLoading.value = true
      try {
        const data = await store.fetch(`/api/matches/${matchId}/chat`)
        chatMessages.value = data
        scrollChatToBottom()
      } catch (err) {
        console.error('Failed to load chat history:', err)
      } finally {
        chatLoading.value = false
      }
    }

    const sendChatMessage = async () => {
      if (!newChatMessage.value.trim() || !selectedMatch.value || chatLoading.value) return
      
      const userText = newChatMessage.value.trim()
      newChatMessage.value = ''
      chatLoading.value = true
      
      // Instantly push user message to UI to feel highly responsive
      const tempUserMsg = {
        id: Date.now(),
        role: 'user',
        message: userText,
        created_at: new Date().toISOString()
      }
      chatMessages.value.push(tempUserMsg)
      scrollChatToBottom()

      try {
        await store.fetch(`/api/matches/${selectedMatch.value.id}/chat`, {
          method: 'POST',
          body: JSON.stringify({ message: userText })
        })
        
        // Refresh history to retrieve Assistant response and correct IDs
        await fetchChatHistory(selectedMatch.value.id)
      } catch (err) {
        alert('Не удалось отправить сообщение: ' + err.message)
        // Remove temp message if it failed
        chatMessages.value = chatMessages.value.filter(m => m.id !== tempUserMsg.id)
      } finally {
        chatLoading.value = false
      }
    }

    const sendQuickPrompt = (promptText) => {
      newChatMessage.value = promptText
      sendChatMessage()
    }

    const formatMessageText = (text) => {
      if (!text) return ''
      // Replace basic markdown **bold** with <strong>bold</strong>
      let formatted = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      // Replace list bullet points
      formatted = formatted.replace(/^\s*-\s+(.*?)$/gm, '• $1')
      return formatted
    }

    const scrollChatToBottom = () => {
      setTimeout(() => {
        if (chatScrollContainer.value) {
          chatScrollContainer.value.scrollTop = chatScrollContainer.value.scrollHeight
        }
      }, 50)
    }



    const fetchMatches = async () => {
      loading.value = true
      try {
        let endpoint = `/api/matches?limit=${limit.value}&offset=${offset.value}`
        if (selectedProfile.value) {
          endpoint += `&profile_id=${selectedProfile.value}`
        }
        if (selectedStatus.value) {
          endpoint += `&status=${selectedStatus.value}`
        }
        // Client-side text search or backend search
        // Note: the backend `/api/tenders` supports `q`, but `/api/matches` does not natively.
        // We will perform clientside regex filter if a search query is typed, or fetch tenders filtered
        // and match their profiles. For UX simplicity and responsiveness, we will request data 
        // and filter or show matched entries.
        // Wait, does the API support search query on matches? Let's check main.py matches endpoint definition:
        // No, `matches` endpoint takes limit, offset, profile_id, status.
        // So we can do a clientside query on the returned list, or query the `/api/tenders?matched_only=true&q=...`
        // Wait! The easiest and most flexible is to load matches, and if searchQuery is present, we filter 
        // them. In real usage, clientside filter on the page works instantly.
        
        const data = await store.fetch(endpoint)
        
        if (searchQuery.value) {
          const q = searchQuery.value.toLowerCase()
          matches.value = data.items.filter(item => {
            return (
              item.tender.title.toLowerCase().includes(q) ||
              (item.tender.customer_name && item.tender.customer_name.toLowerCase().includes(q)) ||
              item.matched_keywords.some(k => k.toLowerCase().includes(q))
            );
          })
        } else {
          matches.value = data.items
        }

        // Fetch counts for badges
        const statsData = await store.fetch('/api/stats')
        systemStats.value = statsData.stats || {}
      } catch (err) {
        console.error('Failed to fetch matches:', err)
      } finally {
        loading.value = false
      }
    }

    // Debounced search trigger
    let searchTimeout = null
    const debouncedSearch = () => {
      if (searchTimeout) clearTimeout(searchTimeout)
      searchTimeout = setTimeout(() => {
        offset.value = 0
        fetchMatches()
      }, 300)
    }

    const clearSearch = () => {
      searchQuery.value = ''
      offset.value = 0
      fetchMatches()
    }

    const selectStatusTab = (status) => {
      selectedStatus.value = status
      offset.value = 0
      fetchMatches()
    }

    const getTabCount = (statusVal) => {
      if (!systemStats.value) return null
      if (statusVal === null) return systemStats.value.total_matches
      if (statusVal === 'new') return systemStats.value.new_matches
      if (statusVal === 'in_work' || statusVal === 'processed') return systemStats.value.processed_matches
      if (statusVal === 'accepted') return systemStats.value.sent_notifications // as indicator of processed/sent alerts
      if (statusVal === 'rejected') return null
      if (statusVal === 'expired') return systemStats.value.expired_matches
      return null
    }

    const getScoreClass = (score) => {
      if (score >= 80) return 'score-high'
      if (score >= 50) return 'score-medium'
      return 'score-low'
    }

    const formatDate = (isoString) => {
      if (!isoString) return ''
      try {
        const date = new Date(isoString)
        if (isNaN(date.getTime())) return isoString
        return date.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
      } catch (e) {
        return isoString
      }
    }

    const formatFileSize = (bytes) => {
      if (!bytes) return '0 B'
      const k = 1024
      const sizes = ['B', 'KB', 'MB', 'GB']
      const i = Math.floor(Math.log(bytes) / Math.log(k))
      return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
    }

    const truncateText = (text, len) => {
      if (!text) return ''
      return text.length > len ? text.substring(0, len) + '...' : text
    }

    const formatStatusName = (status) => {
      const dict = {
        'new': 'Новый',
        'processed': 'В обработке',
        'in_work': 'В работе',
        'accepted': 'Принят',
        'rejected': 'Отклонен',
        'expired': 'Истек',
        'rejected_by_ai': 'Отклонен ИИ'
      }
      return dict[status] || status
    }

    const isDeadlineClose = (deadlineString) => {
      if (!deadlineString) return false
      const deadline = new Date(deadlineString)
      if (isNaN(deadline.getTime())) return false
      const diff = deadline.getTime() - Date.now()
      // Less than 2 days left
      return diff > 0 && diff < 2 * 24 * 60 * 60 * 1000
    }

    const quickStatusUpdate = async (matchId, newStatus) => {
      try {
        await store.fetch(`/api/matches/${matchId}/status`, {
          method: 'PUT',
          body: JSON.stringify({ status: newStatus })
        })
        fetchMatches()
        if (selectedMatch.value && selectedMatch.value.id === matchId) {
          selectedMatch.value.status = newStatus
        }
      } catch (err) {
        alert('Не удалось обновить статус: ' + err.message)
      }
    }

    const openDetailPanel = (match) => {
      selectedMatch.value = match
      activeAiTab.value = 'summary'
      chatMessages.value = []
      newChatMessage.value = ''
      detailPanelOpen.value = true
    }

    const closeDetailPanel = () => {
      detailPanelOpen.value = false
      selectedMatch.value = null
      chatMessages.value = []
      newChatMessage.value = ''
    }

    const updatePipelineStatus = (newStatus) => {
      if (selectedMatch.value) {
        quickStatusUpdate(selectedMatch.value.id, newStatus)
      }
    }

    const downloadExcel = () => {
      let url = `${store.apiUrl}/api/reports/export/excel`
      const params = []
      if (selectedProfile.value) params.push(`profile_id=${selectedProfile.value}`)
      if (selectedStatus.value) params.push(`status=${selectedStatus.value}`)
      if (params.length > 0) {
        url += '?' + params.join('&')
      }

      // Download file using window or token headers if auth is active
      if (store.token) {
        // Fetch with auth, convert to blob and trigger download
        store.isLoading = true
        fetch(url, {
          headers: {
            'Authorization': `Bearer ${store.token}`
          }
        })
        .then(response => {
          if (!response.ok) throw new Error('Ошибка скачивания файла')
          return response.blob()
        })
        .then(blob => {
          const downloadUrl = window.URL.createObjectURL(blob)
          const a = document.createElement('a')
          a.href = downloadUrl
          a.download = `tenders_report_${new Date().toISOString().slice(0, 10)}.xlsx`
          document.body.appendChild(a)
          a.click()
          a.remove()
        })
        .catch(err => alert('Ошибка при выгрузке Excel: ' + err.message))
        .finally(() => { store.isLoading = false })
      } else {
        window.open(url)
      }
    }

    const prevPage = () => {
      if (offset.value >= limit.value) {
        offset.value -= limit.value
        fetchMatches()
      }
    }

    const nextPage = () => {
      offset.value += limit.value
      fetchMatches()
    }

    onMounted(() => {
      fetchProfiles()
      fetchMatches()
      fetchCrmSettings()
    })

    return {
      matches,
      profiles,
      loading,
      limit,
      offset,
      selectedProfile,
      searchQuery,
      selectedStatus,
      statusTabs,
      detailPanelOpen,
      selectedMatch,
      activeAiTab,
      debouncedSearch,
      clearSearch,
      selectStatusTab,
      getTabCount,
      getScoreClass,
      formatDate,
      formatFileSize,
      truncateText,
      formatStatusName,
      isDeadlineClose,
      quickStatusUpdate,
      openDetailPanel,
      closeDetailPanel,
      updatePipelineStatus,
      downloadExcel,
      prevPage,
      nextPage,
      activeCrm,
      exporting,
      activeCrmName,
      exportToCrm,
      getCrmEntityUrl,
      chatMessages,
      newChatMessage,
      chatLoading,
      chatScrollContainer,
      selectChatTab,
      sendChatMessage,
      sendQuickPrompt,
      formatMessageText
    }
  }
}
</script>

<style scoped>
.matches-view {
  animation: fadeIn 0.4s ease-out;
}
.filters-panel {
  margin-bottom: 1.5rem;
  background: rgba(17, 24, 39, 0.4);
}
.filters-grid {
  display: grid;
  grid-template-columns: 1fr 2fr;
  gap: 1.5rem;
}
@media (max-width: 768px) {
  .filters-grid {
    grid-template-columns: 1fr;
  }
}

.search-input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}
.clear-search-btn {
  position: absolute;
  right: 1rem;
  cursor: pointer;
  font-size: 1.25rem;
  color: var(--text-muted);
  transition: color 0.2s;
}
.clear-search-btn:hover {
  color: white;
}

.status-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 1.5rem;
  border-bottom: 1px solid var(--border-card);
  padding-bottom: 0.75rem;
}
.tab-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  padding: 0.5rem 1rem;
  cursor: pointer;
  font-weight: 600;
  font-size: 0.95rem;
  border-radius: var(--radius-sm);
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.tab-btn:hover {
  color: var(--text-main);
  background: rgba(255, 255, 255, 0.02);
}
.tab-btn.active {
  color: var(--text-inverse);
  background: linear-gradient(90deg, rgba(59, 130, 246, 0.2) 0%, rgba(139, 92, 246, 0.05) 100%);
  border-left: 2px solid var(--primary);
}
.tab-count {
  font-size: 0.75rem;
  padding: 0.1rem 0.4rem;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 20px;
  color: var(--text-main);
}
.tab-btn.active .tab-count {
  background: var(--primary);
  color: white;
}

.matches-card {
  padding: 0;
  border: 1px solid var(--border-card);
  overflow: hidden;
}

.tender-cell {
  max-width: 320px;
}
.tender-title-link {
  color: var(--text-main);
  text-decoration: none;
  font-weight: 600;
  font-family: var(--font-display);
  font-size: 0.95rem;
  transition: color 0.2s;
}
.tender-title-link:hover {
  color: var(--primary);
}
.tender-subinfo {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.25rem;
  font-size: 0.75rem;
}
.source-tag {
  color: var(--info);
  background: var(--info-bg);
  padding: 0.1rem 0.35rem;
  border-radius: 4px;
  text-transform: uppercase;
  font-weight: 700;
}
.number-tag {
  color: var(--text-muted);
}

.ai-relevance-badge {
  font-size: 0.75rem;
  font-weight: 700;
  padding: 0.15rem 0.5rem;
  border-radius: 20px;
  text-transform: uppercase;
}
.ai-relevance-badge.positive { background: var(--success-bg); color: var(--success); }
.ai-relevance-badge.negative { background: var(--error-bg); color: var(--error); }
.ai-relevance-badge.pending { background: rgba(255, 255, 255, 0.05); color: var(--text-muted); }

.score-badge {
  font-family: var(--font-display);
  font-weight: 700;
  padding: 0.25rem 0.5rem;
  border-radius: var(--radius-sm);
  font-size: 0.85rem;
}
.score-badge.score-high {
  background: var(--success-bg);
  color: var(--success);
  box-shadow: 0 0 10px rgba(16, 185, 129, 0.1);
}
.score-badge.score-medium {
  background: var(--info-bg);
  color: var(--info);
}
.score-badge.score-low {
  background: var(--warning-bg);
  color: var(--warning);
}

.deadline-cell.deadline-danger {
  color: var(--error);
  font-weight: 600;
  animation: pulseGlow 1.5s infinite alternate;
}

@keyframes pulseGlow {
  from { text-shadow: 0 0 2px rgba(244, 63, 94, 0.1); }
  to { text-shadow: 0 0 8px rgba(244, 63, 94, 0.4); }
}

.action-buttons-cell {
  display: flex;
  justify-content: center;
  gap: 0.4rem;
}
.quick-btn {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border-card);
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.8rem;
  font-weight: bold;
  transition: all 0.2s;
}
.quick-btn:hover {
  background: rgba(255, 255, 255, 0.08);
}
.quick-btn.accept:hover {
  border-color: var(--success);
  color: var(--success);
  background: var(--success-bg);
}
.quick-btn.reject:hover {
  border-color: var(--error);
  color: var(--error);
  background: var(--error-bg);
}

.pagination-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.5rem;
  background: rgba(0, 0, 0, 0.15);
  border-top: 1px solid var(--border-card);
}
.pagination-info {
  font-size: 0.85rem;
  color: var(--text-muted);
}

.table-loading-state {
  text-align: center;
  padding: 4rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
}

/* Detail panel modal */
.detail-panel-content {
  max-width: 1050px;
  width: 95vw;
}
.detail-header-title {
  display: flex;
  align-items: center;
  gap: 1rem;
}
.detail-grid {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 2rem;
  margin-top: 1rem;
}
@media (max-width: 992px) {
  .detail-grid {
    grid-template-columns: 1fr;
  }
}

.tender-full-title {
  font-family: var(--font-display);
  font-size: 1.4rem;
  font-weight: 700;
  line-height: 1.3;
  margin-bottom: 1.5rem;
}

.info-blocks-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.25rem;
  background: rgba(0, 0, 0, 0.2);
  padding: 1rem;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-card);
}
.info-block {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.info-block .label {
  font-size: 0.75rem;
  color: var(--text-muted);
  font-weight: 600;
}
.info-block .value {
  font-size: 0.9rem;
  font-weight: 500;
}
.info-block .highlight-value {
  color: #60a5fa;
  font-weight: 700;
  font-family: var(--font-display);
}

.detail-section {
  margin-top: 1.5rem;
}
.detail-section h4 {
  font-family: var(--font-display);
  font-size: 1.05rem;
  font-weight: 600;
  margin-bottom: 0.75rem;
  border-left: 3px solid var(--primary);
  padding-left: 0.5rem;
}
.description-text {
  font-size: 0.9rem;
  color: var(--text-muted);
  background: rgba(255, 255, 255, 0.01);
  padding: 0.75rem 1rem;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-card);
  max-height: 200px;
  overflow-y: auto;
  white-space: pre-line;
}

/* Lots list */
.lots-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.lot-item {
  background: rgba(255, 255, 255, 0.015);
  border: 1px solid var(--border-card);
  padding: 0.65rem 0.85rem;
  border-radius: var(--radius-sm);
  font-size: 0.85rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.lot-price {
  color: #60a5fa;
  font-weight: 600;
}

/* Attachments */
.attachments-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 0.75rem;
}
.attachment-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background: rgba(255, 255, 255, 0.015);
  border: 1px solid var(--border-card);
  padding: 0.5rem 0.75rem;
  border-radius: var(--radius-sm);
  font-size: 0.8rem;
  overflow: hidden;
}
.file-details {
  display: flex;
  flex-direction: column;
  flex-grow: 1;
  overflow: hidden;
}
.file-name {
  white-space: nowrap;
  text-overflow: ellipsis;
  overflow: hidden;
}
.file-size {
  font-size: 0.7rem;
  color: var(--text-muted);
}
.file-download-link {
  color: var(--text-muted);
  text-decoration: none;
  font-size: 0.95rem;
}
.file-download-link:hover {
  color: white;
}

/* Terms */
.terms-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}
@media (max-width: 576px) {
  .terms-grid {
    grid-template-columns: 1fr;
  }
}
.term-card {
  background: rgba(255, 255, 255, 0.01);
  border: 1px dashed var(--border-card);
  padding: 0.75rem;
  border-radius: var(--radius-sm);
  font-size: 0.85rem;
}
.term-card strong {
  font-size: 0.8rem;
  color: var(--text-muted);
}
.term-card p {
  margin-top: 0.25rem;
}

/* Right side action panel */
.action-panel h4 {
  font-family: var(--font-display);
  font-size: 1.1rem;
  font-weight: 600;
}
.border-glow {
  border-color: var(--border-card-focus);
  box-shadow: var(--shadow-glow);
}
.match-score-breakdown {
  margin-top: 1rem;
  border-top: 1px solid var(--border-card);
  padding-top: 1rem;
}
.score-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.85rem;
}

/* AI Insight Panel */
.ai-insight-panel {
  border: 1px solid rgba(139, 92, 246, 0.25);
  border-radius: var(--radius-lg);
  overflow: hidden;
  background: radial-gradient(circle at top right, rgba(139, 92, 246, 0.04), transparent 40%);
}
.ai-panel-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background: rgba(139, 92, 246, 0.08);
  padding: 0.75rem 1rem;
  border-bottom: 1px solid rgba(139, 92, 246, 0.15);
}
.ai-panel-header h4 {
  font-family: var(--font-display);
  font-size: 0.95rem;
  font-weight: 700;
  color: #a78bfa;
}
.ai-sparkle {
  font-size: 1.1rem;
  animation: sparkle 1.5s infinite alternate;
}
@keyframes sparkle {
  from { transform: scale(1); filter: brightness(1); }
  to { transform: scale(1.15); filter: brightness(1.3); }
}

.ai-empty-analysis {
  padding: 2rem;
  text-align: center;
  font-size: 0.85rem;
  color: var(--text-muted);
}

.ai-tabs {
  display: flex;
  background: rgba(0, 0, 0, 0.2);
  border-bottom: 1px solid var(--border-card);
}
.ai-tab-btn {
  flex-grow: 1;
  background: transparent;
  border: none;
  padding: 0.65rem 0.5rem;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.2s;
}
.ai-tab-btn:hover {
  color: white;
}
.ai-tab-btn.active {
  color: #c084fc;
  background: rgba(139, 92, 246, 0.05);
  border-bottom: 2px solid var(--secondary);
}

.ai-tab-content {
  border-radius: 0;
  border-top: none;
  border-left: none;
  border-right: none;
  min-height: 180px;
  max-height: 350px;
  overflow-y: auto;
  font-size: 0.9rem;
  line-height: 1.45;
}
.relevance-explanation p {
  color: var(--text-muted);
}
.ai-key-points ul {
  padding-left: 1.25rem;
  margin-top: 0.5rem;
  color: var(--text-muted);
}
.ai-key-points li {
  margin-bottom: 0.4rem;
}

.risk-alert {
  display: flex;
  gap: 0.5rem;
  background: rgba(244, 63, 94, 0.08);
  border: 1px solid rgba(244, 63, 94, 0.15);
  padding: 0.5rem 0.75rem;
  border-radius: var(--radius-sm);
  margin-top: 0.5rem;
  font-size: 0.85rem;
}
.risk-icon {
  color: var(--error);
  font-weight: bold;
}
.no-risks-msg {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--success);
  padding: 1rem;
}

.proposal-field strong {
  font-size: 0.8rem;
  color: var(--text-muted);
}
.proposal-field p {
  margin-top: 0.25rem;
}

/* Winner intelligence panel */
.winner-intel-panel h4 {
  font-family: var(--font-display);
  font-size: 1.05rem;
  font-weight: 600;
}
.winner-details {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.winner-row {
  display: flex;
  justify-content: space-between;
  font-size: 0.85rem;
  border-bottom: 1px dashed rgba(255, 255, 255, 0.05);
  padding-bottom: 0.35rem;
}
.winner-row:last-child {
  border-bottom: none;
}
.winner-row .label {
  color: var(--text-muted);
}
.winner-row .value {
  font-weight: 600;
}
.winner-row .font-bold {
  font-weight: 700;
}

.mt-4 { margin-top: 1rem; }
.mb-0 { margin-bottom: 0; }
.text-center { text-align: center; }

.crm-export-section {
  border-top: 1px solid var(--border-card);
  padding-top: 1rem;
}
.crm-exported-status {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.2);
  padding: 0.75rem;
  border-radius: var(--radius-sm);
}
.crm-exported-icon {
  font-size: 1.25rem;
}
.crm-exported-info {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.crm-export-label {
  font-size: 0.75rem;
  color: var(--text-muted);
}
.crm-deal-link {
  color: #10b981;
  font-weight: 600;
  font-size: 0.85rem;
  text-decoration: underline;
}
.crm-deal-link:hover {
  color: #34d399;
}
.crm-no-integration {
  font-size: 0.85rem;
  color: var(--text-muted);
}
.spinner-sm {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.2);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  display: inline-block;
}

/* QA Chat styles */
.ai-content-chat {
  display: flex;
  flex-direction: column;
  height: 380px;
}
.chat-messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 0.75rem;
  margin-bottom: 0.75rem;
  background: rgba(0, 0, 0, 0.2);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-card);
}
.chat-welcome-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  text-align: center;
  padding: 1.5rem;
}
.chat-welcome-icon {
  font-size: 2.2rem;
  margin-bottom: 0.5rem;
}
.chat-welcome-state h5 {
  margin: 0 0 0.5rem 0;
  font-size: 1rem;
  color: var(--text-main);
}
.chat-welcome-state p {
  margin: 0 0 1rem 0;
  font-size: 0.85rem;
  color: var(--text-muted);
}
.quick-prompts-grid {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  width: 100%;
}
.quick-prompt-btn {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border-card);
  color: var(--text-main);
  padding: 0.5rem;
  font-size: 0.8rem;
  text-align: left;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}
.quick-prompt-btn:hover {
  background: rgba(59, 130, 246, 0.1);
  border-color: var(--primary);
}
.chat-messages-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.chat-bubble-wrapper {
  display: flex;
  width: 100%;
}
.chat-bubble-wrapper.user {
  justify-content: flex-end;
}
.chat-bubble {
  max-width: 85%;
  padding: 0.65rem 0.85rem;
  border-radius: 12px;
  font-size: 0.85rem;
  line-height: 1.4;
  position: relative;
}
.chat-bubble-wrapper.user .chat-bubble {
  background: linear-gradient(135deg, var(--primary), #2563eb);
  color: white;
  border-bottom-right-radius: 2px;
}
.chat-bubble-wrapper.assistant .chat-bubble {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border-card);
  color: var(--text-main);
  border-bottom-left-radius: 2px;
}
.chat-bubble-sender {
  display: block;
  font-size: 0.7rem;
  font-weight: 700;
  margin-bottom: 0.25rem;
  opacity: 0.8;
}
.chat-input-wrapper {
  display: flex;
  gap: 0.5rem;
}
.chat-input {
  flex: 1;
  background: rgba(0, 0, 0, 0.3);
}
.btn-chat-send {
  padding: 0 1rem;
  display: flex;
  align-items: center;
  justify-content: center;
}
.typing-indicator {
  display: flex;
  align-items: center;
  gap: 3px;
  height: 14px;
}
.typing-indicator span {
  width: 6px;
  height: 6px;
  background: var(--text-muted);
  border-radius: 50%;
  animation: typing 1s infinite alternate;
}
.typing-indicator span:nth-child(2) {
  animation-delay: 0.2s;
}
.typing-indicator span:nth-child(3) {
  animation-delay: 0.4s;
}
@keyframes typing {
  from { opacity: 0.3; transform: translateY(0); }
  to { opacity: 1; transform: translateY(-4px); }
}
</style>
