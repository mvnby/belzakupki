"""Keyword scoring for tender texts.

Uses morphological normalisation (pymorphy3 if available, plain casefold
otherwise) so that keywords like "кондиционер" match inflected forms such
as "кондиционеров", "кондиционировании", "кондиционирование".
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re

from worker.morphology import normalise_for_matching


@dataclass(frozen=True)
class ScoreResult:
    score: Decimal
    matched_keywords: list[str]
    reason: str | None = None


def find_keywords(text: str, keywords: list[str]) -> list[str]:
    """Return keywords (original form) found in *text* after normalisation."""
    normalised_text = normalise_for_matching(text)
    matched: list[str] = []

    for keyword in keywords:
        normalised_keyword = normalise_for_matching(keyword)
        if normalised_keyword and normalised_keyword in normalised_text:
            matched.append(keyword)

    return sorted(set(matched), key=matched.index)


def score_text(
    text: str,
    keywords: list[str],
    negative_keywords: list[str],
) -> ScoreResult:
    negative_matches = find_keywords(text, negative_keywords)

    if negative_matches:
        return ScoreResult(
            score=Decimal("0.00"),
            matched_keywords=[],
            reason="Excluded by negative keywords: " + ", ".join(negative_matches),
        )

    matched_keywords = find_keywords(text, keywords)

    if not matched_keywords:
        return ScoreResult(
            score=Decimal("0.00"),
            matched_keywords=[],
            reason="No matching keywords",
        )

    score = min(100, len(matched_keywords) * 20)

    return ScoreResult(
        score=Decimal(score).quantize(Decimal("0.01")),
        matched_keywords=matched_keywords,
        reason="Matched keywords: " + ", ".join(matched_keywords),
    )
