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
      "url": "https://goszakupki.by/request/view/12345",
      "canonical_url": "https://goszakupki.by/request/view/12345",
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

`tender.canonical_url` is optional and nullable. It identifies the exact current
procurement when an authoritative reference is available, allowing a consumer
to group mirrors within the destination tenant. Consumers must independently
validate and normalize it. Native `source`, `external_id` and `url` stay intact
for scoped details and documents; a canonical reference never grants access.
No title, customer, amount or document similarity establishes identity.

Supported canonical URLs use HTTPS without a `www` alias: Goszakupki
`/{marketing,etrade,request,single-source,single-source-reference,limited}/view/<positive-id>`,
IceTrade `/tenders/all/view/<positive-id>`, and BUTB
`https://zakupki.butb.by/auctions/viewinvitation.html?auction=<identifier>`.
The Goszakupki procedure kind and ID are both identity; BUTB's `auction` query
parameter is identity and must not be removed. Scheme/default-port, host alias,
irrelevant query and fragment differences do not create a second procurement.
Unknown routes, credentials, nondefault ports and lookalike hosts fail closed.
Control characters including DEL are rejected before trimming outer whitespace;
remaining whitespace or backslashes are rejected. Goszakupki and IceTrade accept
one optional trailing path slash; BUTB requires the exact HTML path.

For existing GIAS records, the reference is derived at export from the provider's
top-level `raw_data.auctionUrl`; no backfill is needed. Nested
`oneSourcePurchase.auctionUrl` refers to another procedure and is ignored, as are
`links[*].link` documents. IceTrade extraction accepts only explicitly labelled
current-procurement links in detail tables, including the user-provided real
example `1407896`: the row «Адрес сайта, обеспечивающего доступ на ЭТП» links
to `https://goszakupki.by/limited/view/3836760`. A platform homepage can coexist
in that cell, and document links can appear nearby; neither carries identity.
The regression fixture reproduces that reported structure. Collector-host live
access remains blocked by the upstream 403.
Search requests include the site's current Limited, two-stage and marketing
procedure types alongside the previously enabled types, retaining profile text
and region filters.
Missing listing references or transient detail failures preserve a verified
reference. Two different explicit valid references suppress canonical export,
retain both evidence URLs, and require operator review rather than silently
switching identity. An intervening invalid reference suppresses export while
retaining the prior verified URL for subsequent conflict detection. Release
consumers that accept this field before the collector:
older strict consumers reject unknown fields.

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

When several profiles match the same procurement, retain their independent
states keyed by `match.id`, then aggregate those states under the procurement's
`tenant + source + external_id` key. A rejected match in one profile must not
replace an eligible confirmed match in another. Recompute aggregate eligibility
from the retained matches using the consumer's configured relevance policy;
do not sequentially overwrite one tender-level relevance field with each match.

## GET /api/v1/tenders/{source}/{external_id}

The same `Authorization: Bearer <integration-key>` returns the details for one
tender only when at least one of its matches belongs to the configured tenant
and profile allowlist. A guessed source and external ID therefore cannot expose
another tenant's tender. The response carries the normalized tender fields and
the collector's available customer data. Missing upstream fields stay `null`;
the collector never invents an UNP, address, or corrected contact value.

```json
{
  "source": "goszakupki_by",
  "external_id": "455",
  "source_url": "https://goszakupki.by/...",
  "title": "Поставка оборудования",
  "deadline_at": "2026-10-01T12:00:00Z",
  "estimated_value": "12000 BYN",
  "customer": {
    "name": "Заказчик", "unp": "123456789",
    "legal_address": "г. Минск, ...", "postal_address": null,
    "contacts": {"name": "Иванов И.И.", "phone": "+375...", "email": "mail@example.by"}
  },
  "objects": [{"number": "1", "name": "Оборудование", "quantity": "8 шт."}],
  "documents": [{
    "id": "sha256-hex", "name": "specification.doc",
    "source_url": "https://goszakupki.by/...",
    "extracted_text": "...", "extracted_text_truncated": false
  }]
}
```

`extracted_text` is the collector's saved document extraction, capped at
120,000 characters for each document. It preserves source text as extracted;
the consumer decides whether conflicting contact values need review. The
consumer should impose its own smaller combined prompt budget when assembling
several documents.

`objects` carries source-provided structured procurement objects. Existing
collectors store these as `lots`, so `objects` mirrors `lots` until a provider
supplies a more specific object model. A document-only site or unit breakdown
is not inferred from prose: it remains in `extracted_text` until a source
parser has an explicit, verified schema for it.

## GET /api/v1/tenders/{source}/{external_id}/documents/{document_id}

The same scoped bearer credential downloads the original document bytes. The
service only proxies an HTTPS attachment whose host is the tender source host
or its subdomain, on the source's configured port and without URL credentials.
It validates every redirect under those same rules, follows at most three,
warms source sessions where needed, and enforces a 25 MiB streaming limit. This
keeps source-specific access in BelZakupki while air-api persists its own
attachment. `document_id` comes from the detail response and is a stable
SHA-256 identifier of the document name and source URL.
