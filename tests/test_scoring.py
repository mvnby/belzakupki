"""Unit-tests for worker.scoring (pure, no DB, no network)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from worker.scoring import ScoreResult, find_keywords, score_text


# ---------------------------------------------------------------------------
# find_keywords
# ---------------------------------------------------------------------------

class TestFindKeywords:
    def test_exact_match(self):
        assert find_keywords("поставка кондиционеров", ["кондиционер"]) != []

    def test_no_match(self):
        assert find_keywords("поставка мебели", ["кондиционер"]) == []

    def test_case_insensitive(self):
        assert find_keywords("Поставка КОНДИЦИОНЕРОВ", ["кондиционер"]) != []

    def test_multiple_keywords(self):
        result = find_keywords(
            "поставка кондиционеров и вентиляции",
            ["кондиционер", "вентиляция", "мебель"],
        )
        assert "кондиционер" in result or len(result) >= 1
        assert "мебель" not in result

    def test_empty_text(self):
        assert find_keywords("", ["кондиционер"]) == []

    def test_empty_keywords(self):
        assert find_keywords("любой текст", []) == []

    def test_deduplication(self):
        # Same keyword should appear only once even if found multiple times in text
        result = find_keywords("кондиционер кондиционер кондиционер", ["кондиционер"])
        assert result.count("кондиционер") == 1


# ---------------------------------------------------------------------------
# score_text
# ---------------------------------------------------------------------------

class TestScoreText:
    def test_no_keywords_match_returns_zero(self):
        result = score_text("поставка мебели", ["кондиционер"], [])
        assert result.score == Decimal("0.00")
        assert result.matched_keywords == []

    def test_single_keyword_match_nonzero(self):
        result = score_text("поставка кондиционеров", ["кондиционер"], [])
        assert result.score > Decimal("0")
        assert len(result.matched_keywords) >= 1

    def test_negative_keyword_blocks_match(self):
        result = score_text(
            "поставка кондиционеров бытовых",
            ["кондиционер"],
            ["бытовой"],
        )
        assert result.score == Decimal("0.00")
        assert result.matched_keywords == []

    def test_negative_keyword_not_present_allows_match(self):
        result = score_text(
            "поставка промышленных кондиционеров",
            ["кондиционер"],
            ["бытовой"],
        )
        assert result.score > Decimal("0")

    def test_score_increases_with_more_keywords(self):
        one = score_text("кондиционер вентиляция", ["кондиционер"], [])
        two = score_text("кондиционер вентиляция", ["кондиционер", "вентиляция"], [])
        assert two.score >= one.score

    def test_score_capped_at_100(self):
        # 10 keywords, score formula: min(100, count * 20)
        keywords = [f"слово{i}" for i in range(10)]
        text = " ".join(keywords)
        result = score_text(text, keywords, [])
        assert result.score <= Decimal("100")

    def test_empty_text_returns_zero(self):
        result = score_text("", ["кондиционер"], [])
        assert result.score == Decimal("0.00")

    def test_returns_score_result_type(self):
        result = score_text("текст", ["текст"], [])
        assert isinstance(result, ScoreResult)
        assert isinstance(result.score, Decimal)
