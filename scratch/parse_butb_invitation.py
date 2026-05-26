from bs4 import BeautifulSoup
import re

def get_form_field_value(soup, field_id):
    label = soup.find("label", {"for": field_id})
    if not label:
        return None
    item = label.find_parent("div", class_="ant-form-item")
    if not item:
        item = label.parent.parent
    if item:
        control = item.find(class_="ant-form-item-control")
        if control:
            return control.get_text(" ", strip=True)
    return None

def parse_butb_invitation(html_path):
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
        
    soup = BeautifulSoup(html, "html.parser")
    
    print(f"\n===== Parsing {html_path} =====")
    
    # 1. Standard Fields
    fields = [
        "publicPurchaseNumber",
        "auctionUrl",
        "industry",
        "title",
        "organizatorName",
        "organizatorLocation",
        "organizatorUnp",
        "contactOrganizer",
        "participantRequirements",
        "state",
        "dtCreate",
        "tenderFormName",
        "requestDate"
    ]
    
    for field in fields:
        val = get_form_field_value(soup, field)
        print(f"{field}: {val}")
        
    # 2. Extract contacts info (often in contactOrganizer or structured under contact details)
    # The HTML might have "КОНТАКТНЫЕ ДАННЫЕ" text block
    contacts = {"name": "", "phone": "", "email": ""}
    contact_text = get_form_field_value(soup, "contactOrganizer")
    if contact_text and contact_text != "-":
        contacts["name"] = contact_text
        
    # Check if there is "КОНТАКТНЫЕ ДАННЫЕ" text on the page and extract with regex
    body_text = soup.get_text(" ", strip=True)
    contact_match = re.search(r"КОНТАКТНЫЕ ДАННЫЕ\s*Телефон\s*([^\s]+)\s*E-mail\s*([^\s]+)", body_text)
    if contact_match:
        contacts["phone"] = contact_match.group(1)
        contacts["email"] = contact_match.group(2)
        print(f"Parsed Contact Info: {contacts}")
        
    # 3. Lots Table
    # Find table with headers: Номер лота, Предмет закупки, Количество, Стоимость...
    lots = []
    tables = soup.find_all("table")
    for table in tables:
        thead = table.find("thead")
        if not thead:
            continue
        headers = [th.get_text(" ", strip=True) for th in thead.find_all("th")]
        if any("номер лота" in h.lower() or "предмет закупки" in h.lower() for h in headers):
            # This is the lots table!
            tbody = table.find("tbody")
            if tbody:
                for row in tbody.find_all("tr"):
                    cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
                    # For Ant Design tables, let's filter out empty or collapse cells
                    cells = [c for c in cells if c]
                    if len(cells) >= 4:
                        # Let's map headers to find index
                        # Typically: Number, Name, Qty, Cost, Status
                        lots.append({
                            "number": cells[0],
                            "name": cells[1],
                            "quantity": cells[2],
                            "estimated_value": cells[3],
                            "okrb": cells[4] if len(cells) > 4 else ""
                        })
            break
            
    print(f"Lots found ({len(lots)}):")
    for lot in lots:
        print(lot)
        
    # 4. Documents (Attachments) Table
    # Find table with headers: Дата, Вид документа, Файлы
    attachments = []
    for table in tables:
        thead = table.find("thead")
        if not thead:
            continue
        headers = [th.get_text(" ", strip=True) for th in thead.find_all("th")]
        if any("вид документа" in h.lower() or "файлы" in h.lower() for h in headers):
            tbody = table.find("tbody")
            if tbody:
                for row in tbody.find_all("tr"):
                    # Find the link
                    link = row.find("a", href=True)
                    if link:
                        href = link["href"]
                        name = link.find("span")
                        name_text = name.get_text(" ", strip=True) if name else link.get_text(" ", strip=True)
                        attachments.append({
                            "name": name_text,
                            "url": href
                        })
            break
            
    print(f"Attachments found ({len(attachments)}):")
    for att in attachments:
        print(att)

def main():
    parse_butb_invitation("scratch/butb_PR20260522377862.html")
    parse_butb_invitation("scratch/butb_AU20260522377729.html")

if __name__ == "__main__":
    main()
