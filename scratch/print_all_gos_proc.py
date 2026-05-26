import httpx
import json

def main():
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    with httpx.Client(verify=False, headers=headers) as client:
        r = client.get("https://gias.by/directory/api/v1/gos_proc")
        if r.status_code == 200:
            print("All procedures:")
            for p in r.json():
                print(f"Code: {p.get('code')}, Name: {p.get('name')}, UUID: {p.get('uuid')}")
        else:
            print(f"Failed to fetch procedures: {r.status_code}")

if __name__ == "__main__":
    main()
