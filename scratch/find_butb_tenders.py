from belzakupki_db.session import SessionLocal
from belzakupki_db.models import Tender, TenderSource
from sqlalchemy import select

def main():
    with SessionLocal() as session:
        tenders = session.execute(
            select(Tender).join(TenderSource).where(TenderSource.code == "butb_by").limit(5)
        ).scalars().all()
        
        for t in tenders:
            print(f"ID={t.id}, ExternalID={t.external_id}, Title={t.title}")

if __name__ == "__main__":
    main()
