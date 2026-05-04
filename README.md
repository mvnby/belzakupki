# belzakupki
Сервис мониторинга закупок Беларуси: сбор тендеров, фильтрация по нишам, скоринг релевантности и уведомления в Telegram/email.

## Local backend with Docker

```bash
docker compose build
docker compose up -d db redis
docker compose run --rm api alembic upgrade head
docker compose run --rm api belzakupki-seed
docker compose up api worker
```

Run the first ingest manually:

```bash
docker compose run --rm api belzakupki-ingest-goszakupki --limit 20
```

The API is available at <http://localhost:8000/healthz> by default. Set
`API_PORT` to expose it on a different host port. If local Postgres or Redis
ports are already busy, set `POSTGRES_HOST_PORT` or `REDIS_HOST_PORT`.

## Local backend without Docker

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
