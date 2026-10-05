from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.api.opportunities import _customer_details
from worker.sources.goszakupki_by import parse_tender_details_html


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("filename", "expected_unp", "expected_address", "expected_name", "expected_phone"),
    [
        (
            "goszakupki_live_464.html",
            "300050210",
            "Республика Беларусь, Витебская область, 210 037, г. Витебск, ул. Воинов-Интернационалистов,37",
            "Дудко Максим Александрович",
            "+375212616343",
        ),
        (
            "goszakupki_live_466.html",
            "300582165",
            "Республика Беларусь, Витебская область, 210026, г. Витебск, ул. Суворова, 16",
            "Балашевская Наталия Ивановна",
            "+375214439303",
        ),
    ],
)
def test_real_goszakupki_page_customer_fields(
    filename, expected_unp, expected_address, expected_name, expected_phone
):
    html = (FIXTURES / filename).read_text(encoding="utf-8")
    details = parse_tender_details_html(html)

    assert details["unp"] == expected_unp
    assert details["legal_address"] == expected_address
    assert details["contacts"]["name"] == expected_name
    assert details["contacts"]["phone"] == expected_phone
    assert details["contacts"]["email"] == ""
    assert "101223447" not in str(details)
    assert "info@goszakupki.by" not in str(details)


def test_organization_label_and_embedded_contact_phone():
    html = (FIXTURES / "goszakupki_customer_details.html").read_text(encoding="utf-8")
    details = parse_tender_details_html(html)

    assert details["unp"] == "300050210"
    assert details["legal_address"] == "г. Минск, ул. Примерная, 12"
    assert details["contacts"] == {
        "name": "Иванов Иван Иванович",
        "phone": "+375 29 123-45-67",
        "email": "customer@example.by",
    }
    assert "101223447" not in str(details)
    assert "info@goszakupki.by" not in str(details)


def test_parsed_customer_fields_flow_to_api_projection():
    html = (FIXTURES / "goszakupki_live_464.html").read_text(encoding="utf-8")
    tender = SimpleNamespace(
        customer_name="Учреждение здравоохранения",
        raw_data=parse_tender_details_html(html),
    )

    customer = _customer_details(tender).model_dump()
    assert customer == {
        "name": "Учреждение здравоохранения",
        "unp": "300050210",
        "legal_address": "Республика Беларусь, Витебская область, 210 037, г. Витебск, ул. Воинов-Интернационалистов,37",
        "postal_address": None,
        "contacts": {
            "name": "Дудко Максим Александрович",
            "phone": "+375212616343",
            "email": None,
        },
    }
