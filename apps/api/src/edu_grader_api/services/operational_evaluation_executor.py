from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

from ..db import SessionLocal
from ..settings import settings
from .ai_evaluation_operational import (
    OperationalEvaluationSpec,
    run_operational_evaluation,
    signed_operational_evaluation_evidence,
)

_FORBIDDEN_KEYS = frozenset({"records", "candidate_json", "prompt"})


def _contains_raw_data(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            key.casefold() in _FORBIDDEN_KEYS or _contains_raw_data(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_raw_data(item) for item in value)
    return False


def build_signed_report(spec_json: str) -> dict[str, object]:
    spec = OperationalEvaluationSpec.model_validate_json(spec_json)
    with SessionLocal() as session:
        _exported, report = run_operational_evaluation(session, spec)
    evidence = signed_operational_evaluation_evidence(
        report, hmac_key=settings.evaluation_evidence_hmac_key
    )
    if _contains_raw_data(evidence):
        raise ValueError("raw evaluation data must not leave the executor")
    return evidence


def post_completion(*, callback_url: str, callback_token: str, payload: dict[str, object]) -> None:
    response = httpx.post(
        callback_url,
        headers={"X-Operational-Evaluation-Callback": callback_token},
        json=payload,
        timeout=15,
    )
    response.raise_for_status()


def run_executor(
    *, spec_json: str, callback_url: str, callback_token: str, output_dir: Path
) -> int:
    try:
        evidence = build_signed_report(spec_json)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "report.json").write_text(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        post_completion(
            callback_url=callback_url,
            callback_token=callback_token,
            payload={"report": evidence},
        )
        return 0
    except Exception:  # noqa: BLE001 - report a bounded failure without leaking evaluation input
        try:
            post_completion(
                callback_url=callback_url,
                callback_token=callback_token,
                payload={"failure_code": "evaluation_execution_failed"},
            )
        except Exception:  # noqa: BLE001 - the original executor failure remains the job outcome
            return 1
        return 1


def main() -> int:
    required = {
        "spec_json": os.environ.get("OPERATIONAL_EVALUATION_SPEC_JSON", ""),
        "callback_url": os.environ.get("OPERATIONAL_EVALUATION_CALLBACK_URL", ""),
        "callback_token": os.environ.get("OPERATIONAL_EVALUATION_CALLBACK_TOKEN", ""),
    }
    if any(not value for value in required.values()):
        return 1
    return run_executor(
        spec_json=required["spec_json"],
        callback_url=required["callback_url"],
        callback_token=required["callback_token"],
        output_dir=Path("/tmp/operational-evaluation"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
