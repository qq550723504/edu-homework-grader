from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


verification_path = Path("apps/api/src/edu_grader_api/services/question_verification.py")
verification = verification_path.read_text(encoding="utf-8")
verification = replace_once(
    verification,
    """from .grader import EmbeddingDependencyVersion, SemanticSimilarityResult
from .question_fingerprints import FINGERPRINT_VERSION, PromptFingerprints, fingerprint_prompt
""",
    """from .grader import EmbeddingDependencyVersion, SemanticSimilarityResult
from .objective_prerequisites import (
    evaluate_objective_prerequisite_alignment,
    unavailable_objective_prerequisite_signal,
)
from .question_fingerprints import FINGERPRINT_VERSION, PromptFingerprints, fingerprint_prompt
""",
    "prerequisite imports",
)
verification = replace_once(
    verification,
    'VALIDATOR_VERSION = "verification-v6"\nRULESET_VERSION = "rules-v6"',
    'VALIDATOR_VERSION = "verification-v7"\nRULESET_VERSION = "rules-v7"',
    "version bump",
)
verification = replace_once(
    verification,
    """    duplicate_feature_summary: dict[str, object]
    difficulty_signal: dict[str, object]
    grade_complexity_signal: dict[str, object]
""",
    """    duplicate_feature_summary: dict[str, object]
    difficulty_signal: dict[str, object]
    grade_complexity_signal: dict[str, object]
    objective_prerequisite_signal: dict[str, object]
""",
    "candidate evaluation signal",
)
verification = replace_once(
    verification,
    """            grade_complexity_signal=unavailable_grade_complexity_signal("validator_unavailable"),
        )
""",
    """            grade_complexity_signal=unavailable_grade_complexity_signal("validator_unavailable"),
            objective_prerequisite_signal=unavailable_objective_prerequisite_signal(
                "validator_unavailable"
            ),
        )
""",
    "validator unavailable signal",
)
verification = replace_once(
    verification,
    """        duplicate_feature_summary=evaluation.duplicate_feature_summary,
        difficulty_signal=evaluation.difficulty_signal,
        grade_complexity_signal=evaluation.grade_complexity_signal,
    )
""",
    """        duplicate_feature_summary=evaluation.duplicate_feature_summary,
        difficulty_signal=evaluation.difficulty_signal,
        grade_complexity_signal=evaluation.grade_complexity_signal,
        objective_prerequisite_signal=evaluation.objective_prerequisite_signal,
    )
""",
    "persist call signal",
)
verification = replace_once(
    verification,
    """    findings: list[VerificationFinding] = []
    grade_complexity_signal = unavailable_grade_complexity_signal("candidate_not_evaluated")

    if (
""",
    """    findings: list[VerificationFinding] = []
    grade_complexity_signal = unavailable_grade_complexity_signal("candidate_not_evaluated")
    objective_prerequisite_signal = unavailable_objective_prerequisite_signal(
        "candidate_not_evaluated"
    )

    if (
""",
    "candidate signal initialization",
)
verification = replace_once(
    verification,
    """    difficulty = candidate.get("difficulty")
""",
    """    prerequisite_evaluation = evaluate_objective_prerequisite_alignment(
        session,
        target_revision=revision,
        candidate_knowledge_point=candidate.get("knowledge_point"),
    )
    findings.extend(
        VerificationFinding(
            code=finding.code,
            severity=ValidationFindingSeverity(finding.severity),
            evidence=finding.evidence,
            remediation=finding.remediation,
        )
        for finding in prerequisite_evaluation.findings
    )
    objective_prerequisite_signal = prerequisite_evaluation.feature_summary()

    difficulty = candidate.get("difficulty")
""",
    "candidate prerequisite evaluation",
)
verification = replace_once(
    verification,
    """        grade_complexity_signal=grade_complexity_signal,
    )


def _m1_findings(
""",
    """        grade_complexity_signal=grade_complexity_signal,
        objective_prerequisite_signal=objective_prerequisite_signal,
    )


def _m1_findings(
""",
    "candidate evaluation return",
)
verification = replace_once(
    verification,
    """    duplicate_feature_summary: dict[str, object],
    difficulty_signal: dict[str, object],
    grade_complexity_signal: dict[str, object],
) -> GenerationValidationRun:
""",
    """    duplicate_feature_summary: dict[str, object],
    difficulty_signal: dict[str, object],
    grade_complexity_signal: dict[str, object],
    objective_prerequisite_signal: dict[str, object],
) -> GenerationValidationRun:
""",
    "persist signature",
)
verification = replace_once(
    verification,
    """            "difficulty_signal": difficulty_signal,
            "grade_complexity_signal": grade_complexity_signal,
            **duplicate_feature_summary,
""",
    """            "difficulty_signal": difficulty_signal,
            "grade_complexity_signal": grade_complexity_signal,
            "objective_prerequisite_signal": objective_prerequisite_signal,
            **duplicate_feature_summary,
""",
    "feature summary signal",
)
verification_path.write_text(verification, encoding="utf-8")


test_path = Path("apps/api/tests/test_question_verification.py")
tests = test_path.read_text(encoding="utf-8")
tests = tests.replace('"verification-v6"', '"verification-v7"')
tests = tests.replace('"rules-v6"', '"rules-v7"')
tests = tests.replace(
    '{"difficulty_signal", "grade_complexity_signal"}',
    '{"difficulty_signal", "grade_complexity_signal", "objective_prerequisite_signal"}',
)
if "def test_verification_persists_objective_prerequisite_signal" in tests:
    raise SystemExit("integration tests already present")
tests += r'''


def test_verification_persists_objective_prerequisite_signal(session: Session) -> None:
    draft = generation_draft(session)
    job = session.get(GenerationJob, draft.job_id)
    assert job is not None
    target_revision = job.curriculum_objective_revision
    target_revision.objective.knowledge_point = "whole-number addition"
    session.flush()

    run = verify_current_revision(session, draft=draft, grader_client=PassingGrader())

    signal = run.feature_summary_json["objective_prerequisite_signal"]
    assert signal == {
        "availability": "available",
        "version": "objective-prerequisite-v1",
        "target_objective_code": target_revision.objective.code,
        "resolution": "target",
        "candidate_alias_digest": signal["candidate_alias_digest"],
        "matched_objective_code": target_revision.objective.code,
        "prerequisite_depth": 0,
        "allowed_objective_count": 1,
        "prerequisite_revision_count": 0,
    }
    assert str(signal["candidate_alias_digest"]).startswith("sha256:")
    assert "whole-number addition" not in json.dumps(signal)


def test_verification_blocks_known_objective_outside_prerequisite_closure(
    session: Session,
) -> None:
    candidate = valid_m1_candidate("What is 2 + 2?")
    candidate["knowledge_point"] = "fraction division"
    draft = generation_draft(session, candidate_json=candidate)
    job = session.get(GenerationJob, draft.job_id)
    assert job is not None
    target_revision = job.curriculum_objective_revision
    target_revision.objective.knowledge_point = "whole-number addition"
    outside_objective = CurriculumObjective(
        profile=target_revision.objective.profile,
        grade_mapping=target_revision.objective.grade_mapping,
        code=f"MATH-G6-FRACTION-{uuid4()}",
        subject="mathematics",
        domain="number",
        knowledge_point="fraction division",
        status=CurriculumProfileStatus.ACTIVE,
    )
    outside_revision = CurriculumObjectiveRevision(
        objective=outside_objective,
        revision_number=1,
        text="Divide fractions.",
        source_locator="section outside",
        allowed_question_types=["M1"],
        difficulty_min=0,
        difficulty_max=1,
        activity_type=CurriculumActivityType.SCORED_QUESTION,
        status=CurriculumRevisionStatus.ACTIVE,
    )
    session.add(outside_revision)
    session.flush()

    run = verify_current_revision(session, draft=draft, grader_client=PassingGrader())

    finding = finding_by_code(run, "objective_prerequisite_out_of_scope")
    assert run.status is ValidationRunStatus.BLOCKED
    assert finding.severity.value == "blocked"
    assert finding.evidence_json["matched_objective_code"] == outside_objective.code
    assert finding.evidence_json["ruleset_version"] == "objective-prerequisite-v1"
    assert "fraction division" not in json.dumps(finding.evidence_json)
'''
test_path.write_text(tests, encoding="utf-8")
