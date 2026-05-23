// --- Application State ---
const state = {
    activeTab: 'overview',
    stats: {},
    tasks: { ingest: 'idle', notify: 'idle' },
    tenders: [],
    tendersPage: 1,
    tendersPageSize: 15,
    tendersFilterMatched: false,
    tendersSearch: '',
    profiles: [],
    editingProfile: null, // Holds profile object when editing, or null for new profile
    editingKeywords: [],
    editingNegativeKeywords: [],
    pollingInterval: null
};

// --- DOM Elements ---
const views = {
    overview: document.getElementById('view-overview'),
    tenders: document.getElementById('view-tenders'),
    profiles: document.getElementById('view-profiles'),
    actions: document.getElementById('view-actions')
};

const menuItems = document.querySelectorAll('.menu-item');
const pageTitle = document.getElementById('page-title');
const pageSubtitle = document.getElementById('page-subtitle');
const systemConsole = document.getElementById('system-console');

// --- Helper Functions ---
function formatPrice(value) {
    if (!value) return 'Не указана';
    return value;
}

function formatDate(dateStr) {
    if (!dateStr) return '-';
    try {
        const date = new Date(dateStr);
        return date.toLocaleString('ru-RU', { 
            day: '2-digit', 
            month: '2-digit', 
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    } catch {
        return dateStr;
    }
}

function logToConsole(message, type = 'info') {
    const timestamp = new Date().toLocaleTimeString('ru-RU');
    const line = document.createElement('div');
    line.className = `console-line ${type}`;
    line.textContent = `[${timestamp}] ${message}`;
    systemConsole.appendChild(line);
    systemConsole.scrollTop = systemConsole.scrollHeight;
}

// --- Navigation / Routing ---
function switchTab(tabId) {
    state.activeTab = tabId;
    
    // Update active class on menu items
    menuItems.forEach(item => {
        if (item.getAttribute('data-tab') === tabId) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });

    // Update active class on views
    Object.keys(views).forEach(key => {
        if (key === tabId) {
            views[key].classList.add('active');
        } else {
            views[key].classList.remove('active');
        }
    });

    // Update Headers
    switch (tabId) {
        case 'overview':
            pageTitle.textContent = 'Обзор системы';
            pageSubtitle.textContent = 'Текущий статус мониторинга и статистика';
            loadOverviewData();
            break;
        case 'tenders':
            pageTitle.textContent = 'База тендеров';
            pageSubtitle.textContent = 'Список импортированных тендеров и релевантных совпадений';
            loadTendersData();
            break;
        case 'profiles':
            pageTitle.textContent = 'Профили поиска';
            pageSubtitle.textContent = 'Настройка фильтров и каналов уведомлений Telegram';
            loadProfilesData();
            break;
        case 'actions':
            pageTitle.textContent = 'Панель действий';
            pageSubtitle.textContent = 'Ручной запуск импорта и рассылки уведомлений';
            loadActionsData();
            break;
    }
}

// --- API Calls ---

async function fetchStats() {
    try {
        const res = await fetch('/api/stats');
        const data = await res.json();
        state.stats = data.stats;
        state.tasks = data.tasks;
        updateTaskStatusUI();
        return data;
    } catch (err) {
        console.error('Error fetching stats:', err);
    }
}

function updateTaskStatusUI() {
    const statusIngest = document.getElementById('status-ingest');
    const statusNotify = document.getElementById('status-notify');
    const btnRunIngest = document.getElementById('btn-run-ingest');
    const btnRunNotify = document.getElementById('btn-run-notify');
    const taskIndicator = document.getElementById('task-indicator');

    // Ingest status
    if (state.tasks.ingest === 'running') {
        statusIngest.textContent = 'Выполняется...';
        statusIngest.className = 'task-status-badge badge-running';
        if (btnRunIngest) btnRunIngest.disabled = true;
    } else {
        statusIngest.textContent = 'Готов';
        statusIngest.className = 'task-status-badge badge-idle';
        if (btnRunIngest) btnRunIngest.disabled = false;
    }

    // Notify status
    if (state.tasks.notify === 'running') {
        statusNotify.textContent = 'Выполняется...';
        statusNotify.className = 'task-status-badge badge-running';
        if (btnRunNotify) btnRunNotify.disabled = true;
    } else {
        statusNotify.textContent = 'Готов';
        statusNotify.className = 'task-status-badge badge-idle';
        if (btnRunNotify) btnRunNotify.disabled = false;
    }

    // Top indicator
    if (state.tasks.ingest === 'running' || state.tasks.notify === 'running') {
        taskIndicator.innerHTML = '<span class="pulse-dot green"></span><span class="indicator-text">Выполняется фоновый процесс...</span>';
    } else {
        taskIndicator.innerHTML = '<span class="pulse-dot green"></span><span class="indicator-text">Система активна</span>';
    }
}

// --- View: Overview Load ---
async function loadOverviewData() {
    const data = await fetchStats();
    if (!data) return;

    document.getElementById('stat-total-tenders').textContent = data.stats.total_tenders;
    document.getElementById('stat-total-matches').textContent = data.stats.total_matches;
    document.getElementById('stat-sent-notifications').textContent = data.stats.sent_notifications;
    document.getElementById('stat-errors-expired').textContent = `${data.stats.error_notifications} / ${data.stats.expired_matches}`;

    // Load recent matches (limit 5)
    try {
        const matchesRes = await fetch('/matches?limit=5');
        const matchesData = await matchesRes.json();
        
        const tbody = document.getElementById('recent-matches-body');
        tbody.innerHTML = '';

        if (!matchesData.items || matchesData.items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Новых совпадений пока не найдено. Запустите импорт.</td></tr>';
            return;
        }

        matchesData.items.forEach(match => {
            const tr = document.createElement('tr');
            const sourceName = match.tender.source_name || match.tender.source || '-';
            const sourceCode = match.tender.source || 'unknown';
            tr.innerHTML = `
                <td>#${match.id}</td>
                <td><a href="#" class="btn-link text-left" onclick="viewTenderDetails(${match.tender.id}); return false;">${match.tender.title}</a></td>
                <td><span class="source-tag source-${sourceCode}">${sourceName}</span></td>
                <td>${match.profile.name}</td>
                <td><strong>${match.score}</strong></td>
                <td><span class="badge badge-${match.status}">${match.status === 'new' ? 'новый' : match.status === 'processed' ? 'отправлен' : 'просрочен'}</span></td>
                <td>${formatDate(match.created_at)}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error('Error loading recent matches:', err);
    }
}

// --- View: Tenders Load ---
async function loadTendersData() {
    const tbody = document.getElementById('tenders-table-body');
    tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">Загрузка списка тендеров...</td></tr>';

    const offset = (state.tendersPage - 1) * state.tendersPageSize;
    let url = `/tenders?limit=${state.tendersPageSize}&offset=${offset}&matched_only=${state.tendersFilterMatched}`;
    if (state.tendersSearch.trim()) {
        url += `&q=${encodeURIComponent(state.tendersSearch)}`;
    }

    try {
        const res = await fetch(url);
        const data = await res.json();
        state.tenders = data.items;

        tbody.innerHTML = '';
        if (!data.items || data.items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">Тендеры не найдены по заданным критериям</td></tr>';
            document.getElementById('btn-next-page').disabled = true;
            return;
        }

        data.items.forEach(tender => {
            const tr = document.createElement('tr');
            
            // Format status badge
            let statusText = 'активен';
            let badgeClass = 'badge-posted';
            if (tender.status === 'expired') {
                statusText = 'просрочен';
                badgeClass = 'badge-expired';
            }

            const sourceName = tender.source_name || tender.source || '-';
            const sourceCode = tender.source || 'unknown';

            tr.innerHTML = `
                <td>#${tender.id}</td>
                <td><div class="tender-title-column">${tender.title}</div></td>
                <td><div class="tender-customer-column">${tender.customer_name || '-'}</div></td>
                <td><span class="source-tag source-${sourceCode}">${sourceName}</span></td>
                <td>${formatDate(tender.deadline_at)}</td>
                <td>${formatPrice(tender.estimated_value)}</td>
                <td><span class="badge ${badgeClass}">${statusText}</span></td>
                <td>
                    <div style="display:flex; gap: 8px;">
                        <button class="btn btn-secondary" style="padding: 6px 12px; font-size:12px;" onclick="viewTenderDetails(${tender.id})">JSON</button>
                        <a href="${tender.url}" target="_blank" class="btn btn-secondary" style="padding: 6px 12px; font-size:12px; text-decoration:none;"><i class="fa-solid fa-arrow-up-right-from-square"></i></a>
                    </div>
                </td>
            `;
            tbody.appendChild(tr);
        });

        // Pagination buttons state
        document.getElementById('btn-prev-page').disabled = state.tendersPage <= 1;
        document.getElementById('btn-next-page').disabled = data.items.length < state.tendersPageSize;
        document.getElementById('page-indicator').textContent = `Страница ${state.tendersPage}`;

    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center text-danger">Ошибка загрузки: ${err.message}</td></tr>`;
        console.error(err);
    }
}

// --- View: Profiles Load ---
async function loadProfilesData() {
    const container = document.getElementById('profiles-list-container');
    container.innerHTML = '<div class="text-center text-muted" style="grid-column: 1/-1;">Загрузка профилей поиска...</div>';

    try {
        const res = await fetch('/api/profiles');
        const profiles = await res.json();
        state.profiles = profiles;

        container.innerHTML = '';
        if (profiles.length === 0) {
            container.innerHTML = '<div class="text-center text-muted" style="grid-column: 1/-1;">Нет созданных профилей поиска. Создайте новый.</div>';
            return;
        }

        for (const profile of profiles) {
            // Get Telegram channel info for this profile
            const channelRes = await fetch(`/api/profiles/${profile.id}/channels`);
            const channels = await channelRes.json();
            const telegramChannel = channels.find(c => c.type === 'telegram');

            const card = document.createElement('div');
            card.className = 'profile-card';
            
            // Format keywords preview
            const keywordsHTML = profile.keywords.map(kw => `<span class="tag-badge">${kw}</span>`).join('') || '<span class="text-muted">Нет</span>';
            const negKeywordsHTML = profile.negative_keywords.map(kw => `<span class="tag-badge neg">${kw}</span>`).join('') || '<span class="text-muted">Нет</span>';
            
            // Channel indicator
            let channelIndicatorHTML = '<span class="text-muted" style="font-size:13px;"><i class="fa-solid fa-bell-slash"></i> Telegram выключен</span>';
            if (telegramChannel && telegramChannel.is_active) {
                channelIndicatorHTML = `<span class="profile-channel-badge"><i class="fa-brands fa-telegram"></i> ID: ${telegramChannel.config.chat_id || 'Не задан'}</span>`;
            }

            card.innerHTML = `
                <div class="profile-title-bar">
                    <h3>${profile.name}</h3>
                    <div class="status-badge-container">
                        <span class="active-dot ${profile.is_active ? 'active' : 'inactive'}"></span>
                        <span class="text-muted">${profile.is_active ? 'Активен' : 'Отключен'}</span>
                    </div>
                </div>
                <p class="profile-desc">${profile.description || 'Без описания'}</p>
                
                <div>
                    <h4 class="profile-meta-title">Ключевые слова</h4>
                    <div class="profile-keywords-preview">${keywordsHTML}</div>
                </div>

                <div>
                    <h4 class="profile-meta-title">Исключающие слова</h4>
                    <div class="profile-keywords-preview">${negKeywordsHTML}</div>
                </div>

                <div>
                    <h4 class="profile-meta-title">Канал уведомлений</h4>
                    <div>${channelIndicatorHTML}</div>
                </div>

                <div class="profile-card-footer">
                    <button class="btn btn-secondary" style="padding:6px 12px;" onclick="openEditProfileModal(${profile.id})"><i class="fa-solid fa-pen"></i> Изменить</button>
                    <button class="btn btn-secondary" style="padding:6px 12px; color:var(--color-danger); border-color:rgba(239, 68, 68, 0.2);" onclick="deleteProfile(${profile.id})"><i class="fa-solid fa-trash"></i> Удалить</button>
                </div>
            `;
            container.appendChild(card);
        }

    } catch (err) {
        container.innerHTML = `<div class="text-center text-danger" style="grid-column: 1/-1;">Ошибка загрузки: ${err.message}</div>`;
        console.error(err);
    }
}

// --- View: Actions Load ---
function loadActionsData() {
    fetchStats();
    // Поллинг фоновых процессов
    if (!state.pollingInterval) {
        state.pollingInterval = setInterval(fetchStats, 3000);
    }
}

// --- Action Triggers ---

async function runIngest() {
    logToConsole('Инициализация запуска импорта тендеров...', 'info');
    try {
        const res = await fetch('/api/actions/ingest', { method: 'POST' });
        const data = await res.json();
        
        if (data.status === 'started') {
            logToConsole('Фоновая задача импорта и скоринга успешно запущена!', 'success');
        } else if (data.status === 'already_running') {
            logToConsole('Задача импорта уже выполняется в фоне.', 'warning');
        }
        fetchStats();
    } catch (err) {
        logToConsole(`Ошибка при запуске импорта: ${err.message}`, 'error');
    }
}

async function runNotify() {
    logToConsole('Инициализация отправки Telegram уведомлений...', 'info');
    try {
        const res = await fetch('/api/actions/notify', { method: 'POST' });
        const data = await res.json();
        
        if (data.status === 'started') {
            logToConsole('Фоновая рассылка Telegram уведомлений запущена!', 'success');
        } else if (data.status === 'already_running') {
            logToConsole('Задача рассылки уже выполняется в фоне.', 'warning');
        }
        fetchStats();
    } catch (err) {
        logToConsole(`Ошибка при запуске рассылки: ${err.message}`, 'error');
    }
}

// --- Tender Details View (Modal) ---
async function viewTenderDetails(tenderId) {
    try {
        const res = await fetch(`/tenders/${tenderId}`);
        if (!res.ok) throw new Error('Не удалось получить информацию о тендере');
        const tender = await res.json();

        document.getElementById('modal-tender-title').textContent = tender.title;
        document.getElementById('modal-tender-customer').textContent = tender.customer_name || 'Не указан';
        document.getElementById('modal-tender-source').textContent = tender.source_name || tender.source || 'Не указан';
        document.getElementById('modal-tender-deadline').textContent = formatDate(tender.deadline_at);
        document.getElementById('modal-tender-value').textContent = formatPrice(tender.estimated_value);
        
        const link = document.getElementById('modal-tender-link');
        link.href = tender.url;

        // Render formatted JSON
        document.getElementById('modal-tender-json').textContent = JSON.stringify(tender, null, 2);

        // Open Modal
        document.getElementById('tender-modal').style.display = 'flex';
    } catch (err) {
        alert(`Ошибка: ${err.message}`);
    }
}

// --- Profile Edit/Create (Modal) ---

function openCreateProfileModal() {
    state.editingProfile = null;
    state.editingKeywords = [];
    state.editingNegativeKeywords = [];
    
    document.getElementById('modal-profile-title').textContent = 'Создать новый профиль поиска';
    document.getElementById('form-profile-id').value = '';
    document.getElementById('form-profile-name').value = '';
    document.getElementById('form-profile-description').value = '';
    document.getElementById('form-profile-active').checked = true;
    document.getElementById('form-channel-active').checked = true;
    document.getElementById('form-telegram-chat').value = '';
    
    renderTags('keywords');
    renderTags('negative');
    
    document.getElementById('profile-modal').style.display = 'flex';
}

async function openEditProfileModal(profileId) {
    const profile = state.profiles.find(p => p.id === profileId);
    if (!profile) return;

    state.editingProfile = profile;
    state.editingKeywords = [...profile.keywords];
    state.editingNegativeKeywords = [...profile.negative_keywords];

    document.getElementById('modal-profile-title').textContent = 'Редактировать профиль поиска';
    document.getElementById('form-profile-id').value = profile.id;
    document.getElementById('form-profile-name').value = profile.name;
    document.getElementById('form-profile-description').value = profile.description || '';
    document.getElementById('form-profile-active').checked = profile.is_active;

    // Load channel info
    try {
        const channelRes = await fetch(`/api/profiles/${profile.id}/channels`);
        const channels = await channelRes.json();
        const telegramChannel = channels.find(c => c.type === 'telegram');

        if (telegramChannel) {
            document.getElementById('form-channel-active').checked = telegramChannel.is_active;
            document.getElementById('form-telegram-chat').value = telegramChannel.config.chat_id || '';
        } else {
            document.getElementById('form-channel-active').checked = false;
            document.getElementById('form-telegram-chat').value = '';
        }
    } catch (err) {
        console.error('Error fetching channels for editing:', err);
    }

    renderTags('keywords');
    renderTags('negative');

    document.getElementById('profile-modal').style.display = 'flex';
}

function renderTags(type) {
    const container = document.getElementById(type === 'keywords' ? 'keywords-tags-list' : 'negative-tags-list');
    const tagsList = type === 'keywords' ? state.editingKeywords : state.editingNegativeKeywords;
    
    container.innerHTML = '';
    tagsList.forEach((tag, idx) => {
        const item = document.createElement('div');
        item.className = `tag-item ${type === 'negative' ? 'neg' : ''}`;
        item.innerHTML = `
            <span>${tag}</span>
            <button type="button" class="tag-remove-btn" onclick="removeTag('${type}', ${idx})">&times;</button>
        `;
        container.appendChild(item);
    });
}

function addTag(type, value) {
    const val = value.trim();
    if (!val) return;
    
    const tagsList = type === 'keywords' ? state.editingKeywords : state.editingNegativeKeywords;
    if (!tagsList.includes(val)) {
        tagsList.push(val);
        renderTags(type);
    }
}

function removeTag(type, index) {
    const tagsList = type === 'keywords' ? state.editingKeywords : state.editingNegativeKeywords;
    tagsList.splice(index, 1);
    renderTags(type);
}

async function saveProfile() {
    const name = document.getElementById('form-profile-name').value.trim();
    const description = document.getElementById('form-profile-description').value.trim();
    const is_active = document.getElementById('form-profile-active').checked;
    
    if (!name) {
        alert('Пожалуйста, заполните название профиля');
        return;
    }

    const payload = {
        name,
        description: description || null,
        keywords: state.editingKeywords,
        negative_keywords: state.editingNegativeKeywords,
        is_active
    };

    const isNew = !state.editingProfile;
    const url = isNew ? '/api/profiles' : `/api/profiles/${state.editingProfile.id}`;
    const method = isNew ? 'POST' : 'PUT';

    try {
        const profileRes = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (!profileRes.ok) throw new Error('Не удалось сохранить профиль');
        const savedProfile = await profileRes.json();

        // Save channel config
        const channelActive = document.getElementById('form-channel-active').checked;
        const chat_id = document.getElementById('form-telegram-chat').value.trim();

        if (chat_id || channelActive) {
            const channelPayload = {
                type: 'telegram',
                name: 'Telegram Default',
                config: { chat_id: chat_id || 'your-chat-id' },
                is_active: channelActive
            };
            
            const channelRes = await fetch(`/api/profiles/${savedProfile.id}/channels`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(channelPayload)
            });

            if (!channelRes.ok) throw new Error('Профиль сохранен, но не удалось сохранить настройки Telegram');
        }

        // Close modal and reload
        document.getElementById('profile-modal').style.display = 'none';
        loadProfilesData();

    } catch (err) {
        alert(`Ошибка при сохранении: ${err.message}`);
    }
}

async function deleteProfile(profileId) {
    if (!confirm('Вы уверены, что хотите удалить этот поисковый профиль? Все связанные совпадения также будут удалены.')) {
        return;
    }

    try {
        const res = await fetch(`/api/profiles/${profileId}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Не удалось удалить профиль');
        loadProfilesData();
    } catch (err) {
        alert(`Ошибка при удалении: ${err.message}`);
    }
}

// --- Event Listeners Setup ---

function setupEventListeners() {
    // Menu navigation
    menuItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const tabId = item.getAttribute('data-tab');
            switchTab(tabId);
        });
    });

    // Ingest & Notify action buttons
    const btnRunIngest = document.getElementById('btn-run-ingest');
    if (btnRunIngest) btnRunIngest.addEventListener('click', runIngest);
    
    const btnRunNotify = document.getElementById('btn-run-notify');
    if (btnRunNotify) btnRunNotify.addEventListener('click', runNotify);

    const btnClearConsole = document.getElementById('btn-clear-console');
    if (btnClearConsole) {
        btnClearConsole.addEventListener('click', () => {
            systemConsole.innerHTML = '<div class="console-line system">[System] Консоль очищена.</div>';
        });
    }

    // Modal Close buttons
    document.getElementById('modal-tender-close').addEventListener('click', () => {
        document.getElementById('tender-modal').style.display = 'none';
    });
    document.getElementById('btn-close-tender-view').addEventListener('click', () => {
        document.getElementById('tender-modal').style.display = 'none';
    });
    
    document.getElementById('modal-profile-close').addEventListener('click', () => {
        document.getElementById('profile-modal').style.display = 'none';
    });
    document.getElementById('btn-cancel-profile').addEventListener('click', () => {
        document.getElementById('profile-modal').style.display = 'none';
    });

    // Create Profile Button
    document.getElementById('btn-create-profile').addEventListener('click', openCreateProfileModal);
    document.getElementById('btn-save-profile').addEventListener('click', saveProfile);

    // Tags pill input events
    const inputKeyword = document.getElementById('input-keyword-tag');
    inputKeyword.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            addTag('keywords', inputKeyword.value);
            inputKeyword.value = '';
        }
    });

    const inputNegative = document.getElementById('input-negative-tag');
    inputNegative.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            addTag('negative', inputNegative.value);
            inputNegative.value = '';
        }
    });

    // Tenders Filtering & Pagination
    document.getElementById('filter-matched-only').addEventListener('change', (e) => {
        state.tendersFilterMatched = e.target.checked;
        state.tendersPage = 1;
        loadTendersData();
    });

    let searchTimeout = null;
    document.getElementById('tender-search').addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            state.tendersSearch = e.target.value;
            state.tendersPage = 1;
            loadTendersData();
        }, 400);
    });

    document.getElementById('btn-prev-page').addEventListener('click', () => {
        if (state.tendersPage > 1) {
            state.tendersPage--;
            loadTendersData();
        }
    });

    document.getElementById('btn-next-page').addEventListener('click', () => {
        state.tendersPage++;
        loadTendersData();
    });
}

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    
    // Check initial hash route
    const hash = window.location.hash.substring(1);
    if (['overview', 'tenders', 'profiles', 'actions'].includes(hash)) {
        switchTab(hash);
    } else {
        switchTab('overview');
    }
});
