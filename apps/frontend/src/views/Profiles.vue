<template>
  <div class="profiles-view">
    <div class="page-header">
      <div class="page-title">
        <h2>Профили поиска</h2>
        <p>Настройте параметры мониторинга и ключевые слова для поиска тендеров.</p>
      </div>
      <button @click="openCreateModal" class="btn btn-primary">
        <span>+</span> Создать профиль
      </button>
    </div>

    <!-- Profiles Grid -->
    <div v-if="profiles.length === 0" class="glass-card empty-state">
      <div class="empty-icon">🔍</div>
      <h3>Нет активных профилей</h3>
      <p>Создайте свой первый поисковый профиль, чтобы начать отслеживание закупок.</p>
      <button @click="openCreateModal" class="btn btn-primary btn-sm">Создать профиль</button>
    </div>
    <div v-else class="profiles-grid">
      <div v-for="profile in profiles" :key="profile.id" class="glass-card profile-card" :class="{ inactive: !profile.is_active }">
        <div class="profile-card-header">
          <div class="profile-meta">
            <span class="preset-badge" :class="profile.preset_code">{{ getPresetName(profile.preset_code) }}</span>
            <div class="status-toggle-wrapper">
              <label class="switch">
                <input type="checkbox" :checked="profile.is_active" @change="toggleProfileStatus(profile)" />
                <span class="slider round"></span>
              </label>
              <span class="status-text">{{ profile.is_active ? 'Активен' : 'Пауза' }}</span>
            </div>
          </div>
          <div class="profile-actions">
            <button @click="openEditModal(profile)" class="action-btn edit" title="Редактировать">✏️</button>
            <button @click="deleteProfile(profile.id)" class="action-btn delete" title="Удалить">🗑️</button>
          </div>
        </div>

        <h3 class="profile-name">{{ profile.name }}</h3>
        <p class="profile-desc">{{ profile.description || 'Без описания' }}</p>

        <!-- Keywords Summary -->
        <div class="keywords-summary">
          <div class="keyword-section">
            <span class="section-label">Ключевые слова:</span>
            <div class="tags-row">
              <span v-for="kw in parseKeywords(profile.keywords)" :key="kw" class="tag-badge kw">{{ kw }}</span>
              <span v-if="!profile.keywords" class="no-tags">Не заданы</span>
            </div>
          </div>
          <div class="keyword-section mt-2">
            <span class="section-label">Минус-слова:</span>
            <div class="tags-row">
              <span v-for="kw in parseKeywords(profile.negative_keywords)" :key="kw" class="tag-badge neg-kw">{{ kw }}</span>
              <span v-if="!profile.negative_keywords" class="no-tags">Не заданы</span>
            </div>
          </div>
          <div class="keyword-section mt-2">
            <span class="section-label">Регионы поиска:</span>
            <div class="tags-row">
              <span v-for="reg in (profile.regions || [])" :key="reg" class="tag-badge region-tag">{{ getRegionName(reg) }}</span>
              <span v-if="!profile.regions || profile.regions.length === 0" class="no-tags">Вся Беларусь</span>
            </div>
          </div>
        </div>

        <div class="profile-footer-stats">
          <div class="stat-item">
            <span class="label">Минимальный балл:</span>
            <span class="value">{{ profile.min_score || 0 }}</span>
          </div>
          <div class="stat-item">
            <span class="label">Интервал:</span>
            <span class="value">{{ formatSchedule(profile.schedule_interval) }}</span>
          </div>
        </div>

        <!-- Notification Channels Accordion -->
        <div class="channels-accordion">
          <button @click="toggleChannelsExpander(profile.id)" class="btn-channels-toggle">
            <span>🔔 Уведомления и боты</span>
            <span class="arrow" :class="{ expanded: expandedProfileChannels === profile.id }">▼</span>
          </button>
          
          <div v-if="expandedProfileChannels === profile.id" class="channels-panel">
            <div v-if="loadingChannels" class="panel-loader">Загрузка...</div>
            <div v-else class="channels-list">
              <!-- Telegram Channel -->
              <div class="channel-item">
                <div class="channel-info">
                  <span class="channel-icon telegram">✈</span>
                  <div>
                    <strong>Telegram бот</strong>
                    <p class="channel-desc">Рассылка карточек тендеров с ИИ-анализом</p>
                  </div>
                </div>
                <div class="channel-config-form">
                  <div class="channel-toggle-row">
                    <label class="switch switch-sm">
                      <input type="checkbox" v-model="channelsConfig.telegram.is_active" />
                      <span class="slider round"></span>
                    </label>
                    <span class="toggle-label">{{ channelsConfig.telegram.is_active ? 'Включен' : 'Выключен' }}</span>
                  </div>
                  <input
                    type="text"
                    placeholder="Chat ID (например -1001234567)"
                    v-model="channelsConfig.telegram.chat_id"
                    class="form-input form-input-sm"
                  />
                </div>
              </div>

              <!-- Viber Channel -->
              <div class="channel-item mt-3">
                <div class="channel-info">
                  <span class="channel-icon viber">💬</span>
                  <div>
                    <strong>Viber чат</strong>
                    <p class="channel-desc">Интеграция с Viber паблик-аккаунтом</p>
                  </div>
                </div>
                <div class="channel-config-form">
                  <div class="channel-toggle-row">
                    <label class="switch switch-sm">
                      <input type="checkbox" v-model="channelsConfig.viber.is_active" />
                      <span class="slider round"></span>
                    </label>
                    <span class="toggle-label">{{ channelsConfig.viber.is_active ? 'Включен' : 'Выключен' }}</span>
                  </div>
                  <input
                    type="text"
                    placeholder="Токен или Номер"
                    v-model="channelsConfig.viber.chat_id"
                    class="form-input form-input-sm"
                  />
                </div>
              </div>

              <button @click="saveChannels(profile.id)" class="btn btn-secondary btn-sm btn-block mt-3">
                Сохранить каналы
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Create/Edit Modal -->
    <div v-if="modalOpen" class="modal-overlay" @click.self="closeModal">
      <div class="glass-card modal-content">
        <div class="modal-header">
          <h3>{{ editingProfileId ? 'Редактировать профиль поиска' : 'Создать профиль поиска' }}</h3>
          <button @click="closeModal" class="modal-close">&times;</button>
        </div>

        <form @submit.prevent="saveProfile">
          <!-- Preset Selector -->
          <div class="form-group">
            <label class="form-label">Шаблон ниши (Пресет)</label>
            <select v-model="form.preset_code" @change="applyPreset" class="form-input">
              <option v-for="preset in presets" :key="preset.code" :value="preset.code">
                {{ preset.name }}
              </option>
            </select>
          </div>

          <div class="form-group">
            <label class="form-label">Название профиля</label>
            <input type="text" v-model="form.name" class="form-input" placeholder="Например: Вентиляция Минск" required />
          </div>

          <div class="form-group" v-if="form.preset_code !== 'custom'">
            <label class="form-label">Описание ниши для AI-фильтрации</label>
            <textarea v-model="form.description" class="form-input" rows="3" placeholder="Укажите критерии релевантности для нейросети..."></textarea>
          </div>

          <div class="form-group">
            <label class="form-label">Регионы (Если ничего не выбрано — поиск по всей Беларуси)</label>
            <div class="regions-grid">
              <label class="checkbox-container" v-for="r in availableRegions" :key="r.code">
                <input type="checkbox" :value="r.code" v-model="form.regions" />
                <span class="checkbox-label">{{ r.name }}</span>
              </label>
            </div>
          </div>

          <!-- Keywords Chip Inputs -->
          <div class="form-group">
            <label class="form-label">Ключевые слова (Enter или Запятая для разделения)</label>
            <div class="tags-input-container">
              <span v-for="(tag, index) in formKeywords" :key="index" class="tag-chip">
                {{ tag }}
                <span @click="removeFormKeyword(index)" class="remove-tag">&times;</span>
              </span>
              <input
                type="text"
                v-model="newKeywordInput"
                placeholder="Добавить слово..."
                @keydown.enter.prevent="addFormKeyword"
                @keydown.comma.prevent="addFormKeyword"
                @blur="addFormKeyword"
                class="tag-field-input"
              />
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">Минус-слова (Исключить из выдачи)</label>
            <div class="tags-input-container">
              <span v-for="(tag, index) in formNegativeKeywords" :key="index" class="tag-chip negative">
                {{ tag }}
                <span @click="removeFormNegativeKeyword(index)" class="remove-tag">&times;</span>
              </span>
              <input
                type="text"
                v-model="newNegativeKeywordInput"
                placeholder="Исключить слово..."
                @keydown.enter.prevent="addFormNegativeKeyword"
                @keydown.comma.prevent="addFormNegativeKeyword"
                @blur="addFormNegativeKeyword"
                class="tag-field-input"
              />
            </div>
          </div>

          <div class="form-row-2">
            <div class="form-group">
              <label class="form-label">Минимальный балл релевантности: {{ form.min_score }}</label>
              <div class="range-slider-wrapper">
                <input type="range" v-model.number="form.min_score" min="0" max="100" class="range-slider" />
              </div>
            </div>

            <div class="form-group">
              <label class="form-label">Интервал автоматического сбора</label>
              <select v-model="form.schedule_interval" class="form-input">
                <option value="manual">Вручную</option>
                <option value="1h">Раз в час</option>
                <option value="4h">Раз в 4 часа</option>
                <option value="12h">Раз в 12 часов</option>
                <option value="24h">Раз в сутки</option>
              </select>
            </div>
          </div>

          <div class="modal-footer">
            <button type="button" @click="closeModal" class="btn btn-secondary">Отмена</button>
            <button type="submit" class="btn btn-primary" :disabled="saving">
              {{ saving ? 'Сохранение...' : 'Сохранить' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { store } from '../store.js'

export default {
  name: 'Profiles',
  setup() {
    const profiles = ref([])
    const presets = ref([])
    const modalOpen = ref(false)
    const editingProfileId = ref(null)
    const saving = ref(false)

    const availableRegions = [
      { code: '1', name: 'Брестская область' },
      { code: '2', name: 'Витебская область' },
      { code: '3', name: 'Гомельская область' },
      { code: '4', name: 'Гродненская область' },
      { code: '5', name: 'г. Минск' },
      { code: '6', name: 'Минская область' },
      { code: '7', name: 'Могилевская область' }
    ]

    const getRegionName = (code) => {
      const regionsMap = {
        '1': 'Брестская обл.',
        '2': 'Витебская обл.',
        '3': 'Гомельская обл.',
        '4': 'Гродненская обл.',
        '5': 'г. Минск',
        '6': 'Минская обл.',
        '7': 'Могилевская обл.'
      }
      return regionsMap[code] || code
    }

    // Form states
    const form = ref({
      name: '',
      preset_code: 'custom',
      description: '',
      min_score: 50,
      schedule_interval: 'manual',
      is_active: true,
      regions: []
    })

    const formKeywords = ref([])
    const newKeywordInput = ref('')
    const formNegativeKeywords = ref([])
    const newNegativeKeywordInput = ref('')

    // Channels states
    const expandedProfileChannels = ref(null)
    const loadingChannels = ref(false)
    const channelsConfig = ref({
      telegram: { is_active: false, chat_id: '' },
      viber: { is_active: false, chat_id: '' }
    })

    const fetchProfiles = async () => {
      try {
        const data = await store.fetch('/api/profiles')
        profiles.value = data
      } catch (err) {
        console.error('Failed to load profiles:', err)
      }
    }

    const fetchPresets = async () => {
      try {
        const data = await store.fetch('/api/presets')
        presets.value = data
      } catch (err) {
        console.error('Failed to load presets:', err)
      }
    }

    const getPresetName = (code) => {
      const preset = presets.value.find(p => p.code === code)
      return preset ? preset.name : 'Кастомный'
    }

    const parseKeywords = (kw) => {
      if (!kw) return []
      if (Array.isArray(kw)) return kw
      if (typeof kw === 'string') {
        return kw.split(',').map(s => s.trim()).filter(Boolean)
      }
      return []
    }

    const formatSchedule = (interval) => {
      if (!interval) return 'Вручную'
      const dict = {
        '1h': '1 час',
        '4h': '4 часа',
        '12h': '12 часов',
        '24h': 'Сутки'
      }
      return dict[interval] || interval
    }

    const openCreateModal = () => {
      editingProfileId.value = null
      form.value = {
        name: '',
        preset_code: 'custom',
        description: '',
        min_score: 50,
        schedule_interval: 'manual',
        is_active: true,
        regions: []
      }
      formKeywords.value = []
      formNegativeKeywords.value = []
      newKeywordInput.value = ''
      newNegativeKeywordInput.value = ''
      modalOpen.value = true
    }

    const openEditModal = (profile) => {
      editingProfileId.value = profile.id
      form.value = {
        name: profile.name,
        preset_code: profile.preset_code || 'custom',
        description: profile.description || '',
        min_score: profile.min_score || 50,
        schedule_interval: profile.schedule_interval || 'manual',
        is_active: profile.is_active,
        regions: profile.regions ? [...profile.regions] : []
      }
      formKeywords.value = parseKeywords(profile.keywords)
      formNegativeKeywords.value = parseKeywords(profile.negative_keywords)
      newKeywordInput.value = ''
      newNegativeKeywordInput.value = ''
      modalOpen.value = true
    }

    const applyPreset = () => {
      const code = form.value.preset_code
      const preset = presets.value.find(p => p.code === code)
      if (preset && code !== 'custom') {
        form.value.name = preset.name
        form.value.description = preset.description
        formKeywords.value = [...preset.default_keywords]
        formNegativeKeywords.value = [...preset.default_negative_keywords]
      }
    }

    // Tag Inputs keywords logic
    const addFormKeyword = () => {
      let val = newKeywordInput.value.replace(/,/g, '').trim()
      if (val) {
        if (!formKeywords.value.includes(val)) {
          formKeywords.value.push(val)
        }
        newKeywordInput.value = ''
      }
    }
    const removeFormKeyword = (index) => {
      formKeywords.value.splice(index, 1)
    }

    // Tag Inputs negative keywords logic
    const addFormNegativeKeyword = () => {
      let val = newNegativeKeywordInput.value.replace(/,/g, '').trim()
      if (val) {
        if (!formNegativeKeywords.value.includes(val)) {
          formNegativeKeywords.value.push(val)
        }
        newNegativeKeywordInput.value = ''
      }
    }
    const removeFormNegativeKeyword = (index) => {
      formNegativeKeywords.value.splice(index, 1)
    }

    const saveProfile = async () => {
      saving.value = true
      // Commit pending tag inputs
      addFormKeyword()
      addFormNegativeKeyword()

      const payload = {
        name: form.value.name,
        description: form.value.description,
        preset_code: form.value.preset_code,
        niche_description: form.value.preset_code !== 'custom' ? form.value.description : '',
        keywords: formKeywords.value,
        negative_keywords: formNegativeKeywords.value,
        min_score: form.value.min_score,
        is_active: form.value.is_active,
        schedule_interval: form.value.schedule_interval,
        regions: form.value.regions
      }

      try {
        if (editingProfileId.value) {
          await store.fetch(`/api/profiles/${editingProfileId.value}`, {
            method: 'PUT',
            body: JSON.stringify(payload)
          })
        } else {
          await store.fetch('/api/profiles', {
            method: 'POST',
            body: JSON.stringify(payload)
          })
        }
        modalOpen.value = false
        fetchProfiles()
      } catch (err) {
        alert('Не удалось сохранить профиль: ' + err.message)
      } finally {
        saving.value = false
      }
    }

    const deleteProfile = async (id) => {
      if (!confirm('Вы действительно хотите удалить этот профиль? Все совпадения будут утеряны.')) return
      try {
        await store.fetch(`/api/profiles/${id}`, { method: 'DELETE' })
        fetchProfiles()
      } catch (err) {
        alert('Не удалось удалить профиль: ' + err.message)
      }
    }

    const toggleProfileStatus = async (profile) => {
      try {
        await store.fetch(`/api/profiles/${profile.id}`, {
          method: 'PUT',
          body: JSON.stringify({ is_active: !profile.is_active })
        })
        fetchProfiles()
      } catch (err) {
        alert('Не удалось изменить статус профиля: ' + err.message)
      }
    }

    const toggleChannelsExpander = async (profileId) => {
      if (expandedProfileChannels.value === profileId) {
        expandedProfileChannels.value = null
        return
      }
      expandedProfileChannels.value = profileId
      loadingChannels.value = true
      
      // Default blank config
      channelsConfig.value = {
        telegram: { is_active: false, chat_id: '' },
        viber: { is_active: false, chat_id: '' }
      }

      try {
        const channels = await store.fetch(`/api/profiles/${profileId}/channels`)
        channels.forEach(ch => {
          if (ch.type === 'telegram' || ch.type === 'viber') {
            channelsConfig.value[ch.type] = {
              is_active: ch.is_active,
              chat_id: ch.config.chat_id || ''
            }
          }
        })
      } catch (err) {
        console.error('Failed to load channels:', err)
      } finally {
        loadingChannels.value = false
      }
    }

    const saveChannels = async (profileId) => {
      try {
        // Save Telegram channel
        await store.fetch(`/api/profiles/${profileId}/channels`, {
          method: 'POST',
          body: JSON.stringify({
            type: 'telegram',
            name: 'Telegram Бот',
            is_active: channelsConfig.value.telegram.is_active,
            config: { chat_id: channelsConfig.value.telegram.chat_id }
          })
        })

        // Save Viber channel
        await store.fetch(`/api/profiles/${profileId}/channels`, {
          method: 'POST',
          body: JSON.stringify({
            type: 'viber',
            name: 'Viber Паблик',
            is_active: channelsConfig.value.viber.is_active,
            config: { chat_id: channelsConfig.value.viber.chat_id }
          })
        })

        alert('Настройки каналов успешно сохранены!')
      } catch (err) {
        alert('Ошибка сохранения каналов: ' + err.message)
      }
    }

    onMounted(() => {
      fetchProfiles()
      fetchPresets()
    })

    return {
      profiles,
      presets,
      modalOpen,
      editingProfileId,
      saving,
      form,
      formKeywords,
      newKeywordInput,
      formNegativeKeywords,
      newNegativeKeywordInput,
      expandedProfileChannels,
      loadingChannels,
      channelsConfig,
      getPresetName,
      parseKeywords,
      formatSchedule,
      openCreateModal,
      openEditModal,
      closeModal: () => { modalOpen.value = false },
      applyPreset,
      addFormKeyword,
      removeFormKeyword,
      addFormNegativeKeyword,
      removeFormNegativeKeyword,
      saveProfile,
      deleteProfile,
      toggleProfileStatus,
      toggleChannelsExpander,
      saveChannels,
      availableRegions,
      getRegionName
    }
  }
}
</script>

<style scoped>
.profiles-view {
  animation: fadeIn 0.4s ease-out;
}
.empty-state {
  text-align: center;
  padding: 4rem 2rem;
  margin-top: 2rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1rem;
}
.empty-icon {
  font-size: 3.5rem;
}
.profiles-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 1.5rem;
  margin-top: 1.5rem;
}
.profile-card {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  border: 1px solid var(--border-card);
}
.profile-card.inactive {
  opacity: 0.65;
  border-color: transparent;
}
.profile-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
}
.profile-meta {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.preset-badge {
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  padding: 0.2rem 0.5rem;
  border-radius: var(--radius-sm);
  background: rgba(255, 255, 255, 0.05);
}
.preset-badge.hvac { color: #f59e0b; background: rgba(245, 158, 11, 0.1); }
.preset-badge.it_services { color: #3b82f6; background: rgba(59, 130, 246, 0.1); }
.preset-badge.cleaning_services { color: #10b981; background: rgba(16, 185, 129, 0.1); }
.preset-badge.construction_works { color: #8b5cf6; background: rgba(139, 92, 246, 0.1); }

.status-toggle-wrapper {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.status-text {
  font-size: 0.75rem;
  color: var(--text-muted);
}
.profile-actions {
  display: flex;
  gap: 0.5rem;
}
.action-btn {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border-card);
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.9rem;
  transition: all 0.2s;
}
.action-btn:hover {
  background: rgba(255, 255, 255, 0.08);
}
.action-btn.delete:hover {
  border-color: var(--error);
  color: var(--error);
  background: var(--error-bg);
}

.profile-name {
  font-family: var(--font-display);
  font-size: 1.2rem;
  font-weight: 700;
  margin-top: 0.25rem;
}
.profile-desc {
  font-size: 0.85rem;
  color: var(--text-muted);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  height: 2.5rem;
  line-height: 1.4;
}

.keywords-summary {
  background: rgba(0, 0, 0, 0.2);
  padding: 0.75rem;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-card);
}
.keyword-section {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.section-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-muted);
}
.tags-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  max-height: 60px;
  overflow-y: auto;
}
.tag-badge {
  font-size: 0.75rem;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
}
.tag-badge.kw {
  background: rgba(59, 130, 246, 0.15);
  color: #93c5fd;
  border: 1px solid rgba(59, 130, 246, 0.2);
}
.tag-badge.neg-kw {
  background: rgba(244, 63, 94, 0.15);
  color: #fda4af;
  border: 1px solid rgba(244, 63, 94, 0.2);
}
.no-tags {
  font-size: 0.75rem;
  color: var(--text-muted);
  font-style: italic;
}

.profile-footer-stats {
  display: flex;
  justify-content: space-between;
  font-size: 0.8rem;
  border-top: 1px solid var(--border-card);
  padding-top: 0.75rem;
}
.stat-item {
  display: flex;
  gap: 0.4rem;
}
.stat-item .label { color: var(--text-muted); }
.stat-item .value { font-weight: 600; }

/* Switch Toggle Styling */
.switch {
  position: relative;
  display: inline-block;
  width: 36px;
  height: 20px;
}
.switch input { opacity: 0; width: 0; height: 0; }
.slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: #334155;
  transition: .2s;
}
.slider:before {
  position: absolute;
  content: "";
  height: 14px;
  width: 14px;
  left: 3px;
  bottom: 3px;
  background-color: white;
  transition: .2s;
}
input:checked + .slider { background-color: var(--primary); }
input:focus + .slider { box-shadow: 0 0 1px var(--primary); }
input:checked + .slider:before { transform: translateX(16px); }
.slider.round { border-radius: 34px; }
.slider.round:before { border-radius: 50%; }

/* Small Switch */
.switch-sm {
  width: 28px;
  height: 16px;
}
.switch-sm .slider:before {
  height: 10px;
  width: 10px;
  left: 3px;
  bottom: 3px;
}
input:checked + .switch-sm + .toggle-label {
  color: var(--success);
}
input:checked + .slider:before { transform: translateX(12px); }

/* Channels Accordion */
.channels-accordion {
  border-top: 1px solid var(--border-card);
  padding-top: 0.5rem;
  margin-top: 0.5rem;
}
.btn-channels-toggle {
  background: transparent;
  border: none;
  width: 100%;
  text-align: left;
  color: var(--text-muted);
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.25rem 0;
}
.btn-channels-toggle:hover {
  color: var(--text-main);
}
.btn-channels-toggle .arrow {
  font-size: 0.65rem;
  transition: transform 0.2s;
}
.btn-channels-toggle .arrow.expanded {
  transform: rotate(180deg);
}

.channels-panel {
  padding: 0.75rem 0 0 0;
  border-top: 1px dashed var(--border-card);
  margin-top: 0.5rem;
}
.channels-list {
  display: flex;
  flex-direction: column;
}
.channel-item {
  background: rgba(255, 255, 255, 0.015);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-sm);
  padding: 0.75rem;
}
.channel-info {
  display: flex;
  gap: 0.75rem;
  align-items: center;
  margin-bottom: 0.5rem;
}
.channel-icon {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
}
.channel-icon.telegram { background: rgba(59, 130, 246, 0.15); color: #3b82f6; }
.channel-icon.viber { background: rgba(139, 92, 246, 0.15); color: #8b5cf6; }

.channel-desc {
  font-size: 0.75rem;
  color: var(--text-muted);
}
.channel-config-form {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  margin-top: 0.5rem;
}
.channel-toggle-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.toggle-label {
  font-size: 0.75rem;
  color: var(--text-muted);
}
.form-input-sm {
  padding: 0.35rem 0.5rem;
  font-size: 0.8rem;
  width: 170px;
}

/* Visual tags input box */
.tags-input-container {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-md);
  padding: 0.5rem;
  min-height: 44px;
}
.tags-input-container:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-glow);
  background: rgba(15, 23, 42, 0.9);
}
.tag-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  background: rgba(59, 130, 246, 0.15);
  color: #93c5fd;
  border: 1px solid rgba(59, 130, 246, 0.25);
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.8rem;
  font-weight: 500;
}
.tag-chip.negative {
  background: rgba(244, 63, 94, 0.15);
  color: #fda4af;
  border: 1px solid rgba(244, 63, 94, 0.25);
}
.remove-tag {
  cursor: pointer;
  font-size: 1rem;
  line-height: 1;
}
.remove-tag:hover {
  color: white;
}
.tag-field-input {
  border: none;
  background: transparent;
  outline: none;
  color: white;
  font-family: var(--font-main);
  font-size: 0.9rem;
  flex-grow: 1;
  min-width: 100px;
  padding: 0.2rem 0;
}

/* Modals */
.form-row-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}
.range-slider-wrapper {
  padding: 0.5rem 0;
}
.range-slider {
  width: 100%;
  background: #1e293b;
  accent-color: var(--primary);
  height: 6px;
  border-radius: 3px;
  outline: none;
}
.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  border-top: 1px solid var(--border-card);
  padding-top: 1.25rem;
  margin-top: 1.25rem;
}
.mt-2 { margin-top: 0.5rem; }
.mt-3 { margin-top: 0.75rem; }

.tag-badge.region-tag {
  background: rgba(139, 92, 246, 0.15);
  color: #c084fc;
  border: 1px solid rgba(139, 92, 246, 0.25);
}

.regions-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 0.75rem;
  background: rgba(15, 23, 42, 0.4);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-md);
  padding: 0.75rem;
  margin-top: 0.5rem;
}

.checkbox-container {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  font-size: 0.85rem;
  color: var(--text-muted);
  user-select: none;
  transition: color 0.2s;
}

.checkbox-container:hover {
  color: var(--text-main);
}

.checkbox-container input {
  cursor: pointer;
  accent-color: var(--primary);
}
</style>
