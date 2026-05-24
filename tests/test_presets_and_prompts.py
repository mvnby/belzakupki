from __future__ import annotations

import pytest
from belzakupki_db.presets import PRESETS
from worker.analyzer.deepseek_client import (
    get_metadata_system_prompt,
    get_deep_analysis_system_prompt,
)

def test_presets_registry_structure():
    assert "hvac" in PRESETS
    assert "it_services" in PRESETS
    assert "security_systems" in PRESETS
    assert "office_supplies" in PRESETS
    assert "cleaning_services" in PRESETS
    assert "custom" in PRESETS

    for code, preset in PRESETS.items():
        assert preset["code"] == code
        assert "name" in preset
        assert "description" in preset
        assert "default_keywords" in preset
        assert "default_negative_keywords" in preset
        assert isinstance(preset["default_keywords"], list)
        assert isinstance(preset["default_negative_keywords"], list)

def test_get_metadata_system_prompt():
    niche_desc = "Мы занимаемся разработкой сайтов на Python."
    keywords = ["разработка", "сайт", "django"]
    negative_keywords = ["1c", "bitrix"]

    prompt = get_metadata_system_prompt(niche_desc, keywords, negative_keywords)

    assert "Мы занимаемся следующей деятельностью (наша ниша):" in prompt
    assert niche_desc in prompt
    assert "разработка, сайт, django" in prompt
    assert "1c, bitrix" in prompt
    assert '{"type": "json_object"}' not in prompt  # it should be plain template

def test_get_deep_analysis_system_prompt():
    niche_desc = "Услуги клининга и уборки."
    keywords = ["уборка", "клининг"]
    negative_keywords = ["вывоз мусора"]

    prompt = get_deep_analysis_system_prompt(niche_desc, keywords, negative_keywords)

    assert "Our business niche description:" in prompt
    assert niche_desc in prompt
    assert "уборка, клининг" in prompt
    assert "вывоз мусора" in prompt
