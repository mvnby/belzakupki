from bs4 import BeautifulSoup
import urllib.parse
import json
import re

def parse_butb_invitation_details(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    
    # 1. Parse Grids for general metadata
    data = {}
    grids = soup.find_all(class_=lambda c: c and "grid" in c)
    for g in grids:
        children = [c.get_text(" ", strip=True) for c in g.find_all(recursive=False)]
        for idx, text in enumerate(children):
            clean_txt = text.strip(":")
            if clean_txt in [
                "Регистрационный номер", "Вид процедуры", "Вид процедуры закупки",
                "Состояние", "УНП", "Полное наименование", "Место нахождения",
                "Телефон", "E-mail", "Вид закупки", "Отрасль", "Наименование процедуры",
                "Наименование закупки", "Конечная дата представления информации",
                "Дата окончания приема предложений", "Дата окончания подачи предложений"
            ]:
                if idx + 1 < len(children):
                    val = children[idx+1]
                    if clean_txt in data:
                        if isinstance(data[clean_txt], list):
                            data[clean_txt].append(val)
                        else:
                            data[clean_txt] = [data[clean_txt], val]
                    else:
                        data[clean_txt] = val

    # Helper to get last item if list, else item itself
    def get_last(val):
        if isinstance(val, list):
            return val[-1]
        return val

    source_number = get_last(data.get("Регистрационный номер"))
    procedure_type = get_last(data.get("Вид закупки") or data.get("Вид процедуры"))
    status = get_last(data.get("Состояние"))
    title = get_last(data.get("Наименование процедуры") or data.get("Наименование закупки"))
    customer_name = get_last(data.get("Полное наименование"))
    
    # Contacts
    contacts = {"name": "", "phone": "", "email": ""}
    
    # Extract phone/email from "КОНТАКТНЫЕ ДАННЫЕ" section
    phones = data.get("Телефон")
    emails = data.get("E-mail")
    
    contacts["phone"] = get_last(phones) if phones else ""
    contacts["email"] = get_last(emails) if emails else ""
    
    # Fallback contact parsing from text with regex if empty
    if not contacts["phone"] or not contacts["email"]:
        body_text = soup.get_text(" ", strip=True)
        phone_match = re.search(r"Телефон\s*([+\d\s\(\)-]{7,25})", body_text, re.IGNORECASE)
        email_match = re.search(r"E-mail\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,4})", body_text, re.IGNORECASE)
        if phone_match and not contacts["phone"]:
            contacts["phone"] = phone_match.group(1).strip()
        if email_match and not contacts["email"]:
            contacts["email"] = email_match.group(1).strip()
            
    # Lots & Deliveries
    lots = []
    deliveries = set()
    tables = soup.find_all("table")
    
    for table in tables:
        # SKIP outer layout tables containing nested tables
        if table.find("table") is not None:
            continue
            
        thead = table.find("thead")
        if not thead:
            continue
        headers = [th.get_text(" ", strip=True) for th in thead.find_all("th")]
        if any("№ лота" in h or "предмет закупки" in h.lower() for h in headers):
            h_lower = [h.lower() for h in headers]
            num_idx = h_lower.index("№ лота") if "№ лота" in h_lower else 0
            okrb_idx = h_lower.index("код окрб") if "код окрб" in h_lower else 1
            name_idx = h_lower.index("предмет закупки") if "предмет закупки" in h_lower else 2
            qty_idx = h_lower.index("количество (объем)") if "количество (объем)" in h_lower else 3
            delivery_idx = h_lower.index("место поставки") if "место поставки" in h_lower else -1
            
            value_idx = -1
            for idx, h in enumerate(h_lower):
                if "стоимость" in h or "цена" in h:
                    value_idx = idx
                    
            tbody = table.find("tbody")
            rows = tbody.find_all("tr") if tbody else table.find_all("tr")
            rows = [r for r in rows if not r.find("th")]
            
            for row in rows:
                tds = row.find_all("td")
                if len(tds) > max(num_idx, name_idx):
                    lot_num = tds[num_idx].get_text(" ", strip=True) if len(tds) > num_idx else ""
                    okrb = tds[okrb_idx].get_text(" ", strip=True) if len(tds) > okrb_idx else ""
                    name = tds[name_idx].get_text(" ", strip=True) if len(tds) > name_idx else ""
                    qty = tds[qty_idx].get_text(" ", strip=True) if len(tds) > qty_idx else ""
                    val = tds[value_idx].get_text(" ", strip=True) if value_idx != -1 and len(tds) > value_idx else ""
                    delivery = tds[delivery_idx].get_text(" ", strip=True) if delivery_idx != -1 and len(tds) > delivery_idx else ""
                    
                    if delivery:
                        deliveries.add(delivery)
                        
                    lots.append({
                        "number": lot_num,
                        "okrb": okrb,
                        "name": name,
                        "quantity": qty,
                        "estimated_value": val
                    })
            break
            
    delivery_terms = ", ".join(sorted(list(deliveries))) if deliveries else None

    # 5. Document Attachments
    attachments = []
    for table in tables:
        if table.find("table") is not None:
            continue
            
        thead = table.find("thead")
        if not thead:
            continue
        headers = [th.get_text(" ", strip=True) for th in thead.find_all("th")]
        if any("имя файла" in h.lower() or "наименование документа" in h.lower() for h in headers):
            h_lower = [h.lower() for h in headers]
            name_idx = h_lower.index("наименование документа") if "наименование документа" in h_lower else -1
            file_idx = h_lower.index("имя файла") if "имя файла" in h_lower else -1
            
            tbody = table.find("tbody")
            rows = tbody.find_all("tr") if tbody else table.find_all("tr")
            rows = [r for r in rows if not r.find("th")]
            
            for row in rows:
                tds = row.find_all("td")
                link = row.find("a", href=True)
                if link:
                    href = link["href"]
                    if href.startswith("/"):
                        href = "https://zakupki.butb.by" + href
                    if ";jsessionid=" in href:
                        parts = href.split(";jsessionid=")
                        path_part = parts[0]
                        query_part = parts[1].split("?")[-1] if "?" in parts[1] else ""
                        href = path_part + ("?" + query_part if query_part else "")
                        
                    doc_name = ""
                    if name_idx != -1 and len(tds) > name_idx:
                        doc_name = tds[name_idx].get_text(" ", strip=True)
                    if not doc_name:
                        doc_name = link.get_text(" ", strip=True)
                        
                    attachments.append({
                        "name": doc_name,
                        "url": href
                    })
            break

    # Funding source classification
    funding_source = "Не указан"
    proc_type_val = data.get("Вид закупки")
    if proc_type_val:
        if "бюджет" in proc_type_val.lower():
            funding_source = "Бюджетные средства"
        elif "собствен" in proc_type_val.lower():
            funding_source = "Собственные средства"
            
    payment_terms = "см. документацию" if attachments else None
    
    return {
        "source_number": source_number,
        "procedure_type": procedure_type,
        "status": status,
        "customer_name": customer_name,
        "contacts": contacts if any(contacts.values()) else None,
        "delivery_terms": delivery_terms,
        "payment_terms": payment_terms,
        "funding_source": funding_source,
        "attachments": attachments,
        "lots": lots
    }

def main():
    for name in ["PR20260522377862", "AU20260522377729"]:
        with open(f"scratch/butb_{name}.html", "r", encoding="utf-8") as f:
            html = f.read()
        res = parse_butb_invitation_details(html)
        print("\nParsed Result:")
        print(json.dumps(res, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
