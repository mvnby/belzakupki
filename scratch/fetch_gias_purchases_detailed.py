import httpx
import json

def main():
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Content-Type": "application/json"
    }
    
    payload = {
        "page": 0,
        "pageSize": 5,
        "sortField": "dtCreate",
        "sortOrder": "DESC"
    }
    
    with httpx.Client(verify=False, headers=headers) as client:
        r = client.post("https://gias.by/search/api/v1/search/purchases", json=payload)
        if r.status_code == 200:
            print("Purchases Search Results:")
            data = r.json()
            # print total elements
            print(f"Total elements: {data.get('totalElements')}")
            # print items
            items = data.get("content", [])
            for i, item in enumerate(items):
                print(f"\n--- Item {i+1} ---")
                print(json.dumps(item, indent=2, ensure_ascii=False))
        else:
            print(f"Failed to fetch search: {r.status_code}")
            print(r.text)

if __name__ == "__main__":
    main()
