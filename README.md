# belzakupki
Сервис мониторинга закупок Беларуси: сбор тендеров, фильтрация по нишам, скоринг релевантности и уведомления в Telegram/email.

## Local backend

```bash
python -m venv .venv
.venv/bin/python -m pip install -e .
export PYTHONPATH=packages/db:apps/worker/src
docker compose up -d db redis
.venv/bin/alembic upgrade head
.venv/bin/belzakupki-seed
.venv/bin/belzakupki-ingest-goszakupki --limit 20
```

The parser warms up a session on `goszakupki.by` before requesting posted
tenders. If your local Python certificate store rejects the site certificate,
set `GOSZAKUPKI_VERIFY_SSL=false` for local development.
