# Git & Repository Workflow Guidelines

This document outlines the standard Git and development workflow for the **BelZakupki** repository.

## 1. Branching Strategy

All development work should be done in dedicated branches branched off from the latest `main` or active sprint branch.

- **Branch Naming Conventions**:
  - `feature/name-of-feature` — for new features (e.g., `feature/excel-attachment-extractor`).
  - `bugfix/name-of-bug` — for fixing issues.
  - `refactor/what-changed` — for code restructuring without changing behavior.
  - `codex/name-of-sprint-or-task` — for sprint-specific work (e.g., `codex/show-ingested-data`).
  - `docs/what-changed` — for updates to documentation.

## 2. Commit Message Standards

We follow the **Conventional Commits** specification. Commits should be structured as follows:

```
<type>(<scope>): <short description>
```

- **Allowed Types**:
  - `feat` — A new feature.
  - `fix` — A bug fix.
  - `docs` — Documentation changes.
  - `style` — Formatting, missing semi-colons, etc. (no production code changes).
  - `refactor` — A code change that neither fixes a bug nor adds a feature.
  - `test` — Adding missing tests or correcting existing tests.
  - `chore` — Updating build tasks, package manager configs, etc.

*Example*: `feat(worker): implement pymorphy3 morphological scoring fallback`

## 3. Database Migrations with Alembic

When you modify any SQLAlchemy models in `packages/db/belzakupki_db/models.py`:

1. **Generate Migration**:
   ```bash
   .venv/bin/alembic revision --autogenerate -m "description_of_change"
   ```
2. **Review the Migration**: Inspect the generated file under `alembic/versions/` to verify it matches your intentions.
3. **Merge Multiple Heads** (if conflicts occur):
   If another branch has generated a migration, merge the heads using:
   ```bash
   .venv/bin/alembic merge -m "merge heads" <rev_id_1> <rev_id_2>
   ```
4. **Apply Migration locally**:
   ```bash
   .venv/bin/alembic upgrade head
   ```

## 4. Verification Checklists

Before committing and pushing changes:

1. **Run Unit Tests**: Ensure all tests pass:
   ```bash
   .venv/bin/python -m pytest
   ```
2. **Environment File**: If you added new variables, remember to document them in `.env.example`.
