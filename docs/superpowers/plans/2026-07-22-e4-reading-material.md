# E4 Generated Reading Material Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Require every E4@2 generated candidate to contain a bounded passage that deterministically contains every rubric evidence phrase before verification can pass.

**Architecture:** The shared Pydantic candidate contract gains an E4-only reading_material field. Fake and OpenAI provider output continue to use that one contract and existing candidate JSON persistence and teacher payloads remain unchanged. Core API safety-scans the passage and adds deterministic fail-closed grounding gates before the existing isolated E4 Grader probes.

**Tech Stack:** Python 3.12+, Pydantic v2, FastAPI, SQLAlchemy 2, pytest, Ruff, OpenAI Responses structured output.

## Global Constraints

- reading_material is generated candidate data only. Do not add it to GenerationRequest, a database column, migration, Grader request, log, or validation finding.
- The nullable top-level field is at most 8,000 characters. Only E4 may set it; E4 requires a nonblank value after trimming.
- Normalize material and phrases with existing _normalize_e2_form: NFKC, whitespace collapse, case-folding, and terminal-punctuation removal.
- Material failures are blocked, expose only specified counts/reason/probe, and must make zero Grader calls.
- Do not backfill legacy drafts; legacy E4 revalidation without material blocks.
- Preserve E4@2 policy, isolated point probing, needs_review requirement, teacher confirmation, publication, and assignment behavior.

---

## File Structure

- Modify: services/generator/src/edu_generator/contracts.py — strict candidate property and question-type invariant.
- Modify: services/generator/src/edu_generator/providers.py — deterministic Fake Provider E4 passage.
- Modify: services/generator/tests/test_contracts.py — contract, JSON-schema, and Fake Provider regressions.
- Modify: apps/api/src/edu_grader_api/services/question_verification.py — material safety scan and fail-closed E4 grounding.
- Modify: apps/api/tests/test_generation_service.py — candidate JSON persistence and content hash.
- Modify: apps/api/tests/test_ai_question_generation_api.py — teacher payload round-trip.
- Modify: apps/api/tests/test_question_verification.py — material behavior, safety, no-Grader calls, and legacy candidates.

### Task 1: Add the strict E4-only candidate material contract

**Files:**
- Modify: services/generator/src/edu_generator/contracts.py:5-69
- Modify: services/generator/src/edu_generator/providers.py:20-47
- Modify: services/generator/tests/test_contracts.py:1-46

**Interfaces:**
- Consumes: QuestionType and GeneratedCandidate validation.
- Produces: GeneratedCandidate.reading_material: str | None and FakeGenerationProvider candidates whose E4 material contains complete response.

- [x] **Step 1: Write failing contract, schema, and provider tests**

~~~python
from pydantic import ValidationError
from edu_generator.contracts import GeneratedCandidate, ProviderCandidatePayload

def test_generated_candidate_requires_material_only_for_e4() -> None:
    base = {
        "objective_revision_id": str(uuid4()), "policy_version": "2",
        "prompt": "Read and answer.", "rule_json": {"scoring_points": []},
        "explanation": "Explain.", "knowledge_point": "reading", "difficulty": 0.5,
    }
    assert GeneratedCandidate.model_validate(
        {**base, "question_type": "E4", "reading_material": "A complete response."}
    ).reading_material == "A complete response."
    with pytest.raises(ValidationError):
        GeneratedCandidate.model_validate({**base, "question_type": "E4"})
    with pytest.raises(ValidationError):
        GeneratedCandidate.model_validate(
            {**base, "question_type": "M1", "reading_material": "A passage."}
        )

def test_responses_schema_exposes_nullable_reading_material() -> None:
    candidate = ProviderCandidatePayload.model_json_schema()["$defs"]["GeneratedCandidate"]
    assert candidate["properties"]["reading_material"]["anyOf"][1] == {"type": "null"}
    assert candidate["properties"]["reading_material"]["maxLength"] == 8_000

def test_fake_provider_emits_only_e4_reading_material() -> None:
    result = FakeGenerationProvider(seed=7).generate(request_with_m1_and_e4())
    assert result.candidates[0].reading_material is None
    assert "complete response" in (result.candidates[1].reading_material or "")
~~~

- [x] **Step 2: Run the Generator contract tests to verify failure**

Run: python -m pytest services/generator/tests/test_contracts.py -q

Expected: FAIL because GeneratedCandidate has no reading_material and Fake Provider omits it.

- [x] **Step 3: Implement the shared invariant and Fake output**

~~~python
# contracts.py
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

class GeneratedCandidate(BaseModel):
    # existing fields unchanged
    reading_material: str | None = Field(default=None, max_length=8_000)

    @model_validator(mode="after")
    def _validate_reading_material(self) -> "GeneratedCandidate":
        if self.question_type == "E4":
            if self.reading_material is None or not self.reading_material.strip():
                raise ValueError("E4 candidates require nonblank reading_material")
        elif self.reading_material is not None:
            raise ValueError("only E4 candidates may include reading_material")
        return self

# providers.py, in each candidate payload
"reading_material": (
    "The student gave a complete response about the practice item."
    if question_type == "E4"
    else None
),
~~~

Keep the Responses schema sourced only from ProviderCandidatePayload.model_json_schema(); do not add an OpenAI-only schema.

- [x] **Step 4: Run focused Generator tests to verify success**

Run: python -m pytest services/generator/tests/test_contracts.py -q

Expected: PASS, including strict E4 acceptance/rejection, 8,000-character schema bound, and deterministic Fake output.

- [x] **Step 5: Commit the generator contract slice**

~~~bash
git add services/generator/src/edu_generator/contracts.py services/generator/src/edu_generator/providers.py services/generator/tests/test_contracts.py
git commit -m "feat: require generated E4 reading material"
~~~

### Task 2: Prove existing persistence and teacher payload boundaries carry material

**Files:**
- Modify: apps/api/tests/test_generation_service.py:120-155
- Modify: apps/api/tests/test_ai_question_generation_api.py:100-145

**Interfaces:**
- Consumes: GeneratedCandidate.model_dump(mode="json"), existing _persist_valid_candidates(), and ai_question_generation._draft_payload() returning draft.candidate_json as candidate.
- Produces: regression proof that no persistence/route/schema code is required; E4 material is part of immutable candidate JSON and content hash.

- [x] **Step 1: Write failing persistence and teacher-payload tests**

~~~python
def test_e4_material_is_persisted_and_part_of_candidate_hash(session: Session) -> None:
    teacher, revision = teacher_and_e4_objective(session)
    job = create_or_get_job(session, request=e4_generation_request(revision), actor=teacher)
    run_generation_job(session, job=job, provider=FakeGenerationProvider(seed=7))

    draft = job.drafts[0]
    assert draft.candidate_json["reading_material"]
    assert draft.content_hash == _content_hash(draft.candidate_json)

def test_teacher_question_list_returns_e4_reading_material(
    client: TestClient, session: Session
) -> None:
    response = create_and_fetch_e4_draft(client, session)
    assert response.status_code == 200
    assert response.json()["items"][0]["candidate"]["reading_material"]
~~~

Create local test helpers that mirror the current M1 setup but use allowed_question_types=["E4"] and question_types=["E4"]. Do not change endpoint shapes.

- [x] **Step 2: Run persistence/payload tests to verify failure**

Run: python -m pytest apps/api/tests/test_generation_service.py apps/api/tests/test_ai_question_generation_api.py -q

Expected: FAIL because the current Fake Provider does not generate material.

- [x] **Step 3: Keep production persistence and routing unchanged**

~~~python
# Existing production data path remains the only one:
content = candidate.model_dump(mode="json")   # generation.py
"candidate": draft.candidate_json             # ai_question_generation.py
~~~

Adjust only test fixtures needed to request E4. Confirm stored candidate JSON includes material, the existing content hash reflects complete JSON, and the authenticated teacher list response exposes the existing candidate envelope. Do not add a migration, route, column, public response field, or material log.

- [x] **Step 4: Run persistence/payload tests to verify success**

Run: python -m pytest apps/api/tests/test_generation_service.py apps/api/tests/test_ai_question_generation_api.py -q

Expected: PASS; material survives provider validation, persistence, hashing, and teacher-scoped retrieval.

- [x] **Step 5: Commit the API boundary regression tests**

~~~bash
git add apps/api/tests/test_generation_service.py apps/api/tests/test_ai_question_generation_api.py
git commit -m "test: cover E4 reading material persistence"
~~~

### Task 3: Fail closed when E4 evidence cannot be grounded in material

**Files:**
- Modify: apps/api/src/edu_grader_api/services/question_verification.py:184-216,516-609
- Modify: apps/api/tests/test_question_verification.py:270-285,662-823

**Interfaces:**
- Consumes: candidate["reading_material"], _normalize_e2_form(value: str), _safety_findings(), and VerificationGraderClient.grade().
- Produces: _e4_findings(rule_json, policy_version, reading_material, grader_client) with validity and literal-grounding gates before E4 probes.

- [x] **Step 1: Write failing E4 material verification tests**

~~~python
def test_e4_missing_or_oversized_material_blocks_without_grader_calls(session: Session) -> None:
    for material, reason in [
        (None, "missing_or_blank"), (" " * 2, "missing_or_blank"), ("x" * 8_001, "too_long")
    ]:
        candidate = valid_e4_candidate()
        if material is None:
            candidate.pop("reading_material")
        else:
            candidate["reading_material"] = material
        grader = PassingE4Grader()
        run = verification.run_candidate_verification(
            session,
            draft=generation_draft(
                session, allowed_question_types=["E4"], candidate_json=candidate
            ),
            grader_client=grader,
        )
        finding = next(item for item in run.findings if item.code == "e4_reading_material_invalid")
        assert finding.evidence_json == {
            "reason": reason, "scoring_point_count": 2, "evidence_phrase_count": 2
        }
        assert grader.grade_requests == []

def test_e4_material_mismatch_blocks_before_grader_and_never_echoes_text(
    session: Session,
) -> None:
    candidate = valid_e4_candidate()
    candidate["reading_material"] = "The road was open, and the students arrived early."
    grader = PassingE4Grader()
    run = verification.run_candidate_verification(
        session,
        draft=generation_draft(session, allowed_question_types=["E4"], candidate_json=candidate),
        grader_client=grader,
    )
    finding = next(item for item in run.findings if item.code == "e4_evidence_material_mismatch")
    assert finding.evidence_json == {
        "probe": "reading_material", "scoring_point_count": 2, "evidence_phrase_count": 2
    }
    assert grader.grade_requests == []
    assert "road was open" not in finding.remediation

def test_e4_normalized_material_match_and_material_safety_scan(session: Session) -> None:
    candidate = valid_e4_candidate()
    candidate["reading_material"] = "BECAUSE the bridge was closed.  THEY arrived late!"
    assert verification.run_candidate_verification(
        session,
        draft=generation_draft(session, allowed_question_types=["E4"], candidate_json=candidate),
        grader_client=PassingE4Grader(),
    ).status is ValidationRunStatus.PASSED

    candidate["reading_material"] = "self-harm instructions"
    unsafe = verification.run_candidate_verification(
        session,
        draft=generation_draft(session, allowed_question_types=["E4"], candidate_json=candidate),
        grader_client=PassingE4Grader(),
    )
    assert next(item for item in unsafe.findings if item.code == "unsafe_minor_content").evidence_json == {
        "category": "self_harm"
    }
~~~

Update valid_e4_candidate() to supply “Because the bridge was closed, they arrived late.” so existing E4 tests remain focused. Add one legacy persisted E4 candidate without this key: it must block with missing_or_blank and zero Grader calls.

- [x] **Step 2: Run the E4 verifier tests to verify failure**

Run: python -m pytest apps/api/tests/test_question_verification.py -q

Expected: FAIL because _evaluate_candidate() neither safety-scans material nor passes it to _e4_findings().

- [x] **Step 3: Implement safety and grounding gates before E4 probes**

~~~python
# _evaluate_candidate(), alongside current text safety inputs
reading_material = candidate.get("reading_material")
findings.extend(
    _safety_findings(
        prompt if isinstance(prompt, str) else "",
        explanation if isinstance(explanation, str) else "",
        reading_material if isinstance(reading_material, str) else "",
        *(_text_values(rule_json) if isinstance(rule_json, dict) else []),
    )
)
if question_type == "E4" and isinstance(rule_json, dict) and not policy_errors:
    findings.extend(_e4_findings(rule_json, policy_version, reading_material, grader_client))

# exact helper signature
def _e4_findings(
    rule_json: dict[str, object],
    policy_version: object,
    reading_material: object,
    grader_client: VerificationGraderClient,
) -> list[VerificationFinding]:
~~~

After the existing deterministic rubric validity, duplicate, overlap, and finite score checks, but before the first point probe, add:

~~~python
if not isinstance(reading_material, str) or not reading_material.strip():
    return [_blocked(
        "e4_reading_material_invalid",
        {"reason": "missing_or_blank", "scoring_point_count": point_count,
         "evidence_phrase_count": len(evidence_phrases)},
        "Generate a non-empty reading passage for this E4 candidate.",
    )]
if len(reading_material) > 8_000:
    return [_blocked(
        "e4_reading_material_invalid",
        {"reason": "too_long", "scoring_point_count": point_count,
         "evidence_phrase_count": len(evidence_phrases)},
        "Generate a reading passage within the supported length.",
    )]
normalized_material = _normalize_e2_form(reading_material)
if any(_normalize_e2_form(phrase) not in normalized_material for phrase in evidence_phrases):
    return [_blocked(
        "e4_evidence_material_mismatch",
        {"probe": "reading_material", "scoring_point_count": point_count,
         "evidence_phrase_count": len(evidence_phrases)},
        "Regenerate the candidate so each rubric phrase occurs in its reading passage.",
    )]
~~~

Do not include material, phrases, point identifiers, offsets, or snippets in findings. Do not pass material to grader_client.grade().

- [x] **Step 4: Run focused and complete regression suites**

Run:

~~~bash
python -m pytest services/generator/tests/test_contracts.py -q
python -m pytest apps/api/tests/test_generation_service.py apps/api/tests/test_ai_question_generation_api.py apps/api/tests/test_question_verification.py -q
python -m pytest packages/processor-policy/tests services/generator/tests apps/api/tests services/grader/tests -q
python -m ruff check services/generator apps/api
python -m ruff format --check services/generator apps/api
git diff --check
~~~

Expected: every command exits 0; malformed, legacy, and mismatched material blocks without Grader calls while normalized grounded material retains existing isolated E4 probes.

- [x] **Step 5: Commit the verification slice**

~~~bash
git add apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_question_verification.py
git commit -m "feat: verify E4 evidence against reading material"
~~~

### Task 4: Review-ready integration and documentation confirmation

**Files:**
- Modify: docs/superpowers/specs/2026-07-22-e4-reading-material-design.md only if implementation reveals a factual mismatch; otherwise leave it unchanged.
- Modify: docs/superpowers/plans/2026-07-22-e4-reading-material.md only to check completed boxes during execution.

**Interfaces:**
- Consumes: the three completed slices and test results.
- Produces: a review-ready branch with no unintended API, migration, or Grader-request changes.

- [x] **Step 1: Verify architectural boundaries by diff**

Run:

~~~bash
git diff origin/main...HEAD -- apps/api/alembic apps/api/src/edu_grader_api/routers services/grader
git diff --check
git status --short
~~~

Expected: no migration, no Grader-service change, and no new external/public route. Router changes, if any, are test-only.

- [x] **Step 2: Review documented invariants**

~~~bash
rg -n "reading_material|e4_reading_material_invalid|e4_evidence_material_mismatch" services/generator apps/api
~~~

Expected: shared contract and Fake Provider contain the field; material stays in candidate JSON/payloads; both block codes use only sanitized reason/probe/counts.

- [x] **Step 3: Commit only a changed plan/spec**

~~~bash
git add docs/superpowers/plans/2026-07-22-e4-reading-material.md docs/superpowers/specs/2026-07-22-e4-reading-material-design.md
git commit -m "docs: record E4 reading material verification"
~~~

Run this command only if documentation changed after the initial spec commit; never make an empty commit.

## Self-Review

- Spec coverage: Task 1 covers contract, Responses schema, and Fake Provider. Task 2 proves persistence, hashing, and teacher payload. Task 3 covers safety, normalized grounding, sanitized blocked evidence, zero Grader calls, legacy candidates, and preserved E4 probes. Task 4 verifies no migrations, public routes, or Grader boundary changes.
- Placeholder scan: no unfilled work item, deferred implementation, or unspecified test command remains.
- Type consistency: reading_material: str | None travels from JSON storage as object to _e4_findings, which validates it before calling _normalize_e2_form(str).
