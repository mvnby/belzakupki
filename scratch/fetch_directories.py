import httpx
import json

def main():
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    
    with httpx.Client(verify=False, headers=headers) as client:
        # 1. Regions
        r = client.get("https://gias.by/directory/api/v1/regions")
        if r.status_code == 200:
            print("Regions:")
            print(json.dumps(r.json(), indent=2, ensure_ascii=False))
        else:
            print(f"Regions failed: {r.status_code}")
            
        # 2. Gos Proc (Procedures)
        r = client.get("https://gias.by/directory/api/v1/gos_proc")
        if r.status_code == 200:
            print("\nGos Proc:")
            # print first 5 items to save space
            print(json.dumps(r.json()[:5], indent=2, ensure_ascii=False))
        else:
            print(f"Gos Proc failed: {r.status_code}")

if __name__ == "__main__":
    main()
