import httpx
import json

def main():
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    purchase_gias_id = "52d7a714-65d0-480e-89d9-78f53fd95add"
    url = f"https://gias.by/purchase/api/v1/purchase/{purchase_gias_id}"
    
    with httpx.Client(verify=False, headers=headers) as client:
        r = client.get(url)
        if r.status_code == 200:
            print("Full Details JSON:")
            print(json.dumps(r.json(), indent=2, ensure_ascii=False))
        else:
            print(f"Failed to fetch detail: {r.status_code}")

if __name__ == "__main__":
    main()
