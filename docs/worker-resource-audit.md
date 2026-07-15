# Worker resource-safety audit

## Baseline

The audit started from `main` at `0c514b6`. The unmodified suite passed with
76 tests on Python 3.14.2. Production evidence supplied for the audit showed
the Python worker reaching roughly 1.35–1.37 GiB RSS, a full host swap, two
exit-137 terminations, and a Docker JSON log of roughly 3.38 GiB.

The worker process combines an RQ worker, a Telegram listener, and an embedded
profile scheduler. Before this change, the scheduler could run four profile
pipelines concurrently and could additionally overlap result checking, global
ingest, and an RQ job. Several pipelines loaded every eligible database row,
and OCR rendered every PDF page at 2x resolution.

## Guardrails implemented

- One shared scheduler runner defaults to one heavy task at a time, has a
  bounded eight-item queue, and deduplicates active task keys. Deferred work
  remains due and is retried on a later poll.
- AI analysis, local routing, result checks, and notifications use ordered,
  configurable database batches instead of loading an unbounded result set.
- Attachment processing defaults to ten files per tender. PDF text extraction
  is capped at 100 pages, OCR at 12 pages, and extracted/AI text at 120,000
  characters. PDF, pixmap, and image resources are released per page.
- Production containers have explicit memory, CPU, and PID ceilings. Defaults
  total about 2.5 GiB of hard memory limits, leaving capacity on a 4 GiB host
  for the MVN standby and the operating system. The low-priority worker is
  capped at 1 GiB so it fails before exhausting the host.
- Docker JSON logs rotate at 10 MiB with three files per service (about 150 MiB
  maximum across the five production services).

These are safety ceilings, not a claim that the worker has passed a production
load test. A representative ingest/OCR run should be observed after deployment
before increasing concurrency.

## Important follow-up work

1. Split scheduler, collectors, RQ execution, and delivery adapters into
   separate processes. The current combined process still mixes lifecycle and
   failure domains.
2. Replace archive `extractall` calls with member-by-member safe extraction,
   rejecting traversal paths, excessive member counts, and excessive expanded
   size before writing files.
3. Stop holding database sessions across scraping, attachment downloads, OCR,
   AI calls, and Telegram requests. Persist small state transitions around
   external calls instead.
4. Add RQ job timeouts, queue-level deduplication, retention limits, and
   explicit API handling for Redis enqueue failures.
5. Add a controlled shutdown path for scheduled work and cleanup of a custom
   `WORKER_TEMP_DIR` after interrupted jobs.
6. Break up `apps/api/main.py`; it currently combines API routing, auth,
   analytics, CRM, RAG/chat, and static frontend delivery in one large module.

The intended service boundary is: collectors produce a normalized
`TenderOpportunity`, matching evaluates independent profiles, and delivery
adapters publish to MVN leads, Telegram, email, or an external API.
