# Shared-host deployment

Deploy only an explicitly reviewed full commit SHA:

```sh
./deploy.sh FULL_40_CHARACTER_COMMIT_SHA
```

The default SSH alias is `mvn-api-by`; an optional second argument overrides it.
The account must permit passwordless `sudo` for deployment. The script archives
that exact committed source locally, stages it in
`/opt/belzakupki/releases/<SHA>`, and retains old releases. Local uncommitted
changes are excluded. Provision `/opt/belzakupki/.env` before the first rollout;
the script never invents production secrets or copies development defaults.

Compose always uses project `belzakupki` and working directory
`/opt/belzakupki`. A build-context override points builds at the pinned release.
The root-owned mode-0600 lock `/var/lock/mvn-shared-host-belzakupki.lock`
coordinates with air-api deployment suspension on this shared host.

This is a cold rollout: scheduler, worker and Telegram receive SIGTERM before the
build. The script waits up to 60 seconds for graceful exit; a busy worker aborts
the rollout before the build and is never force-killed. One release-tagged
image (`belzakupki:<SHA>`) is built and shared by all application services, then
migrations run and API, worker, scheduler and Telegram start.
The resolved API secret is validated before services are stopped. Migration
commands explicitly disable stdin attachment; the local deploy also requires
the remote completion marker emitted after all runtime probes, so an early
zero-status shell exit cannot be mistaken for a successful rollout.
If a build or migration fails, previously running containers are restarted when
still present. Missing/replaced containers and restoration failures are reported;
a private `deploy-recovery.*` record remains for operator recovery. After
containers are replaced, no automatic application rollback is attempted.
This is not an automatic database rollback. Following a rollout
failure, inspect the reported error and migration state before retrying; never
assume source rollback reverses a migration. Keep a database backup before
schema changes. CPU and memory headroom for Docker builds must be checked by the
operator; runtime service limits do not bound the Docker builder.

Verification requires database/Redis health, fresh worker/scheduler readiness,
an HTTP 401 for anonymous `/api/auth/me`, and all four processes running. These
checks run inside the API container. Separately verify the public HTTPS endpoint
when routing is intentionally provisioned or changed. This script neither starts
nor recreates Caddy and never changes its routes. It performs no system-wide
Docker cleanup and does not delete other projects' containers or images.

# Attachment extraction limits

ZIP and RAR entries are validated before extraction, including paths, links,
member count and declared expanded bytes. Selected document entries stream into
generated isolated directories with actual-byte checks. Nested archives are not
expanded. RAR requires a version exposing link metadata; other versions fail
closed. 7z extraction is disabled because supported py7zr versions do not share
a bounded streaming interface. Unsupported or rejected attachments contribute no
text and log a warning; the rest of the tender remains available.

Defaults: `WORKER_ARCHIVE_MAX_MEMBERS=100`,
`WORKER_ARCHIVE_MAX_BYTES=52428800`,
`WORKER_SPREADSHEET_MAX_ROWS=10000`,
`WORKER_SPREADSHEET_MAX_COLUMNS=256`,
`WORKER_EXTRACTED_TEXT_MAX_CHARS=120000`.
DOCX/XLSX ZIP packages also undergo the archive preflight before their parsers
open them. Text collection stops at its budget, rather than collecting the whole
document first; spreadsheet rows have a separate iteration limit. Binary Word
conversion has a 10-second deadline and bounded stdout. Native parsers and a
single PDF page can still allocate before returning text; service memory limits
remain the final containment boundary.

## Redis durability migration

Redis uses an external Docker volume selected by `REDIS_DATA_VOLUME`
(default `belzakupki_redis_data`), with AOF enabled, `appendfsync everysec` and
`maxmemory-policy noeviction`. The volume survives Compose removal. AOF everysec
limits the usual sudden-crash loss window to approximately one second; it is not
a replacement for backups.

For an existing deployment, preserve the **exact current** Docker volume mounted
at Redis `/data`, even when its name is an anonymous hash. Put that name in
`/opt/belzakupki/.env` as `REDIS_DATA_VOLUME`. Do not attach a new empty named
volume. Before recreating Redis, enable AOF on the existing running instance
(`CONFIG SET appendonly yes`) and wait until `INFO persistence` reports
`aof_enabled:1`, `aof_rewrite_in_progress:0`, `aof_rewrite_scheduled:0`,
`aof_last_bgrewrite_status:ok`, and `aof_last_write_status:ok`. Take a backup and
coordinate this migration under the shared-host deployment lock. Starting Redis
with `appendonly yes` before its existing data has been written to AOF can ignore
the old RDB data, so the order is essential.

The deploy script checks the actual mount and AOF readiness before stopping any
service. A mismatched volume, missing mount, stopped Redis or incomplete/failed
AOF rewrite aborts the rollout. For a fresh installation without a Redis
container, it creates the selected external volume under the deployment lock;
Docker retains that volume on subsequent deployments. Moving data to a different
volume is a separate explicit migration, never an automatic deploy action.

## Results maintenance fairness

Scheduled results checks process at most `WORKER_RESULTS_JOB_BATCH_SIZE` tenders
(default 5) per RQ job. Progress (`after_id`, frozen `through_id`, next scan time)
lives in the persistent Redis key `belzakupki:results-check:progress:v1` without
a TTL. The database commits before cursor advancement. A crash between commit
and Redis checkpoint can repeat the last chunk safely; completed result writes
are idempotent, and no-result rows also advance after a committed attempt.

The scheduler queues fresh ingestion and due profiles before results maintenance.
An unfinished snapshot resumes on each scheduler poll; when it ends, a new scan
starts after a one-hour cooldown. The deterministic unique scheduled job ID
prevents concurrent maintenance jobs. Do not enqueue the same callable under
arbitrary IDs while a scheduled maintenance job is active.

This is a row-count bound, not a hard wall-clock guarantee: each source's HTTP
requests and retries can still delay a chunk. Monitor actual chunk duration and
upstream failures; reducing the count reduces the maximum number of slow lookups
in a job. The old complete-snapshot drain helper remains for explicit maintenance
use, but the scheduler no longer calls it.
