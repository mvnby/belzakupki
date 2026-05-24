import pytest
from decimal import Decimal
from worker.sources.goszakupki_by import parse_tender_result_html as parse_goszakupki_result
from worker.sources.icetrade_by import parse_tender_result_html as parse_icetrade_result

MOCK_GOSZAKUPKI_REQUEST_HTML = """
<html>
<body>
    <div class="wrap">
        <div class="container">
            <pre class="preview">
﻿﻿Протокол оценки и сравнения предложений, выбора участника-победителя или признания процедуры запроса ценовых предложений 
№ auc0003353417 по лоту №1 несостоявшейся

Рассмотрев предложения от 2 участников по лоту №1, комиссия приняла решение:

1     Код: 30861   Дочернее коммунальное унитарное предприятие мелиоративных систем "Зельвенское ПМС"    Дата и время подачи: 13.05.2026 15:20:24
      Адрес: Республика Беларусь, Гродненская область, г.п. Зельва, ул.50 лет ВЛКСМ, 31, 231940   УНП: 590817465   Ценовое предложение: 8 640.20 BYN 
      Решение заказчика (организатора): допущено 

2     Код: 62541   Коммунальное унитарное предприятие мелиоративных систем "Слонимское ПМС"    Дата и время подачи: 14.05.2026 11:36:59
      Адрес: Республика Беларусь, Гродненская область, г. Слоним, ул. Минский тракт, 34, 231800   УНП: 590879165   Ценовое предложение: 8 642.71 BYN 
      Решение заказчика (организатора): допущено 

Результаты оценки и сравнения предложений 2 участников:

1     Код: 30861   Дочернее коммунальное унитарное предприятие мелиоративных систем "Зельвенское ПМС"    Дата и время подачи: 13.05.2026 15:20:24
      Адрес: Республика Беларусь, Гродненская область, г.п. Зельва, ул.50 лет ВЛКСМ, 31, 231940   УНП: 590817465 
      Место: 1    Выбран победителем: Да     Цена договора: 8 640.20 BYN
2     Код: 62541   Коммунальное унитарное предприятие мелиоративных систем "Слонимское ПМС"    Дата и время подачи: 14.05.2026 11:36:59
      Адрес: Республика Беларусь, Гродненская область, г. Слоним, ул. Минский тракт, 34, 231800   УНП: 590879165 
      Место: 2    Выбран победителем: Нет

Признать закупку по лоту №1 состоявшейся 
            </pre>
        </div>
    </div>
</body>
</html>
"""

MOCK_GOSZAKUPKI_AUCTION_HTML = """
<html>
<body>
    <pre class="preview">
﻿﻿Решение заказчика (организатора) о соответствии предложений участников требованиям аукционных документов ко
вторым разделам предложений участников или признания электронного аукциона несостоявшимся по лоту №1 электронного аукциона №auc0003313916

Рассмотрев вторые разделы аукционных предложений от 2 участников по лоту №1, комиссия приняла решение:
1     Код: 84648   Открытое акционерное общество "Белкнига"
      Адрес: Республика Беларусь, г. Минск, ул. Железнодорожная, 27а, к. 18, 220089   УНП: 100026606   Ставка: 8 883.24 BYN 
      Решение: соответствует
2     Код: 41984   Общество с ограниченной ответственностью "БукЛайнГрупп"
      Адрес: Республика Беларусь, г. Минск, ул. Грушевская, 124 цокольный этаж, 220089   УНП: 192713198   Ставка: 8 899.16 BYN 
      Решение: соответствует

Процедуру закупки по лоту №1 признать состоявшейся.

Участником-победителем выбрать Открытое акционерное общество "Белкнига" с ценой договора  8 883.24 BYN 
    </pre>
</body>
</html>
"""

MOCK_ICETRADE_RESULT_HTML = """
<html>
<body>
    <table>
        <tr>
            <td>Результат процедуры закупки</td>
            <td>Состоялась</td>
        </tr>
        <tr>
            <td>№ лота</td>
            <td>Описание предмета закупки</td>
            <td>Участники, с которыми заключен договор</td>
            <td>Цена договора</td>
        </tr>
        <tr>
            <td>1</td>
            <td>Грузовой подъемник в существующую лифтовую шахту 1 ед.</td>
            <td>ООО «СИМСтрейд»</td>
            <td>37 700 BYN</td>
        </tr>
        <tr>
            <td>УНП участников (или номера документов, удостоверяющих личность, для физических лиц), с которыми заключен договор</td>
            <td>192780561</td>
        </tr>
        <tr>
            <td>Иные участники и цены их предложений</td>
            <td>ООО «НОВАСТАР», УНП 491319658 - 39120,00; ООО «Союзпромтехника», УНП 491382789 - 38137,00.</td>
        </tr>
    </table>
</body>
</html>
"""

def test_parse_goszakupki_request_result():
    res = parse_goszakupki_result(MOCK_GOSZAKUPKI_REQUEST_HTML)
    assert res is not None
    assert res["status"] == "Состоялась"
    assert res["winner_name"] == 'Дочернее коммунальное унитарное предприятие мелиоративных систем "Зельвенское ПМС"'
    assert res["winner_unp"] == "590817465"
    assert res["contract_price"] == Decimal("8640.20")
    assert res["currency"] == "BYN"
    assert len(res["participants"]) == 2
    assert res["participants"][0]["name"] == 'Дочернее коммунальное унитарное предприятие мелиоративных систем "Зельвенское ПМС"'
    assert res["participants"][0]["winner"] is True
    assert res["participants"][1]["name"] == 'Коммунальное унитарное предприятие мелиоративных систем "Слонимское ПМС"'
    assert res["participants"][1]["winner"] is False

def test_parse_goszakupki_auction_result():
    res = parse_goszakupki_result(MOCK_GOSZAKUPKI_AUCTION_HTML)
    assert res is not None
    assert res["status"] == "Состоялась"
    assert res["winner_name"] == 'Открытое акционерное общество "Белкнига"'
    assert res["winner_unp"] == "100026606"
    assert res["contract_price"] == Decimal("8883.24")
    assert res["currency"] == "BYN"
    assert len(res["participants"]) == 2
    assert res["participants"][0]["name"] == 'Открытое акционерное общество "Белкнига"'
    assert res["participants"][0]["winner"] is True
    assert res["participants"][1]["name"] == 'Общество с ограниченной ответственностью "БукЛайнГрупп"'
    assert res["participants"][1]["winner"] is False

def test_parse_icetrade_result_page():
    res = parse_icetrade_result(MOCK_ICETRADE_RESULT_HTML)
    assert res is not None
    assert res["status"] == "Состоялась"
    assert res["winner_name"] == "ООО «СИМСтрейд»"
    assert res["winner_unp"] == "192780561"
    assert res["contract_price"] == Decimal("37700")
    assert res["currency"] == "BYN"
    assert len(res["participants"]) == 3
    assert res["participants"][0]["name"] == "ООО «СИМСтрейд»"
    assert res["participants"][0]["winner"] is True
    assert res["participants"][1]["name"] == "ООО «НОВАСТАР»"
    assert res["participants"][1]["unp"] == "491319658"
    assert res["participants"][1]["price"] == "39120,00"
    assert res["participants"][2]["name"] == "ООО «Союзпромтехника»"
    assert res["participants"][2]["unp"] == "491382789"
