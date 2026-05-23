"""Unit-tests for worker.morphology (no DB, no network).

These tests run with and without pymorphy3 installed:
  - If pymorphy3 is present, they verify morphological normalisation.
  - If it's absent, they verify the plain-casefold fallback still works.
"""
from __future__ import annotations

import importlib
import sys

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_morphology_module():
    """Force re-import of morphology so the cached analyser is cleared."""
    for mod in list(sys.modules.keys()):
        if "morphology" in mod:
            del sys.modules[mod]


# ---------------------------------------------------------------------------
# Basic normalisation
# ---------------------------------------------------------------------------

class TestNormaliseForMatching:
    def test_lowercases(self):
        from worker.morphology import normalise_for_matching
        result = normalise_for_matching("КОНДИЦИОНЕР")
        assert result == result.casefold()

    def test_collapses_whitespace(self):
        from worker.morphology import normalise_for_matching
        result = normalise_for_matching("  много   пробелов  ")
        assert "  " not in result
        assert result == result.strip()

    def test_empty_string(self):
        from worker.morphology import normalise_for_matching
        assert normalise_for_matching("") == ""

    def test_returns_string(self):
        from worker.morphology import normalise_for_matching
        assert isinstance(normalise_for_matching("тест"), str)


# ---------------------------------------------------------------------------
# Morphological matching (integration — requires pymorphy3)
# ---------------------------------------------------------------------------

PYMORPHY3_AVAILABLE = importlib.util.find_spec("pymorphy3") is not None


@pytest.mark.skipif(not PYMORPHY3_AVAILABLE, reason="pymorphy3 not installed")
class TestMorphologicalNormalisation:
    def test_nominative_to_lemma(self):
        from worker.morphology import normalise_for_matching
        assert normalise_for_matching("кондиционер") == normalise_for_matching("кондиционеров")

    def test_genitive_plural_matches_nominative(self):
        from worker.morphology import normalise_for_matching
        assert normalise_for_matching("вентиляция") == normalise_for_matching("вентиляции")

    def test_verb_form_matches_infinitive(self):
        from worker.morphology import normalise_for_matching
        # "поставляет" → "поставлять" and "поставлять" → "поставлять"
        inf = normalise_for_matching("поставлять")
        conj = normalise_for_matching("поставляет")
        assert inf == conj

    def test_scoring_finds_inflected_form(self):
        """End-to-end: keyword 'кондиционер' should match text with 'кондиционеров'."""
        from worker.scoring import score_text
        result = score_text(
            "Закупка кондиционеров для административного здания",
            ["кондиционер"],
            [],
        )
        assert result.score > 0, (
            "Expected non-zero score when keyword lemma matches inflected form in text"
        )


# ---------------------------------------------------------------------------
# Fallback without pymorphy3
# ---------------------------------------------------------------------------

class TestBuildNormalisedKeyword:
    def test_plain_keyword(self):
        from worker.morphology import build_normalised_keyword
        result = build_normalised_keyword("Кондиционер")
        assert isinstance(result, str)
        assert result  # non-empty
