from worker.sources.goszakupki_by import parse_tender_details_html


def lot(number, name, quantity, status, place, okrb):
    return f"""
      <tr class="lot-row">
        <th class="lot-num">{number}</th><td class="lot-description">{name}</td>
        <td class="lot-count-price">{quantity}</td><td class="lot-status">{status}</td>
      </tr>
      <tr id="lot-inf-{number}" class="lot-inf"><td></td><td></td><td colspan="3">
        <div><b>Срок поставки:</b><span class="col-md-6">с 01.12.2026 по 25.12.2026</span></div>
        <div><b>Место (места) поставки товара (выполнения работ, оказания услуг):</b>
          <span class="col-md-6">{place}</span></div>
        <div><b>Код предмета закупки по ОКРБ:</b><span class="col-md-6">{okrb}</span></div>
      </td></tr>
    """


def table(*rows):
    return '<table id="lotsList"><thead><tr><th>№ лота</th><th>Предмет закупки</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table>"


def test_native_rows_keep_quantity_cost_and_executing_site_per_lot():
    html = table(
        lot(1, "Перенос кондиционера", "1 услуга, 2 450.30 BYN", "Подача предложений",
            "Витебская область, г. Лепель, пл. Свободы 11-2", "43.39.19.100"),
        lot(2, "Монтаж вентиляции", "2 единицы, 10 100.00 BYN", "Отменен",
            "Витебская область, г. Витебск", "43.22.12.200"),
    )
    result = parse_tender_details_html(html)
    assert result["lot_inventory_complete"]
    one, two = result["lots"]
    assert one == {
        "number": "1", "name": "Перенос кондиционера", "quantity": "1 услуга", "estimated_value": "2 450.30 BYN",
        "status": "Подача предложений", "okrb": "43.39.19.100", "delivery_period": "с 01.12.2026 по 25.12.2026",
        "delivery_place": "Витебская область, г. Лепель, пл. Свободы 11-2",
    }
    assert two["number"] == "2" and two["status"] == "Отменен"
    assert two["delivery_place"] == "Витебская область, г. Витебск"


def test_conflicting_lot_rows_make_inventory_incomplete_without_fake_lot_numbers():
    repeated = lot(1, "Кондиционеры", "2 шт.", "Подача предложений", "Минск", "28.25.12")
    other = lot(2, "Вентиляция", "1 шт.", "Подача предложений", "Витебск", "43.22.12.200")
    result = parse_tender_details_html(table(repeated, repeated, other))
    assert not result["lot_inventory_complete"]
    assert [item["number"] for item in result["lots"]] == ["2"]
