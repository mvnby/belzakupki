from belzakupki_db.session import SessionLocal
from belzakupki_db.models import Tender
from belzakupki_db.read import serialize_tender
from sqlalchemy import select
import json

def main():
    with SessionLocal() as session:
        tender = session.execute(
            select(Tender).where(Tender.external_id == "52d7a714-65d0-480e-89d9-78f53fd95add")
        ).scalar_one_or_none()
        
        if tender:
            print("Tender in DB:")
            print("Title:", tender.title)
            print("Status:", tender.status)
            print("Deadline:", tender.deadline_at)
            
            # Serialize
            serialized = serialize_tender(tender)
            print("\nSerialized JSON:")
            print(json.dumps(serialized, indent=2, ensure_ascii=False, default=str))
        else:
            print("Tender not found in DB")

if __name__ == "__main__":
    main()
