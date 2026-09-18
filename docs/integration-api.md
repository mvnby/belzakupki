# Integration API v1

BelZakupki remains an independent collector and relevance service. Consumers
use HTTP only; they never share its database. Interactive users authenticate
with their own login; integration credentials cannot access the management API.

## Authentication and scope

All deployments require a randomly generated `API_SECRET_KEY` (32+ characters).
There is no anonymous first-user fallback. Keep existing users/passwords; rotate
any seed password before enabling production. Missing/weak signing secrets stop
startup. Generate secrets directly in protected environment storage, never in
logs, source control or command-line arguments.

The first consumer is configured by `INTEGRATION_API_KEY` (32+ random characters),
`INTEGRATION_TENANT_ID` and optional comma-separated `INTEGRATION_PROFILE_IDS`.
Only this active tenant's matches are returned. Profile IDs further narrow access;
they cannot widen tenant scope. Omit the profile filter only when all profiles in
that tenant belong to the consumer. Use a different key from `API_SECRET_KEY`.
The initial deployment supports one independently revocable consumer key; a
multi-customer key registry, quotas and billing are separate product work.

## GET /api/v1/opportunities

Supply `Authorization: Bearer <integration-key>` over HTTPS. `limit` is 1–100
(default 100). `cursor` is opaque, signed and tenant-bound. OpenAPI is available
at `/openapi.json` and interactive documentation at `/docs`.

Response:

```json
{
  "items": [{
    "id": 42,
    "updated_at": "2026-09-19T10:00:00Z",
    "profile": {"id": 1, "name": "HVAC"},
    "score": 85,
    "relevance_status": "confirmed",
    "eligible": true,
    "tender": {
      "id": 100, "source": "goszakupki_by", "external_id": "12345",
      "title": "Поставка кондиционеров", "customer_name": "Заказчик",
      "url": "https://goszakupki.by/",
      "deadline_at": "2026-10-01T12:00:00Z",
      "published_at": "2026-09-19T09:00:00Z",
      "estimated_value": "15000 BYN", "contacts": null
    },
    "reason": "Совпадение по профилю HVAC",
    "ai_analysis": {"relevant": true}
  }],
  "next_cursor": null,
  "has_more": false
}
```

This is a **current-state reconciliation feed**, not a lossless event log:

1. Start with no cursor; process each page transactionally.
2. Save `next_cursor` only after successfully applying that page.
3. Continue while `has_more=true`; terminal `next_cursor=null` resets the scan.
4. Start another complete scan on the next polling interval. This deliberately
   revisits existing matches and catches updates to older records without a
   timestamp race with long-running collector transactions.
5. Deduplicate by destination tenant + `tender.source` + `tender.external_id`,
   not match ID: multiple profiles can match the same procurement. Use a stored
   fingerprint to skip unchanged rows. Never overwrite staff status/comments.

`relevance_status` is `confirmed` (AI accepted), `rules_only` (AI bypassed,
including exhausted credits), `pending`, or `rejected`. `eligible` additionally
checks active profile/source, an open procurement status, external ID and deadline.
An unknown deadline remains eligible; consumers can apply a stricter policy.
Automated intake should default to `eligible=true` and `confirmed`; accepting
`rules_only` requires an explicit consumer setting. Relevance is a model/rule
assessment, not a promise that the procurement meets every commercial condition.

Repeated pages are safe to replay. Current-state scans do not publish deletion
tombstones; a disappeared record must never cause automatic deletion of a CRM
lead. The feed is intended for modest per-tenant match volumes; an indexed durable
change log can replace full reconciliation if measured scale requires it.

401 means invalid credentials, 403 means disabled/missing tenant, 400 means
invalid cursor, 422 invalid page parameters, 503 unavailable configuration.
Retry transient failures with bounded backoff; never advance the checkpoint on
failure. After key rotation, cursors remain valid unless the signing key changes.

## Operational probes

`/api/health` and `/healthz` return JSON, verify PostgreSQL and Redis, and return
503 on dependency failures. `/api/ready` additionally requires a recent scheduler
heartbeat and a live RQ worker heartbeat. A deliberate deployment pause returns
503 readiness while the read API remains usable. These probes prove process
availability, not successful collection from every upstream source; monitor
latest successful tender ingest separately.
