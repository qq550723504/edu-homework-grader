from __future__ import annotations

import pytest

from edu_grader_api.services import verification_capacity as capacity
from edu_grader_api.services.verification_capacity import evaluate_verification_capacity


def test_text_scan_budget_is_candidate_wide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = {
        "prompt": "bounded text scan",
        "wide_text": [
            "x" * capacity.MAX_CANDIDATE_BYTES,
            "y" * capacity.MAX_CANDIDATE_BYTES,
        ],
    }
    category_calls = 0
    real_category = capacity.unicodedata.category

    def counted_category(character: str) -> str:
        nonlocal category_calls
        category_calls += 1
        return real_category(character)

    monkeypatch.setattr(capacity.unicodedata, "category", counted_category)

    evaluation = evaluate_verification_capacity(candidate)

    assert evaluation.blocked is True
    assert "candidate_bytes" in evaluation.violations
    assert 0 < category_calls <= capacity._TEXT_SCAN_LIMIT
