# belzakupki
Сервис мониторинга закупок Беларуси: сбор тендеров, фильтрация по нишам, скоринг релевантности и уведомления в Telegram/email.

## Local backend

```bash
python -m venv .venv
.venv/bin/python -m pip install -e .
docker compose up -d db redis
.venv/bin/alembic upgrade head
.venv/bin/belzakupki-seed
.venv/bin/belzakupki-ingest-goszakupki --limit 20
```

`goszakupki.by/tenders/posted` redirects anonymous requests to login. Set
`GOSZAKUPKI_COOKIE` to an authenticated session cookie before running the
ingest command against live tenders.
