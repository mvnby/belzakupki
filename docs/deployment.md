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
The resolved API secret is validated before services are stopped.
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
