from bs4 import BeautifulSoup

def main():
    with open("scratch/butb_PR20260522377862.html", "r", encoding="utf-8") as f:
        html = f.read()
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    for idx, t in enumerate(tables):
        thead = t.find("thead")
        headers = [th.get_text(" ", strip=True) for th in thead.find_all("th")] if thead else []
        print(f"\nTable {idx} Headers: {headers}")
        tbody = t.find("tbody")
        rows = tbody.find_all("tr") if tbody else t.find_all("tr")
        print(f"Row count: {len(rows)}")
        for r_idx, r in enumerate(rows[:5]):
            tds = [td.get_text(" ", strip=True) for td in r.find_all("td")]
            print(f"  Row {r_idx}: {tds}")

if __name__ == "__main__":
    main()
