import httpx
import json
from datetime import datetime, timezone

GIAS_PROCEDURE_TYPES = {
    1: "открытый конкурс",
    2: "электронный аукцион",
    3: "процедура запроса ценовых предложений",
    4: "процедура закупки из одного источника",
    5: "биржевые торги",
    6: "двухэтапный конкурс",
    7: "конкурс с ограниченным участием",
    8: "процедура закупки из одного источника на ЭТП",
}

def extract_region(item: dict) -> str | None:
    org = item.get("organizator") or {}
    location = org.get("location") or ""
    name = org.get("name") or ""
    text = (name + " " + location).lower()
    
    if "брест" in text:
        return "1"
    if "витеб" in text:
        return "2"
    if "гоме" in text:
        return "3"
    if "гродн" in text:
        return "4"
    if "могил" in text:
        return "7"
    if "минс" in text or "белфармация" in text or "белмедтехника" in text or "белжелдорснаб" in text:
        if "област" in text or "район" in text:
            return "6"
        return "5"
    return None

def map_gias_tender(item: dict, detail: dict | None = None) -> dict:
    d = detail or item
    purchase_gias_id = d.get("purchaseGiasId") or item.get("purchaseGiasId")
    external_id = purchase_gias_id
    
    title = d.get("title") or item.get("title")
    org = d.get("organizator") or item.get("organizator") or {}
    customer_name = org.get("name")
    url = f"https://gias.by/gias/#/purchase/current/{purchase_gias_id}"
    status = d.get("stateName") or item.get("stateName")
    
    tender_form = d.get("tenderForm")
    procedure_type = GIAS_PROCEDURE_TYPES.get(tender_form, "Не указана")
    funding_source = "Не указан"
    
    sum_lot_obj = d.get("sumLot") or item.get("sumLot") or {}
    estimated_value = sum_lot_obj.get("sumLot")
    
    currency = d.get("codeCurrencyToEtp")
    if currency == "933":
        currency = "BYN"
    elif not currency:
        currency = "BYN"
        
    dt_create = d.get("dtCreate") or item.get("dtCreate")
    published_at = None
    if dt_create:
        published_at = datetime.fromtimestamp(dt_create / 1000, tz=timezone.utc)
        
    request_date = d.get("requestDate") or item.get("requestDate")
    deadline_at = None
    if request_date:
        deadline_at = datetime.fromtimestamp(request_date / 1000, tz=timezone.utc)
        
    gias_region = d.get("region")
    region = None
    if gias_region is not None:
        gias_region_str = str(gias_region)
        gias_to_canonical = {
            "1": "1",
            "2": "2",
            "3": "3",
            "4": "4",
            "5": "6",
            "6": "7",
            "7": "5"
        }
        region = gias_to_canonical.get(gias_region_str)
        
    if not region:
        region = extract_region(d)
        
    return {
        "external_id": external_id,
        "title": title,
        "customer_name": customer_name,
        "url": url,
        "status": status,
        "procedure_type": procedure_type,
        "funding_source": funding_source,
        "estimated_value": estimated_value,
        "currency": currency,
        "published_at": published_at,
        "deadline_at": deadline_at,
        "region": region,
    }

def main():
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Content-Type": "application/json"
    }
    
    payload = {
        "page": 0,
        "pageSize": 3,
        "sortField": "dtCreate",
        "sortOrder": "DESC"
    }
    
    # Increase timeout to 30 seconds
    with httpx.Client(verify=False, headers=headers, timeout=30.0) as client:
        # Search list
        print("Fetching search list...")
        r = client.post("https://gias.by/search/api/v1/search/purchases", json=payload)
        if r.status_code == 200:
            content = r.json().get("content", [])
            print(f"Found {len(content)} items. Fetching details...")
            for item in content:
                purchase_gias_id = item.get("purchaseGiasId")
                detail_url = f"https://gias.by/purchase/api/v1/purchase/{purchase_gias_id}"
                print(f"Fetching detail: {detail_url}")
                r_detail = client.get(detail_url)
                detail = r_detail.json() if r_detail.status_code == 200 else None
                
                mapped = map_gias_tender(item, detail)
                print(json.dumps(mapped, indent=2, ensure_ascii=False, default=str))
        else:
            print(f"Search failed: {r.status_code}")

if __name__ == "__main__":
    main()
