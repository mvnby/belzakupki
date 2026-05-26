from bs4 import BeautifulSoup

def main():
    with open("scratch/butb_PR20260522377862.html", "r", encoding="utf-8") as f:
        html = f.read()
        
    soup = BeautifulSoup(html, "html.parser")
    
    # 1. Print all anchor links (file attachments)
    print("Anchor links:")
    anchors = soup.find_all("a", href=True)
    file_links = []
    for a in anchors:
        href = a["href"]
        if "/files/" in href or "download" in href or "file" in href:
            file_links.append((a.get_text(" ", strip=True), href))
    for text, href in file_links[:20]:
        print(f"  {text} -> {href}")
        
    # 2. Print elements inside "grid-2-column"
    print("\nGrid columns:")
    grids = soup.find_all(class_=lambda c: c and "grid" in c)
    for g in grids[:5]:
        print(f"Grid class: {g.get('class')}")
        # print first few children text
        children = [child.get_text(" ", strip=True) for child in g.find_all(recursive=False)]
        print(f"  Children: {children[:10]}")
        
    # 3. Print all tables and their headers
    print("\nTables:")
    tables = soup.find_all("table")
    for i, t in enumerate(tables):
        thead = t.find("thead")
        headers = [th.get_text(" ", strip=True) for th in thead.find_all("th")] if thead else []
        tbody = t.find("tbody")
        row_count = len(tbody.find_all("tr")) if tbody else len(t.find_all("tr"))
        print(f"  Table {i}: Headers={headers}, Rows={row_count}")

if __name__ == "__main__":
    main()
