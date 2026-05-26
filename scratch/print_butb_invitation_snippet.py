import httpx
from bs4 import BeautifulSoup

def main():
    url = "https://zakupki.butb.by/auctions/viewinvitation.html?auction=PR20260522377862"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    with httpx.Client(verify=False, headers=headers) as client:
        r = client.get(url)
        soup = BeautifulSoup(r.text, "html.parser")
        
        # Print first few elements with text
        print("Body text snippet:")
        print("\n".join([line.strip() for line in soup.get_text().split("\n") if line.strip()][:30]))

if __name__ == "__main__":
    main()
