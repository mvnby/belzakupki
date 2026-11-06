# AI credits, profile context and notification retries

An AI credit means one completed analysis of a profile/tender match. Both
metadata and document stages together cost one credit; a valid rejection at
either stage also costs one. A missing provider response or an exception does
not consume a credit. Provider token charges are a separate concern.

Before starting AI, a conditional database update reserves a credit against
the current plan, activity flag and billing cycle. Concurrent reservations
cannot exceed the remaining quota. Expiry and 30-day cycle resets are checked
in the database, so stale ORM objects cannot erase new usage. The match result
and charge share a transaction; a per-match savepoint rolls both back on error.
PostgreSQL row locks skip matches already being analyzed by another worker.
Tenant-less legacy profiles retain their existing unmetered behavior.

Reservations use the existing bounded-batch transaction. They can wait for
another transaction for the same tenant. Moving external AI calls out of
database transactions would require a durable reservation/recovery lifecycle;
that remains separate from this fix.

The AI niche is selected in this order:

1. Nonblank `niche_description`.
2. Nonblank description of the profile's `preset_code`.
3. The profile's keywords.
4. A neutral description without an assumed industry.

Both AI stages receive the same resolved niche. Existing HVAC profiles still
use HVAC when it is explicitly selected.

## Delivery state

Migration `a8080519ec64`, following `7f6e8d9c0b1a`, adds `attempt_count` and
`next_attempt_at` to the existing unique `(match_id, channel_id)` log. Historical
log content and match statuses are preserved. Existing logs start with zero
counted attempts; this means unknown historical attempts, not proof of no
earlier delivery.

For each eligible new match, confirmed sent channels are skipped. A failed
channel reuses its existing log, records the error and becomes eligible later:

- `WORKER_NOTIFICATION_MAX_ATTEMPTS=5`, including the initial attempt;
- `WORKER_NOTIFICATION_RETRY_SECONDS=60`, doubling after each failure, capped
  at one hour;
- `next_attempt_at` is the earliest retry time, not a dedicated timer. Delivery
  happens in the next notification job that sees it due;
- after the last failed attempt, the log stays `error`, with no automatic retry.

A match becomes `processed` only after all currently active channels have
confirmed delivery (or there are no active channels). Partial failures leave
it `new`. The drain captures an ID boundary and due time; a failing first batch
cannot starve later matches or retry itself indefinitely. Expired and
unconfirmed matches are not sent. `WORKER_NOTIFICATIONS_ENABLED=false` remains
authoritative, including the API fallback path.

PostgreSQL match locks serialize concurrent dispatchers. Each match commits
its channel results before the next match; a later database failure does not
roll back earlier confirmations. A Telegram timeout after the remote service
accepted a message, or a process crash before the confirmation is committed,
can still produce a duplicate on retry: Telegram sendMessage supplies no
transaction shared with this database. This is not an exactly-once guarantee.

## Verification

Run `python -m pytest`. The reliability suite covers successful/rejected AI
analyses, absent responses, errors, refunds, rollback, quota exhaustion, profile
fallbacks, partial channel failures, retry delays/limits, tenant boundaries and
progress past failed batches. With `TEST_POSTGRES_URL` pointing to the disposable
`belzakupki_test` database, it also checks concurrent workers, concurrent cycle
resets and migration upgrade/downgrade with existing logs. CI provides PostgreSQL
16 and runs these tests; SQLite alone cannot verify row-lock behavior.
