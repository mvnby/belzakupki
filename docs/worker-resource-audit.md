# Worker resource-safety audit

## Baseline

The audit started from `main` at `0c514b6`. The unmodified suite passed with
76 tests on Python 3.14.2. Production evidence supplied for the audit showed
the Python worker reaching roughly 1.35–1.37 GiB RSS, a full host swap, two
exit-137 terminations, and a Docker JSON log of roughly 3.38 GiB.

The worker process combined an RQ worker, a Telegram listener, and an embedded
profile scheduler. Before this change, the scheduler could run four profile
pipelines concurrently and could additionally overlap result checking, global
ingest, and an RQ job. Several pipelines loaded every eligible database row,
and OCR rendered every PDF page at 2x resolution.

## Guardrails implemented

- Scheduler, Telegram listener, and RQ consumer now run as separate processes.
  The scheduler only produces deterministic, unique RQ jobs into a bounded
  eight-item queue. The single RQ consumer is the only heavy execution plane.
  Jobs retry after 60, 300, and 900 seconds; a profile is stamped only after
  its complete pipeline succeeds. RQ's scheduler process promotes interval
  retries without reintroducing application threads into the worker.
- AI analysis, local routing, result checks, and notifications use ordered,
  configurable database batches instead of loading an unbounded result set.
  AI walks a fixed pending-ID snapshot with a cursor, commits and clears the
  ORM identity map between batches, and notifications require confirmed
  `ai_relevance=true`. When AI is not configured, each bounded batch is
  explicitly marked as a morphology-based bypass instead of remaining in an
  ambiguous pending state. Worker jobs also drain notification batches to a
  stable empty queue, clearing ORM objects between batches; CLI/API calls keep
  their existing single-batch default.
- Attachment processing defaults to ten files per tender. PDF text extraction
  is capped at 100 pages, OCR at 12 pages, and extracted/AI text at 120,000
  characters. PDF, pixmap, and image resources are released per page.
- Production containers have explicit memory, CPU, and PID ceilings. Defaults
  total 1.75 GiB of hard memory limits. The low-priority worker is capped at
  768 MiB so it fails before exhausting the host.
- Docker JSON logs rotate at 10 MiB with three files per service (about 210 MiB
  maximum across the seven production services).

These are safety ceilings, not a measured capacity guarantee for co-location
with MVN. A representative ingest/OCR run plus the MVN standby must be observed
on the 4 GiB host before this envelope is considered proven.

An AI row that returns no result is intentionally retried by the next periodic
run (normally within 30–60 minutes). Its ID still advances the current cursor,
so one failing early row cannot starve later pending opportunities.

Result checks use the same fixed-snapshot cursor rule. A tender with no result
is visited once in the current hourly run, later IDs still run, and the tender
is eligible for retry in the next hourly snapshot.

## Important follow-up work

1. Replace archive `extractall` calls with member-by-member safe extraction,
   rejecting traversal paths, excessive member counts, and excessive expanded
   size before writing files.
2. Stop holding database sessions across scraping, attachment downloads, OCR,
   AI calls, and Telegram requests. Persist small state transitions around
   external calls instead.
3. Add explicit API handling for Redis enqueue failures and operational queue
   metrics/alerts.
4. Add cleanup of a custom `WORKER_TEMP_DIR` after interrupted jobs.
5. Break up `apps/api/main.py`; it currently combines API routing, auth,
   analytics, CRM, RAG/chat, and static frontend delivery in one large module.

The intended service boundary is: collectors produce a normalized
`TenderOpportunity`, matching evaluates independent profiles, and delivery
adapters publish to MVN leads, Telegram, email, or an external API.
