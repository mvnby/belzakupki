# Antigravity Agent Guidelines

Welcome to the **BelZakupki** repository! This document serves as a guide for AI agents working on this codebase.

## Repository Overview

BelZakupki is a Belarus procurement monitoring service that collects tenders, filters them by niche, scores relevance, and sends notifications via Telegram/email.

- **Stack**: Python 3.14, FastAPI, SQLAlchemy, Alembic, PostgreSQL, Redis, RQ (Redis Queue), pymorphy3, tenacity.
- **Components**:
  - [apps/api](file:///Users/maksimkorotov/Documents/belzakupki/apps/api): FastAPI web server exposing REST endpoints and serving the dashboard.
  - [apps/worker](file:///Users/maksimkorotov/Documents/belzakupki/apps/worker): RQ worker processing ingest, scoring, and notification jobs, with an integrated background scheduler thread.
  - [packages/db](file:///Users/maksimkorotov/Documents/belzakupki/packages/db): SQLAlchemy models, migrations (Alembic), and session helpers.

## Agent Rules & Guidelines

1. **Follow the Git Workflow**: Refer to the repository guidelines in [git-workflow.md](file:///Users/maksimkorotov/Documents/belzakupki/docs/git-workflow.md) before making commits or branching.
   - **Branch Naming Conventions**:
     - `codex/name-of-task` — for sprint/task-specific work (e.g., `codex/quality-robustness-scheduler`). *Note: AI agents should default to this prefix for task assignments.*
     - `feature/name-of-feature` — for new infrastructure features.
     - `bugfix/name-of-bug` — for fixing issues.
     - `refactor/what-changed` — for code restructuring without changing behavior.
     - `docs/what-changed` — for updates to documentation.
2. **Preserve Integrity**: Do not remove existing comments, docstrings, or tests unless explicitly requested.
3. **Lazy Loading**: When introducing external libraries, use lazy loading/imports if they are optional (e.g., see [morphology.py](file:///Users/maksimkorotov/Documents/belzakupki/apps/worker/src/worker/morphology.py) and [text_extractor.py](file:///Users/maksimkorotov/Documents/belzakupki/apps/worker/src/worker/analyzer/text_extractor.py) for reference).
4. **Error Handling & Rollbacks**: Ensure database sessions are safely rolled back on exceptions (refer to [session.py](file:///Users/maksimkorotov/Documents/belzakupki/packages/db/belzakupki_db/session.py)).
5. **No Placeholders**: Never write placeholder code or template items. All code must be fully functional.
6. **Run Verification**: Always run `.venv/bin/python -m pytest` to check that the test suite passes before finalizing work.
