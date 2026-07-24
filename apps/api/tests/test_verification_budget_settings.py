from __future__ import annotations

import pytest
from pydantic import ValidationError

from edu_grader_api.settings import Settings


def test_verification_total_timeout_default_is_bounded() -> None:
    configured = Settings(_env_file=None)

    assert configured.verification_total_timeout_seconds == 30.0


@pytest.mark.parametrize("value", [0, -1, 121, float("inf"), float("nan")])
def test_verification_total_timeout_rejects_invalid_values(value: float) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            verification_total_timeout_seconds=value,
        )


def test_verification_total_timeout_accepts_release_range() -> None:
    assert (
        Settings(
            _env_file=None,
            verification_total_timeout_seconds=45,
        ).verification_total_timeout_seconds
        == 45
    )
