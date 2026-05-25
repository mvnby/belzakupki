from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from worker.sources.gias_by import (
    get_mock_tenders,
    fetch_tenders,
    fetch_tenders_for_profiles,
)

def test_get_mock_tenders():
    tenders = get_mock_tenders()
    assert len(tenders) == 2
    for t in tenders:
        assert "external_id" in t
        assert "title" in t
        assert "customer_name" in t
        assert "url" in t
        assert "region" in t
        assert t["currency"] == "BYN"

def test_fetch_tenders():
    # Verify that fetch_tenders returns mock tenders even if network fails (fallback mode)
    tenders = fetch_tenders(limit=1)
    assert len(tenders) == 1
    assert tenders[0]["external_id"] == "gias001"

def test_fetch_tenders_for_profiles():
    profile = MagicMock()
    profile.keywords = ["кондиционер"]
    profile.negative_keywords = ["услуги"]
    profile.regions = None

    matched = fetch_tenders_for_profiles([profile])
    # The first mock tender has 'Поставка кондиционеров и сплит-систем'
    # The second mock tender has 'Услуги по техническому обслуживанию систем кондиционирования' which is blocked by negative keyword 'услуги'
    assert len(matched) == 1
    assert matched[0]["external_id"] == "gias001"
