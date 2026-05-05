from __future__ import annotations

import argparse

from belzakupki_db.read import (
    list_matches,
    list_tenders,
    serialize_match,
    serialize_tender,
)
from belzakupki_db.seed import seed_database
from belzakupki_db.session import SessionLocal
from worker.ingest import ingest_goszakupki_tenders


def _trim(value: object, width: int = 100) -> str:
    text = "" if value is None else str(value).replace("\n", " ")

    if len(text) <= width:
        return text

    return f"{text[: width - 3]}..."


def _print_tender(item: dict[str, object]) -> None:
    source_number = item.get("source_number") or item.get("external_id") or "-"
    customer_name = item.get("customer_name") or "-"
    deadline = item.get("deadline") or item.get("deadline_at") or "-"
    estimated_value = item.get("estimated_value") or "-"

    print(f"#{item['id']} {source_number} [{item['status']}]")
    print(f"  title: {_trim(item['title'], 120)}")
    print(f"  customer: {_trim(customer_name, 120)}")
    print(f"  deadline: {_trim(deadline, 80)}")
    print(f"  value: {_trim(estimated_value, 80)}")
    print(f"  url: {item['url']}")


def _print_match(item: dict[str, object]) -> None:
    tender = item["tender"]
    profile = item["profile"]

    if not isinstance(tender, dict) or not isinstance(profile, dict):
        raise TypeError("Unexpected match payload")

    keywords = ", ".join(item.get("matched_keywords") or [])

    print(f"#{item['id']} score={item['score']} [{item['status']}]")
    print(f"  profile: {profile['name']}")
    print(f"  keywords: {keywords or '-'}")
    print(f"  tender: {_trim(tender['title'], 120)}")
    print(f"  url: {tender['url']}")


def seed() -> None:
    with SessionLocal() as session:
        seed_database(session)

    print("Seed done")


def ingest_goszakupki() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--search-preset",
        choices=("hvac-vitebsk",),
        default=None,
        help="Use a predefined goszakupki.by search instead of the full posted list.",
    )
    args = parser.parse_args()

    with SessionLocal() as session:
        stats = ingest_goszakupki_tenders(
            session,
            limit=args.limit,
            search_preset=args.search_preset,
        )

    print(
        "Ingest done: "
        f"fetched={stats.fetched} "
        f"created={stats.created} "
        f"updated={stats.updated} "
        f"matches={stats.matches}"
    )


def show_tenders() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--matched-only", action="store_true")
    parser.add_argument("--q", default=None)
    args = parser.parse_args()

    with SessionLocal() as session:
        items = list_tenders(
            session,
            limit=args.limit,
            offset=args.offset,
            matched_only=args.matched_only,
            query=args.q,
        )
        payload = [serialize_tender(item) for item in items]

    if not payload:
        print("No tenders found")
        return

    for index, item in enumerate(payload):
        if index:
            print()
        _print_tender(item)


def show_matches() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()

    with SessionLocal() as session:
        items = list_matches(
            session,
            limit=args.limit,
            offset=args.offset,
        )
        payload = [serialize_match(item) for item in items]

    if not payload:
        print("No matches found")
        return

    for index, item in enumerate(payload):
        if index:
            print()
        _print_match(item)
