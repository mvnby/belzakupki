from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session

from belzakupki_db.read import (
    get_tender,
    list_matches,
    list_tenders,
    serialize_match,
    serialize_tender,
)
from belzakupki_db.session import get_session

app = FastAPI(title="belzakupki")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/tenders")
def tenders(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    matched_only: bool = False,
    q: str | None = Query(default=None, min_length=1),
    session: Session = Depends(get_session),
):
    items = list_tenders(
        session,
        limit=limit,
        offset=offset,
        matched_only=matched_only,
        query=q,
    )

    return {
        "items": [serialize_tender(item) for item in items],
        "limit": limit,
        "offset": offset,
    }


@app.get("/tenders/{tender_id}")
def tender(tender_id: int, session: Session = Depends(get_session)):
    item = get_tender(session, tender_id)

    if item is None:
        raise HTTPException(status_code=404, detail="Tender not found")

    return serialize_tender(item)


@app.get("/matches")
def matches(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    items = list_matches(session, limit=limit, offset=offset)

    return {
        "items": [serialize_match(item) for item in items],
        "limit": limit,
        "offset": offset,
    }
