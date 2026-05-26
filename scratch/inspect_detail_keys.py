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
            data = r.json()
            print("Detail JSON Keys:")
            print(list(data.keys()))
            
            # Print organizational and contact details
            print("\nOrganizator:")
            print(data.get("organizator"))
            print("\nContact Organizer:")
            print(data.get("contactOrganizer"))
            print("\nParticipant Requirements:")
            print(data.get("participantRequirements"))
            print("\nNotes:")
            print(data.get("notes"))
            print("\nOne Source Purchase:")
            print(data.get("oneSourcePurchase"))
            
            # Look for any potential payment or delivery keys
            for k, v in data.items():
                if any(x in k.lower() for x in ["pay", "deliv", "term", "cond", "plat", "opl", "srok", "dostav"]):
                    print(f"\nPotential key {k}: {v}")
        else:
            print(f"Failed to fetch detail: {r.status_code}")

if __name__ == "__main__":
    main()
