import httpx

def download(auction_id):
    url = f"https://zakupki.butb.by/auctions/viewinvitation.html?auction={auction_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    with httpx.Client(verify=False, headers=headers) as client:
        r = client.get(url)
        filename = f"scratch/butb_{auction_id}.html"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(r.text)
        print(f"Downloaded {url} to {filename}")

def main():
    download("PR20260522377862")
    # Let's also download the one from the user's example: 4536937 -> AU20260522377729
    # Wait, the user's example had publicPurchaseNumber 4536937, and ETP auction: AU20260522377729
    # Let's download AU20260522377729
    download("AU20260522377729")

if __name__ == "__main__":
    main()
