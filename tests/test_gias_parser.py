from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest

from worker.sources.gias_by import (
    extract_region_fallback,
    map_gias_tender,
    fetch_tenders,
    fetch_tenders_for_profiles,
)


def test_extract_region_fallback():
    # Test fallback extraction from organizer location/name
    assert extract_region_fallback({"organizator": {"name": "Брестский облисполком"}}) == "1"
    assert extract_region_fallback({"organizator": {"location": "Витебская обл., г. Орша"}}) == "2"
    assert extract_region_fallback({"organizator": {"name": "УЗ Минская областная клиническая больница"}}) == "6"
    assert extract_region_fallback({"organizator": {"name": "г. Минск, пр. Независимости"}}) == "5"
    assert extract_region_fallback({"organizator": {"name": "Неизвестная компания"}}) is None


def test_map_gias_tender_minimal():
    # Test mapping with minimal search item data
    item = {
        "purchaseGiasId": "test-uuid",
        "title": "Test Title",
        "stateName": "Подача предложений",
        "dtCreate": 1779458632652,
        "requestDate": 1779915599999,
        "sumLot": {
            "sumLot": 45000.0
        },
        "organizator": {
            "name": "Витебский областной комитет"
        }
    }
    
    mapped = map_gias_tender(item)
    assert mapped["external_id"] == "test-uuid"
    assert mapped["title"] == "Test Title"
    assert mapped["status"] == "Подача предложений"
    assert mapped["estimated_value"] == 45000.0
    assert mapped["currency"] == "BYN"
    assert mapped["region"] == "2"  # extracted via fallback
    assert mapped["procedure_type"] == "Не указана"  # tenderForm is missing
    assert mapped["published_at"] == datetime.fromtimestamp(1779458632.652, tz=timezone.utc)
    assert mapped["deadline_at"] == datetime.fromtimestamp(1779915599.999, tz=timezone.utc)


def test_map_gias_tender_with_detail():
    # Test mapping using detailed tender information
    item = {
        "purchaseGiasId": "test-uuid",
        "title": "Search Title",
    }
    detail = {
        "purchaseGiasId": "test-uuid",
        "title": "Detailed Title",
        "tenderForm": 2,  # электронный аукцион
        "region": 7,  # г. Минск (maps to canonical 5)
        "dtCreate": 1779458632652,
        "requestDate": 1779915599999,
        "sumLot": {
            "sumLot": 120000.5
        },
        "codeCurrencyToEtp": "933",
        "organizator": {
            "name": "МинскОрг",
            "location": "Минск"
        }
    }
    
    mapped = map_gias_tender(item, detail)
    assert mapped["external_id"] == "test-uuid"
    assert mapped["title"] == "Detailed Title"
    assert mapped["procedure_type"] == "электронный аукцион"
    assert mapped["region"] == "5"
    assert mapped["estimated_value"] == 120000.5
    assert mapped["currency"] == "BYN"


@patch("httpx.Client")
def test_fetch_tenders_success(mock_client_class):
    # Mock the Client instance and its methods
    mock_client = MagicMock()
    mock_client_class.return_value.__enter__.return_value = mock_client
    
    # 1. Mock search response
    mock_search_res = MagicMock()
    mock_search_res.status_code = 200
    mock_search_res.json.return_value = {
        "content": [
            {
                "purchaseGiasId": "uuid-1",
                "title": "Tender 1"
            }
        ]
    }
    mock_client.post.return_value = mock_search_res
    
    # 2. Mock detail response
    mock_detail_res = MagicMock()
    mock_detail_res.status_code = 200
    mock_detail_res.json.return_value = {
        "purchaseGiasId": "uuid-1",
        "title": "Tender 1 Detail",
        "tenderForm": 3,  # запрос ценовых предложений
        "region": 1,
        "sumLot": {
            "sumLot": 5000.0
        },
        "organizator": {
            "name": "БрестАгро"
        }
    }
    mock_client.get.return_value = mock_detail_res
    
    tenders = fetch_tenders(limit=1)
    
    assert len(tenders) == 1
    t = tenders[0]
    assert t["external_id"] == "uuid-1"
    assert t["title"] == "Tender 1 Detail"
    assert t["procedure_type"] == "процедура запроса ценовых предложений"
    assert t["region"] == "1"
    assert t["estimated_value"] == 5000.0


@patch("worker.sources.gias_by.fetch_tenders")
def test_fetch_tenders_for_profiles(mock_fetch):
    mock_tenders = [
        {
            "external_id": "uuid-1",
            "title": "Поставка кондиционеров в Гродно",
            "region": "4",
        },
        {
            "external_id": "uuid-2",
            "title": "Строительство детского сада в Бресте",
            "region": "1",
        }
    ]
    mock_fetch.return_value = mock_tenders
    
    profile = MagicMock()
    profile.keywords = ["кондиционер"]
    profile.negative_keywords = []
    profile.regions = ["4"]
    
    matched = fetch_tenders_for_profiles([profile])
    assert len(matched) == 1
    assert matched[0]["external_id"] == "uuid-1"
