from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest

from worker.sources.butb_by import (
    parse_date,
    parse_price,
    extract_region,
    parse_tenders_html,
    fetch_tenders_for_profiles,
    parse_tender_details_html,
    fetch_tender_details,
    fetch_tender_attachments,
)

def test_parse_date():
    assert parse_date("22.05.2026") == datetime(2026, 5, 21, 21, 0, tzinfo=timezone.utc)
    assert parse_date(None) is None
    assert parse_date("invalid") is None

def test_parse_price():
    val, curr = parse_price("66 978,12 BYN")
    assert val == 66978.12
    assert curr == "BYN"

    val, curr = parse_price("1 200,00 USD")
    assert val == 1200.0
    assert curr == "USD"

    val, curr = parse_price(None)
    assert val is None
    assert curr == "BYN"

def test_extract_region():
    assert extract_region("Витебский областной исполнительный комитет") == "2"
    assert extract_region("УЗ 'Брестская городская больница'") == "1"
    assert extract_region("Минский областной исполнительный комитет") == "6"
    assert extract_region("Минский городской исполнительный комитет") == "5"
    assert extract_region("ООО 'Коммерческая компания'") is None

def test_parse_tenders_html():
    mock_html = """
    <table>
        <tr>
            <td>PR20260522377862</td>
            <td>Поставка кондиционеров и сплит-систем</td>
            <td>запрос ценовых предложений</td>
            <td>22.05.2026</td>
            <td>66 978,12 BYN</td>
            <td>Витебский областной исполнительный комитет</td>
            <td>Бюджетные средства</td>
            <td>29.05.2026</td>
            <td>Подача предложений</td>
        </tr>
        <tr>
            <td>AU20260522377863</td>
            <td>Техническое обслуживание сплит-систем</td>
            <td>электронный аукцион</td>
            <td>23.05.2026</td>
            <td>12 000,00 BYN</td>
            <td>УЗ 'Гродненская областная клиническая больница'</td>
            <td>Бюджетные средства</td>
            <td>30.05.2026</td>
            <td>Подача предложений</td>
        </tr>
        <tr>
            <td>invalid-row-id</td>
            <td>Should be skipped</td>
            <td>...</td>
            <td>...</td>
            <td>...</td>
            <td>...</td>
            <td>...</td>
            <td>...</td>
            <td>...</td>
        </tr>
    </table>
    """
    tenders = parse_tenders_html(mock_html)
    assert len(tenders) == 2
    
    t0 = tenders[0]
    assert t0["external_id"] == "PR20260522377862"
    assert t0["title"] == "Поставка кондиционеров и сплит-систем"
    assert t0["procedure_type"] == "запрос ценовых предложений"
    assert t0["url"] == "https://zakupki.butb.by/auctions/viewinvitation.html?auction=PR20260522377862"
    assert t0["estimated_value"] == 66978.12
    assert t0["currency"] == "BYN"
    assert t0["region"] == "2"
    assert t0["funding_source"] == "Бюджетные средства"

    t1 = tenders[1]
    assert t1["external_id"] == "AU20260522377863"
    assert t1["url"] == "https://zakupki.butb.by/auctions/viewinvitation.html?auction=AU20260522377863"
    assert t1["region"] == "4"

@patch("worker.sources.butb_by.fetch_tenders")
def test_fetch_tenders_for_profiles(mock_fetch):
    mock_tenders = [
        {
            "external_id": "PR20260522377862",
            "title": "Поставка кондиционеров и сплит-систем",
            "region": "2",
        },
        {
            "external_id": "AU20260522377863",
            "title": "Установка оконных блоков",
            "region": "4",
        }
    ]
    mock_fetch.return_value = mock_tenders

    profile = MagicMock()
    profile.keywords = ["кондиционер"]
    profile.negative_keywords = ["услуги"]
    profile.regions = None

    matched = fetch_tenders_for_profiles([profile])
    assert len(matched) == 1
    assert matched[0]["external_id"] == "PR20260522377862"


def test_parse_tender_details_html():
    mock_html = """
    <div class="grid">
        <div>Регистрационный номер:</div>
        <div>PR20260522377862</div>
        <div>Вид закупки:</div>
        <div>государственная (бюджет)</div>
        <div>Состояние:</div>
        <div>Подача предложений</div>
        <div>Полное наименование:</div>
        <div>Республиканское унитарное предприятие</div>
        <div>Телефон:</div>
        <div>+375232 35 67 14</div>
        <div>E-mail:</div>
        <div>203@mdt.by</div>
    </div>
    <table>
        <thead>
            <tr>
                <th>№ лота</th>
                <th>Код ОКРБ</th>
                <th>Предмет закупки</th>
                <th>Количество (объем)</th>
                <th>Место поставки</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>1</td>
                <td>32.50.13.650</td>
                <td>Краник трехходовой запорный</td>
                <td>127 500 шт.</td>
                <td>г. Гомель, ул. Чонгарской дивизии 14</td>
            </tr>
        </tbody>
    </table>
    <table>
        <thead>
            <tr>
                <th>Наименование документа</th>
                <th>Имя файла</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>Запрос цены</td>
                <td><a href="/auctions/download?id=5782804;jsessionid=abc?download=1">pr_purchase.pdf</a></td>
            </tr>
        </tbody>
    </table>
    """
    
    details = parse_tender_details_html(mock_html)
    assert details["source_number"] == "PR20260522377862"
    assert details["procedure_type"] == "государственная (бюджет)"
    assert details["status"] == "Подача предложений"
    assert details["customer_name"] == "Республиканское унитарное предприятие"
    assert details["contacts"] == {
        "name": "",
        "phone": "+375232 35 67 14",
        "email": "203@mdt.by"
    }
    assert details["delivery_terms"] == "г. Гомель, ул. Чонгарской дивизии 14"
    assert details["payment_terms"] == "см. документацию"
    assert details["funding_source"] == "Бюджетные средства"
    assert len(details["attachments"]) == 1
    assert details["attachments"][0] == {
        "name": "Запрос цены",
        "url": "https://zakupki.butb.by/auctions/download?id=5782804&download=1"
    }
    assert len(details["lots"]) == 1
    assert details["lots"][0] == {
        "number": "1",
        "okrb": "32.50.13.650",
        "name": "Краник трехходовой запорный",
        "quantity": "127 500 шт.",
        "estimated_value": ""
    }


@patch("worker.sources.butb_by.httpx.Client")
def test_fetch_tender_details(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value.__enter__.return_value = mock_client
    
    mock_response_main = MagicMock()
    mock_response_main.status_code = 200
    
    mock_response_detail = MagicMock()
    mock_response_detail.status_code = 200
    mock_response_detail.text = "<div class='grid'><div>Регистрационный номер:</div><div>PR123</div></div>"
    
    mock_client.get.side_effect = [mock_response_main, mock_response_detail]
    
    details = fetch_tender_details("https://zakupki.butb.by/auctions/viewinvitation.html?auction=PR123")
    assert details["source_number"] == "PR123"


@patch("worker.sources.butb_by.fetch_tender_details")
def test_fetch_tender_attachments(mock_fetch):
    mock_fetch.return_value = {
        "attachments": [{"name": "doc1.pdf", "url": "http://link"}]
    }
    attachments = fetch_tender_attachments("http://url")
    assert len(attachments) == 1
    assert attachments[0]["name"] == "doc1.pdf"

