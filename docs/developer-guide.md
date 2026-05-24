# BelZakupki — Руководство Разработчика (Developer Onboarding Guide)

Добро пожаловать в команду разработки BelZakupki! Этот документ составлен специально для того, чтобы помочь вам быстро разобраться в архитектуре, кодовой базе, процессах локального запуска и правилах разработки проекта.

---

## 1. Общая архитектура проекта

Проект построен как монорепозиторий, разделенный на независимые компоненты (приложения) и общие библиотеки:

```mermaid
graph TD
    API[apps/api: FastAPI Server] --> DB_PKG[packages/db: SQLAlchemy models & helpers]
    Worker[apps/worker: RQ Worker & Daemon Scheduler] --> DB_PKG
    DB_PKG --> PG[(PostgreSQL)]
    Worker --> Redis[(Redis Queue)]
    API --> Redis
```

### Основные компоненты:
1. **`packages/db`**: Общий пакет, отвечающий за работу с базой данных.
   - Содержит декларативные модели SQLAlchemy (`models.py`).
   - Содержит миграции Alembic (директория `alembic` в корне).
   - Предоставляет хелперы для создания сессий (`session.py`) и готовые функции чтения/сериализации (`read.py`).
2. **`apps/api`**: FastAPI веб-сервер.
   - Предоставляет REST API для веб-панели управления (dashboard).
   - Позволяет настраивать поисковые профили (Search Profiles) и каналы уведомлений (Notification Channels).
   - Отдает статические файлы панели управления (`static/`).
3. **`apps/worker`**: Фоновый обработчик задач на базе RQ (Redis Queue) со встроенным планировщиком.
   - Выполняет парсинг госзакупок, скоринг, ИИ-анализ и отправку уведомлений.
   - Запускает фоновые потоки планировщика (scheduler) и слушателя Telegram-бота для обработки кнопок обратной связи.

---

## 2. Жизненный цикл обработки тендеров (Data Pipeline)

Весь процесс обработки тендера можно разделить на следующие этапы:

```mermaid
sequenceDiagram
    participant S as Источник (goszakupki.by/icetrade.by)
    participant W as Worker (ingest.py)
    participant DB as База данных (PostgreSQL)
    participant AI as ИИ (DeepSeek API)
    participant TG as Telegram Bot

    W->>S: 1. Запрос списка новых тендеров
    S-->>W: Список тендеров (HTML)
    W->>W: 2. Парсинг HTML, извлечение метаданных
    W->>DB: 3. Сохранение/обновление (upsert_tender)
    W->>DB: 4. Лемматизация (pymorphy3) и ключевой скоринг
    Note over W,DB: Если score >= min_score, создается TenderMatch со статусом 'new'
    W->>AI: 5. Экспресс-проверка метаданных ИИ (Stage 1)
    alt Не релевантно
        AI-->>W: {"relevant": false, "explanation": "..."}
        W->>DB: Установка статуса REJECTED_BY_AI
    else Релевантно
        AI-->>W: {"relevant": true}
        W->>S: 6. Скачивание прикрепленных документов (.pdf, .docx, .xlsx)
        S-->>W: Файлы документов
        W->>W: 7. Извлечение текста (pypdf, python-docx, openpyxl)
        W->>AI: 8. Глубокий анализ ТЗ ИИ (Stage 2)
        AI-->>W: Детальный JSON (объем, требования, бюджет, советы)
        W->>DB: Сохранение анализа в TenderMatch
        W->>TG: 9. Отправка карточки тендера с инлайн-кнопками
    end
```

---

## 3. Структура базы данных (Schema)

База данных работает на СУБД **PostgreSQL**.
Основные сущности и их связи:

### `TenderSource` (tender_sources)
- Хранит информацию об источниках данных (например, `goszakupki_by` или `icetrade_by`).
- Связь с `Tender` (`1:M`).

### `Tender` (tenders)
- Сам тендер, полученный из внешнего источника.
- Поля: `title` (название), `description` (описание), `customer_name` (заказчик), `url` (ссылка), `status` (`posted` и т.д.), `raw_data` (исходный JSON с разметкой), `deadline_at` (дедлайн подачи).
- Имеет составной уникальный индекс `(source_id, external_id)`.

### `SearchProfile` (search_profiles)
- Поисковый профиль, создаваемый пользователем.
- Содержит ключевые слова (`keywords`), минус-слова (`negative_keywords`), регионы, категории ОКРБ/отрасли, минимальный проходной балл (`min_score`) и интервал запуска планировщика (`schedule_interval`, например, `"1h"`, `"4h"`, `"manual"`).

### `TenderMatch` (tender_matches)
- Связующая таблица совпадений тендера с поисковым профилем.
- Содержит `score` (балл релевантности), `matched_keywords` (совпавшие ключевые слова), `reason` (причина совпадения), `status` (`new`, `processed`, `accepted`, `rejected`, `rejected_by_ai`, `expired`).
- Хранит результаты анализа ИИ: `ai_relevance` (флаг) и `ai_analysis` (детальные данные).

### `NotificationChannel` (notification_channels)
- Канал уведомлений, привязанный к профилю (`profile_id`).
- Содержит тип (`type` = `"telegram"`, в будущем `"email"`), имя и конфигурацию (`config` с `chat_id`).

### `NotificationLog` (notification_logs)
- Журнал отправленных уведомлений для связки совпадения (`match_id`) и канала (`channel_id`).

---

## 4. Локальный запуск и настройка

Локальное окружение можно запустить двумя способами: с Docker и без него.

### Файл окружения `.env`
Создайте файл `.env` на основе `.env.example`:
```ini
DATABASE_URL=postgresql+psycopg://belzakupki:belzakupki@localhost:5432/belzakupki
REDIS_URL=redis://localhost:6379/0

# Настройки для Telegram
TELEGRAM_BOT_TOKEN=your-telegram-bot-token

# Настройки ИИ (DeepSeek)
DEEPSEEK_TOKEN=your-deepseek-api-key

# Фронтенд аутентификация (опционально)
API_SECRET_KEY=your-api-secret-key
```

### Вариант А. Запуск через Docker (Рекомендуемый)
1. Соберите образы и запустите СУБД и Redis:
   ```bash
   docker compose build
   docker compose up -d db redis
   ```
2. Выполните миграции и наполните базу начальными данными:
   ```bash
   docker compose run --rm api alembic upgrade head
   docker compose run --rm api belzakupki-seed
   ```
3. Запустите API-сервер и Worker:
   ```bash
   docker compose up -d api worker
   ```

### Вариант Б. Локальный запуск без Docker
1. Создайте виртуальное окружение Python и установите зависимости в режиме редактирования:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # На macOS/Linux
   pip install -e .[dev]
   ```
2. Запустите СУБД и Redis (например, через Docker):
   ```bash
   docker compose up -d db redis
   ```
3. Установите переменные окружения и выполните миграции и сидирование базы данных:
   ```bash
   export PYTHONPATH=packages/db:apps/worker/src
   alembic upgrade head
   belzakupki-seed
   ```
4. Для запуска API-сервера:
   ```bash
   uvicorn apps.api.main:app --host 127.0.0.1 --port 8008 --reload
   ```
5. Для запуска Worker-процесса:
   ```bash
   python apps/worker/main.py
   ```

---

## 5. Веб-интерфейс панели управления (Web UI Dashboard)

После запуска API-сервера (по умолчанию на <http://localhost:8008>), панель управления доступна в браузере.

Веб-интерфейс представляет собой Single Page Application (SPA), реализованное на чистом HTML, CSS и Vanilla JS (файлы находятся в директории [apps/api/static](file:///Users/maksimkorotov/Documents/belzakupki/apps/api/static)).

### Основные возможности Web UI:
1. **Общая статистика**: Выводит сводную информацию о количестве собранных тендеров, совпадений, отправленных уведомлений и статусе фоновых задач.
2. **Управление поисковыми профилями (Profiles CRUD)**:
   - Просмотр, создание, редактирование и удаление профилей.
   - Настройка ключевых слов, минус-слов, кодов ОКРБ/отраслей, минимального проходного балла и интервала запуска.
3. **Каналы уведомлений**: Подключение каналов связи (например, Telegram-ботов с указанием ID чата) к конкретным профилям поиска.
4. **Просмотр тендеров и совпадений**:
   - Ленты импортированных тендеров и отскоренных совпадений (Matches).
   - Просмотр детальных результатов ИИ-анализа (описание, требования, бюджет, советы по подготовке КП) непосредственно из интерфейса.
5. **Ручной запуск задач**: Кнопки принудительного запуска процессов сбора тендеров (Ingest) и рассылки сообщений (Notify) прямо из веб-панели (задачи выполняются асинхронно в фоне).

---

## 6. Доступные CLI-команды

Проект предоставляет удобные скрипты, прописанные в `pyproject.toml`. Запускайте их из активированного виртуального окружения:

- **`belzakupki-seed`**: Наполнение базы данных тестовыми поисковыми профилями (например, по тематике HVAC) и тестовым источником.
- **`belzakupki-ingest-goszakupki --limit 20`**: Ручной сбор тендеров с `goszakupki.by`.
  - Флаг `--search-preset hvac-vitebsk` запускает предопределенный поиск по кондиционированию в Витебской области.
  - Флаг `--notify` запускает отправку уведомлений сразу после завершения сбора.
- **`belzakupki-ingest-icetrade --limit 20`**: Ручной сбор тендеров с `icetrade.by`.
- **`belzakupki-list-tenders --limit 20`**: Вывести список сохраненных в БД тендеров.
- **`belzakupki-list-matches --limit 20`**: Вывести список совпадений (matches) и их баллы.
- **`belzakupki-send-notifications`**: Принудительная отправка уведомлений по всем совпадениям со статусом `new`.

---

## 7. Правила разработки и рабочий процесс (Git Workflow)

Мы придерживаемся строгих стандартов разработки, описанных в [git-workflow.md](file:///Users/maksimkorotov/Documents/belzakupki/docs/git-workflow.md):

1. **Создание веток**: Всегда создавайте отдельную ветку от `main` с соответствующим префиксом (`feature/`, `bugfix/`, `refactor/`, `docs/`).
2. **Conventional Commits**: Сообщения коммитов должны следовать соглашению `<type>(<scope>): <short description>`.
   - Примеры типов: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`.
3. **Миграции базы данных**:
   - При изменении моделей в `packages/db/belzakupki_db/models.py` сгенерируйте миграцию:
     ```bash
     alembic revision --autogenerate -m "description_of_change"
     ```
   - Проверьте созданный файл миграции в `alembic/versions/` перед коммитом!
4. **Тестирование**: Перед каждым коммитом обязательно убедитесь, что все тесты проходят:
   - Запуск тестов: `.venv/bin/python -m pytest`
   - Тесты лежат в директории `tests/` и покрывают нормализацию текста и скоринг.
