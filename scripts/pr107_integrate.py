#!/usr/bin/env python3
"""One-shot integration script for PR #107; removed before the branch is reviewable."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def integrate_verifier() -> None:
    path = ROOT / "apps/api/src/edu_grader_api/services/question_verification.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .grader import EmbeddingDependencyVersion, SemanticSimilarityResult\n"
        "from .objective_prerequisites import (",
        "from .grader import EmbeddingDependencyVersion, SemanticSimilarityResult\n"
        "from .math_semantics import evaluate_math_semantics, unavailable_math_semantics_signal\n"
        "from .objective_prerequisites import (",
        "math semantics import",
    )
    text = replace_once(
        text,
        'VALIDATOR_VERSION = "verification-v7"\nRULESET_VERSION = "rules-v7"',
        'VALIDATOR_VERSION = "verification-v8"\nRULESET_VERSION = "rules-v8"',
        "verification version",
    )
    text = replace_once(
        text,
        "    grade_complexity_signal: dict[str, object]\n"
        "    objective_prerequisite_signal: dict[str, object]\n",
        "    grade_complexity_signal: dict[str, object]\n"
        "    objective_prerequisite_signal: dict[str, object]\n"
        "    math_semantics_signal: dict[str, object]\n",
        "candidate evaluation field",
    )
    text = replace_once(
        text,
        "            objective_prerequisite_signal=unavailable_objective_prerequisite_signal(\n"
        '                "validator_unavailable"\n'
        "            ),\n",
        "            objective_prerequisite_signal=unavailable_objective_prerequisite_signal(\n"
        '                "validator_unavailable"\n'
        "            ),\n"
        "            math_semantics_signal=unavailable_math_semantics_signal(\n"
        '                "validator_unavailable"\n'
        "            ),\n",
        "validator unavailable signal",
    )
    text = replace_once(
        text,
        "        grade_complexity_signal=evaluation.grade_complexity_signal,\n"
        "        objective_prerequisite_signal=evaluation.objective_prerequisite_signal,\n",
        "        grade_complexity_signal=evaluation.grade_complexity_signal,\n"
        "        objective_prerequisite_signal=evaluation.objective_prerequisite_signal,\n"
        "        math_semantics_signal=evaluation.math_semantics_signal,\n",
        "persist invocation",
    )
    text = replace_once(
        text,
        "    objective_prerequisite_signal = unavailable_objective_prerequisite_signal(\n"
        '        "candidate_not_evaluated"\n'
        "    )\n",
        "    objective_prerequisite_signal = unavailable_objective_prerequisite_signal(\n"
        '        "candidate_not_evaluated"\n'
        "    )\n"
        "    math_semantics_signal = unavailable_math_semantics_signal(\n"
        '        "candidate_not_evaluated"\n'
        "    )\n",
        "signal initialization",
    )
    text = replace_once(
        text,
        '    policy_version = candidate.get("policy_version")\n'
        '    rule_json = candidate.get("rule_json")\n'
        "    policy_errors = (\n",
        '    policy_version = candidate.get("policy_version")\n'
        '    rule_json = candidate.get("rule_json")\n'
        "    math_semantics_evaluation = evaluate_math_semantics(\n"
        "        question_type=question_type,\n"
        "        policy_version=policy_version,\n"
        "        rule_json=rule_json,\n"
        "    )\n"
        "    findings.extend(\n"
        "        VerificationFinding(\n"
        "            code=finding.code,\n"
        "            severity=ValidationFindingSeverity.BLOCKED,\n"
        "            evidence=finding.evidence,\n"
        "            remediation=finding.remediation,\n"
        "        )\n"
        "        for finding in math_semantics_evaluation.findings\n"
        "    )\n"
        "    math_semantics_signal = math_semantics_evaluation.feature_summary()\n"
        "    math_semantics_blocked = bool(math_semantics_evaluation.findings)\n"
        "    policy_errors = (\n",
        "semantics evaluation",
    )
    text = replace_once(
        text,
        '    if question_type == "M2" and isinstance(rule_json, dict) and not policy_errors:\n',
        "    if (\n"
        '        question_type == "M2"\n'
        "        and isinstance(rule_json, dict)\n"
        "        and not policy_errors\n"
        "        and not math_semantics_blocked\n"
        "    ):\n",
        "M2 semantics gate",
    )
    text = replace_once(
        text,
        "    if not policy_errors and isinstance(rule_json, dict) and isinstance(prompt, str):\n",
        "    if (\n"
        "        not policy_errors\n"
        "        and not math_semantics_blocked\n"
        "        and isinstance(rule_json, dict)\n"
        "        and isinstance(prompt, str)\n"
        "    ):\n",
        "complexity semantics gate",
    )
    text = replace_once(
        text,
        '    if question_type == "M1" and isinstance(rule_json, dict) and not policy_errors:\n',
        "    if (\n"
        '        question_type == "M1"\n'
        "        and isinstance(rule_json, dict)\n"
        "        and not policy_errors\n"
        "        and not math_semantics_blocked\n"
        "    ):\n",
        "M1 semantics gate",
    )
    text = replace_once(
        text,
        "        grade_complexity_signal=grade_complexity_signal,\n"
        "        objective_prerequisite_signal=objective_prerequisite_signal,\n"
        "    )\n",
        "        grade_complexity_signal=grade_complexity_signal,\n"
        "        objective_prerequisite_signal=objective_prerequisite_signal,\n"
        "        math_semantics_signal=math_semantics_signal,\n"
        "    )\n",
        "candidate evaluation return",
    )
    text = replace_once(
        text,
        "    grade_complexity_signal: dict[str, object],\n"
        "    objective_prerequisite_signal: dict[str, object],\n"
        ") -> GenerationValidationRun:\n",
        "    grade_complexity_signal: dict[str, object],\n"
        "    objective_prerequisite_signal: dict[str, object],\n"
        "    math_semantics_signal: dict[str, object],\n"
        ") -> GenerationValidationRun:\n",
        "persist signature",
    )
    text = replace_once(
        text,
        '            "grade_complexity_signal": grade_complexity_signal,\n'
        '            "objective_prerequisite_signal": objective_prerequisite_signal,\n'
        "            **duplicate_feature_summary,\n",
        '            "grade_complexity_signal": grade_complexity_signal,\n'
        '            "objective_prerequisite_signal": objective_prerequisite_signal,\n'
        '            "math_semantics_signal": math_semantics_signal,\n'
        "            **duplicate_feature_summary,\n",
        "persist feature summary",
    )
    path.write_text(text, encoding="utf-8")


def integrate_tests() -> None:
    path = ROOT / "apps/api/tests/test_question_verification.py"
    tests = path.read_text(encoding="utf-8")
    tests = tests.replace('"verification-v7"', '"verification-v8"')
    tests = tests.replace('"rules-v7"', '"rules-v8"')
    tests = tests.replace(
        '"objective_prerequisite_signal"}',
        '"objective_prerequisite_signal", "math_semantics_signal"}',
    )
    marker = "def test_verification_persists_supported_math_semantics_signal"
    if marker in tests:
        raise SystemExit("integration tests already present")
    tests += r'''


def test_verification_persists_supported_math_semantics_signal(session: Session) -> None:
    draft = generation_draft(session)

    run = verify_current_revision(session, draft=draft, grader_client=PassingGrader())

    assert run.feature_summary_json["math_semantics_signal"] == {
        "availability": "available",
        "version": "math-semantics-v1",
        "question_type": "M1",
        "policy_version": "1",
        "support_status": "supported",
        "semantic_class": "single_numeric_value",
        "trigger_operator": None,
    }
    assert run.validator_version == "verification-v8"
    assert run.ruleset_version == "rules-v8"


def test_verification_blocks_equation_semantics_before_m2_grader(
    session: Session,
) -> None:
    candidate = valid_m2_candidate()
    candidate["rule_json"] = {
        **candidate["rule_json"],
        "expected": ["Equal", "x", 2],
    }
    draft = generation_draft(
        session,
        allowed_question_types=["M2"],
        candidate_json=candidate,
    )
    grader = PassingM2Grader()

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    finding = finding_by_code(run, "m2_equation_semantics_unsupported")
    assert run.status is ValidationRunStatus.BLOCKED
    assert finding.evidence_json == {
        "ruleset_version": "math-semantics-v1",
        "question_type": "M2",
        "policy_version": "2",
        "semantic_class": "equation_or_inequality",
        "trigger_operator": "Equal",
    }
    assert grader.normalization_requests == []
    assert grader.grade_requests == []
    assert "x" not in json.dumps(finding.evidence_json)


def test_verification_blocks_m1_multiple_solution_semantics_before_grader(
    session: Session,
) -> None:
    candidate = valid_m1_candidate("Give all valid values.")
    candidate["rule_json"] = {"expected": [2, 4], "tolerance": 0}
    grader = RecordingM1Grader()
    draft = generation_draft(session, candidate_json=candidate)

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    finding = finding_by_code(run, "m1_multiple_solution_semantics_unsupported")
    assert run.status is ValidationRunStatus.BLOCKED
    assert finding.evidence_json["semantic_class"] == "multiple_solution_set"
    assert grader.grade_requests == []
'''
    path.write_text(tests, encoding="utf-8")


def synchronize_docs() -> None:
    path = ROOT / "docs/status-evidence.json"
    evidence = json.loads(path.read_text(encoding="utf-8"))
    contract = evidence["generation_contract"]
    contract["validator_version"] = "verification-v8"
    contract["ruleset_version"] = "rules-v8"
    contract["math_semantics_rules_version"] = "math-semantics-v1"
    path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    path = ROOT / "docs/project-status.md"
    status = path.read_text(encoding="utf-8")
    status = status.replace("`verification-v7`", "`verification-v8`")
    status = status.replace("`rules-v7`", "`rules-v8`")
    status = status.replace(
        "| Objective prerequisite rules | `objective-prerequisite-v1` |",
        "| Objective prerequisite rules | `objective-prerequisite-v1` |\n"
        "| Math semantics rules | `math-semantics-v1` |",
    )
    status = status.replace(
        "验证器已加入版本化年级复杂度以及 Objective prerequisite 图门禁",
        "验证器已加入版本化年级复杂度、Objective prerequisite 图门禁和显式数学语义支持矩阵",
    )
    status = status.replace(
        "未经审核直接发布仍禁止；数学语义边界、容量 SLO、正式阈值、生产报告和发布环境验收仍缺",
        "未经审核直接发布仍禁止；容量 SLO、正式阈值、生产报告和发布环境验收仍缺",
    )
    status = status.replace(
        "| #83 | 开放：年级复杂度和 Objective prerequisite 门禁已实现；仍缺数学语义和容量边界。 |",
        "| #83 | 开放：年级复杂度、Objective prerequisite 与数学语义门禁已实现；仍缺容量边界。 |",
    )
    status = status.replace("#83 数学语义/容量边界 ─┐", "#83 验证容量边界 ─────┐")
    path.write_text(status, encoding="utf-8")

    path = ROOT / "docs/roadmap.md"
    roadmap = path.read_text(encoding="utf-8")
    old = "- [ ] #83：剩余 Objective prerequisite、数学多解/定义域/增根漏根语义和容量 SLO；"
    new = (
        "- [x] PR #105：`objective-prerequisite-v1` 传递先修图门禁与 `verification-v7` / `rules-v7`；\n"
        "- [x] PR #107 / #106：`math-semantics-v1` 显式支持矩阵与专用阻断门禁；\n"
        "- [ ] #83：剩余验证容量、超时和 P95 SLO；"
    )
    roadmap = replace_once(roadmap, old, new, "roadmap implementation status")
    roadmap = replace_once(
        roadmap,
        "#83 课程/数学语义边界 ─┐",
        "#83 验证容量边界 ─────┐",
        "roadmap dependency label",
    )
    path.write_text(roadmap, encoding="utf-8")


if __name__ == "__main__":
    integrate_verifier()
    integrate_tests()
    synchronize_docs()
