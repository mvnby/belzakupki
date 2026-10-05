"""Reviewed, allowlisted refresh for customer details on two tenders."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from belzakupki_db.models import Tender, TenderSource
from belzakupki_db.session import SessionLocal
from worker.sources.goszakupki_by import fetch_tender_details


TARGET_URLS = {
    "3722135": "https://goszakupki.by/marketing/view/3722135",
    "3722307": "https://goszakupki.by/etrade/view/3722307",
}
SOURCE_CODE = "goszakupki_by"
CUSTOMER_CONTACT_KEYS = ("name", "phone", "email")


class CustomerRefreshError(RuntimeError):
    """The allowlisted refresh cannot safely proceed."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _customer_fields(customer_name: str | None, raw_data: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw_data if isinstance(raw_data, dict) else {}
    contact_data = raw.get("contacts")
    if not isinstance(contact_data, dict):
        contact_data = {}
    return {
        "name": customer_name,
        "unp": raw.get("unp"),
        "legal_address": raw.get("legal_address"),
        "contacts": {key: contact_data.get(key) for key in CUSTOMER_CONTACT_KEYS},
    }


def _merge_customer_details(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """Merge only non-empty customer fields and preserve all other raw data."""
    merged = deepcopy(existing) if isinstance(existing, dict) else {}
    for key in ("unp", "legal_address"):
        value = incoming.get(key)
        if isinstance(value, (str, int, float)) and str(value).strip():
            merged[key] = str(value).strip()

    incoming_contacts = incoming.get("contacts")
    if isinstance(incoming_contacts, dict):
        old_contacts = merged.get("contacts")
        contacts = deepcopy(old_contacts) if isinstance(old_contacts, dict) else {}
        for key in CUSTOMER_CONTACT_KEYS:
            value = incoming_contacts.get(key)
            if isinstance(value, str) and value.strip():
                contacts[key] = value.strip()
        if contacts:
            merged["contacts"] = contacts
    return merged


def _load_targets(session: Session, *, lock: bool = False) -> list[Tender]:
    statement = (
        select(Tender)
        .join(TenderSource, Tender.source_id == TenderSource.id)
        .where(Tender.external_id.in_(tuple(TARGET_URLS)))
        .order_by(Tender.external_id, Tender.id)
    )
    if lock:
        statement = statement.with_for_update(of=Tender)
    tenders = list(session.scalars(statement))

    if len(tenders) != len(TARGET_URLS):
        raise CustomerRefreshError(
            f"Expected exactly {len(TARGET_URLS)} stored target rows; found {len(tenders)}"
        )
    found: set[str] = set()
    for tender in tenders:
        external_id = tender.external_id
        if external_id not in TARGET_URLS or external_id in found:
            raise CustomerRefreshError("Stored target rows are missing, duplicated, or outside the allowlist")
        if tender.source.code != SOURCE_CODE:
            raise CustomerRefreshError(f"Tender {external_id} belongs to source {tender.source.code!r}")
        if tender.url != TARGET_URLS[external_id]:
            raise CustomerRefreshError(f"Tender {external_id} has an unexpected source URL")
        found.add(external_id)
    if found != set(TARGET_URLS):
        raise CustomerRefreshError("Stored target ID set does not match the allowlist")
    return tenders


def _snapshot(tender: Tender) -> dict[str, Any]:
    return {
        "id": tender.id,
        "external_id": tender.external_id,
        "source_id": tender.source_id,
        "url": tender.url,
        "customer_name": tender.customer_name,
        "raw_data": deepcopy(tender.raw_data) if isinstance(tender.raw_data, dict) else {},
    }


def _plan_digest(records: list[dict[str, Any]]) -> str:
    digest_input = [
        {
            "snapshot": record["snapshot"],
            "incoming_customer": record["incoming_customer"],
            "after": record["after"],
        }
        for record in records
    ]
    return _sha256({"version": 1, "source": SOURCE_CODE, "records": digest_input})


def build_customer_refresh_plan(
    *,
    session_factory: Callable[[], Session] = SessionLocal,
    fetch_details: Callable[[str], dict[str, Any]] = fetch_tender_details,
) -> dict[str, Any]:
    """Read exact targets, fetch current source pages, and return a digestable plan."""
    with session_factory() as session:
        snapshots = [_snapshot(tender) for tender in _load_targets(session)]

    records = []
    for snapshot in snapshots:
        incoming = fetch_details(snapshot["url"])
        if not isinstance(incoming, dict):
            raise CustomerRefreshError(f"Source parser returned no details for {snapshot['external_id']}")
        after_raw = _merge_customer_details(snapshot["raw_data"], incoming)
        records.append({
            "snapshot": snapshot,
            "incoming_customer": {
                "unp": incoming.get("unp"),
                "legal_address": incoming.get("legal_address"),
                "contacts": {
                    key: (incoming.get("contacts") or {}).get(key)
                    for key in CUSTOMER_CONTACT_KEYS
                } if isinstance(incoming.get("contacts"), dict) else {},
            },
            "before": _customer_fields(snapshot["customer_name"], snapshot["raw_data"]),
            "after": _customer_fields(snapshot["customer_name"], after_raw),
        })

    digest = _plan_digest(records)
    return {
        "plan_digest": digest,
        "source": SOURCE_CODE,
        "records": [
            {
                "id": record["snapshot"]["id"],
                "external_id": record["snapshot"]["external_id"],
                "url": record["snapshot"]["url"],
                "before": record["before"],
                "after": record["after"],
            }
            for record in records
        ],
        "_records": records,
    }


def execute_customer_refresh_plan(
    *,
    reviewed_digest: str,
    session_factory: Callable[[], Session] = SessionLocal,
    fetch_details: Callable[[str], dict[str, Any]] = fetch_tender_details,
) -> dict[str, Any]:
    """Rebuild a reviewed plan, recheck locked rows, then write only customer data."""
    plan = build_customer_refresh_plan(
        session_factory=session_factory,
        fetch_details=fetch_details,
    )
    if not reviewed_digest or plan["plan_digest"] != reviewed_digest:
        raise CustomerRefreshError("Reviewed plan digest is stale or does not match the current source and database")

    records_by_external_id = {
        record["snapshot"]["external_id"]: record for record in plan["_records"]
    }
    with session_factory() as session:
        with session.begin():
            locked = _load_targets(session, lock=True)
            if {t.external_id for t in locked} != set(TARGET_URLS):
                raise CustomerRefreshError("Locked target row set changed after planning")
            for tender in locked:
                record = records_by_external_id[tender.external_id]
                expected = record["snapshot"]
                current = _snapshot(tender)
                if current != expected:
                    raise CustomerRefreshError(
                        f"Tender {tender.external_id} changed after planning; create and review a new plan"
                    )
            for tender in locked:
                incoming = records_by_external_id[tender.external_id]["incoming_customer"]
                tender.raw_data = _merge_customer_details(tender.raw_data, incoming)
            session.flush()

    return {key: value for key, value in plan.items() if key != "_records"}

