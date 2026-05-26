import httpx
from bs4 import BeautifulSoup

def main():
    url = "https://zakupki.butb.by/auctions/viewinvitation.html?auction=PR20260522377862"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    with httpx.Client(verify=False, headers=headers) as client:
        r = client.get(url)
        print("Status code:", r.status_code)
        print("Final URL:", r.url)
        
        soup = BeautifulSoup(r.text, "html.parser")
        print("\nPage title:", soup.title.string if soup.title else None)
        
        # Look for typical fields of invitation page
        form_texts = soup.get_text()
        print("\nContains 'Сведения о закупке':", "Сведения о закупке" in form_texts)
        print("Contains 'заказчик':", "заказчик" in form_texts.lower())
        print("Contains 'PR20260522377862':", "PR20260522377862" in form_texts)

if __name__ == "__main__":
    main()
