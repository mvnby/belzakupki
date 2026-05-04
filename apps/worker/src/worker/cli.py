from __future__ import annotations

import argparse

from belzakupki_db.seed import seed_database
from belzakupki_db.session import SessionLocal
from worker.ingest import ingest_goszakupki_tenders


def seed() -> None:
    with SessionLocal() as session:
        seed_database(session)

    print("Seed done")


def ingest_goszakupki() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    with SessionLocal() as session:
        stats = ingest_goszakupki_tenders(session, limit=args.limit)

    print(
        "Ingest done: "
        f"fetched={stats.fetched} "
        f"created={stats.created} "
        f"updated={stats.updated} "
        f"matches={stats.matches}"
    )
