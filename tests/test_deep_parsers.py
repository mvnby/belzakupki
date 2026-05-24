import pytest
from worker.sources.goszakupki_by import parse_tender_details_html as parse_goszakupki
from worker.sources.icetrade_by import parse_tender_details_html as parse_icetrade

MOCK_GOSZAKUPKI_HTML = """
<html>
<body>
    <table>
        <tr>
            <th>Контактное лицо</th>
            <td>Иванов Иван Иванович</td>
        </tr>
        <tr>
            <th>Телефон для связи</th>
            <td>+375 29 111-22-33</td>
        </tr>
        <tr>
            <th>Электронная почта (e-mail)</th>
            <td>ivanov@example.com</td>
        </tr>
        <tr>
            <th>Место поставки товара</th>
            <td>г. Минск, ул. Ленина, 1</td>
        </tr>
        <tr>
            <th>Сроки и условия оплаты</th>
            <td>По факту поставки в течение 30 календарных дней</td>
        </tr>
    </table>

    <table>
        <thead>
            <tr>
                <th>Номер лота</th>
                <th>Предмет закупки</th>
                <th>Кол-во</th>
                <th>Код ОКРБ 007-2012</th>
                <th>Ориентировочная стоимость</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>1</td>
                <td>Поставка кондиционеров для нужд предприятия</td>
                <td>2 шт.</td>
                <td>28.25.12</td>
                <td>10 000 BYN</td>
            </tr>
            <tr>
                <td>2</td>
                <td>Поставка вентиляторов напольных офисных</td>
                <td>5 шт.</td>
                <td>28.25.20</td>
                <td>2 000 BYN</td>
            </tr>
        </tbody>
    </table>
</body>
</html>
"""

MOCK_ICETRADE_HTML = """
<html>
<body>
    <table>
        <tr>
            <td>Контактное лицо (ФИО):</td>
            <td>Петров Петр Петрович</td>
        </tr>
        <tr>
            <td>Телефон:</td>
            <td>+375 17 222-33-44</td>
        </tr>
        <tr>
            <td>E-mail:</td>
            <td>petrov@example.com</td>
        </tr>
        <tr>
            <td>Место доставки:</td>
            <td>г. Витебск, ул. Строителей, 10</td>
        </tr>
        <tr>
            <td>Условия финансирования и оплаты:</td>
            <td>Предоплата 10%</td>
        </tr>
    </table>

    <table>
        <tr class="header">
            <td>Лот №</td>
            <td>Наименование предмета государственной закупки</td>
            <td>Количество (объем)</td>
            <td>ОКРБ 007-2012</td>
            <td>Ориентировочная стоимость, BYN</td>
        </tr>
        <tr>
            <td>1</td>
            <td>Работы по техническому обслуживанию систем кондиционирования</td>
            <td>1 услуга</td>
            <td>84.12.11</td>
            <td>5 000</td>
        </tr>
    </table>
</body>
</html>
"""

def test_parse_goszakupki_details():
    res = parse_goszakupki(MOCK_GOSZAKUPKI_HTML)
    assert res["contacts"]["name"] == "Иванов Иван Иванович"
    assert res["contacts"]["phone"] == "+375 29 111-22-33"
    assert res["contacts"]["email"] == "ivanov@example.com"
    assert res["delivery_terms"] == "г. Минск, ул. Ленина, 1"
    assert res["payment_terms"] == "По факту поставки в течение 30 календарных дней"
    
    assert len(res["lots"]) == 2
    assert res["lots"][0]["number"] == "1" or "Лот 1" in res["lots"][0]["number"]
    assert "Поставка кондиционеров" in res["lots"][0]["name"]
    assert res["lots"][0]["quantity"] == "2 шт."
    assert res["lots"][0]["okrb"] == "28.25.12"
    assert res["lots"][0]["estimated_value"] == "10 000 BYN"

def test_parse_icetrade_details():
    res = parse_icetrade(MOCK_ICETRADE_HTML)
    assert res["contacts"]["name"] == "Петров Петр Петрович"
    assert res["contacts"]["phone"] == "+375 17 222-33-44"
    assert res["contacts"]["email"] == "petrov@example.com"
    assert res["delivery_terms"] == "г. Витебск, ул. Строителей, 10"
    assert res["payment_terms"] == "Предоплата 10%"
    
    assert len(res["lots"]) == 1
    assert res["lots"][0]["number"] == "1" or "Лот 1" in res["lots"][0]["number"]
    assert "Работы по техническому обслуживанию" in res["lots"][0]["name"]
    assert res["lots"][0]["quantity"] == "1 услуга"
    assert res["lots"][0]["okrb"] == "84.12.11"
    assert res["lots"][0]["estimated_value"] == "5 000"
