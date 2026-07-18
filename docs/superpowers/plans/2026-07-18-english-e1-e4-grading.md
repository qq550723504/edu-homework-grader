# English E1-E4 Grading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Deliver reproducible E1-E4 English grading with deterministic automatic outcomes, self-hosted grammar feedback, review-only reading signals, immutable grading evidence, and calibration reporting.

**Architecture:** The Grader evaluates de-identified English rules and answers; it owns deterministic E1/E2 rules plus LanguageTool and local-embedding adapters. The API validates versioned policies, sends submissions to the Grader, stores immutable runs/signals, and exposes teacher-only evidence. Compose runs LanguageTool privately and the Grader never sends student text to public NLP services.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic, SQLAlchemy 2, Alembic, PostgreSQL/SQLite tests, httpx, jsonschema, Docker Compose, LanguageTool, sentence-transformers.

## Global Constraints

- Preserve existing E1@1/E4@1 behavior. Add E1@2, E2@1, E3@1, and E4@2 only.
- Only teacher-authored accepted answers and scoring-point evidence can grant automatic English credit.
- LanguageTool and similarity are feedback/review signals; neither can independently decide correctness.
- Every E4 result is \`needs_review\` with \`requires_review=true\`. Similarity without evidence-point match yields zero provisional score.
- Persist rule/answer snapshots, policy and dependency versions, thresholds, criteria, feedback, and dependency errors.
- Dependency failures become explicit review results, never automatic rejections.
- Run test-first red-green-refactor for every task; format changed Python files with Ruff.

---

## File Structure

| Path | Responsibility |
| --- | --- |
| \`services/grader/src/edu_grader/english.py\` | Pure normalization, E1/E2 contracts, deterministic criteria. |
| \`services/grader/src/edu_grader/english_dependencies.py\` | LanguageTool and local embedding adapters. |
| \`services/grader/src/edu_grader/english_orchestrator.py\` | E3/E4 orchestration and E4 review invariant. |
| \`apps/api/src/edu_grader_api/policies.py\` | E1@2, E2@1, E3@1, E4@2 schemas. |
| \`apps/api/src/edu_grader_api/services/grader.py\` | Complete HTTP Grader request/response mapping. |
| \`apps/api/src/edu_grader_api/models.py\` | Immutable \`GradingRun\` and \`GradingSignal\` records. |
| \`apps/api/alembic/versions/0004_english_grading_runs.py\` | Run/signal schema migration. |
| \`apps/api/src/edu_grader_api/services/assignments.py\` | Submission-time grading and receipt response. |
| \`apps/api/src/edu_grader_api/routers/assignments.py\` | Student-safe response and teacher evidence route. |
| \`infra/languagetool/Dockerfile\` | Private pinned LanguageTool image. |
| \`services/grader/scripts/prefetch_english_model.py\` | Build-time model snapshot verifier. |
| \`services/grader/src/edu_grader/calibration.py\` | JSONL validation and metrics. |

## Task 1: Add versioned English policy schemas and publication gates

**Files:**
- Modify: \`apps/api/src/edu_grader_api/policies.py\`
- Modify: \`apps/api/src/edu_grader_api/services/questions.py:333-341\`
- Create: \`apps/api/tests/test_english_policies.py\`

**Interfaces:** Adds \`POLICY_SCHEMAS[("E1", "2")]\`, \`("E2", "1")\`, \`("E3", "1")\`, \`("E4", "2")\`, and the relevant required test categories.

- [ ] **Step 1: Write the failing schema tests**

\`\`\`python
def test_e2_requires_finite_forms() -> None:
    assert validate_policy("E2", "1", {"lemma": "go", "constraints": {}}) == [
        {"path": "/", "message": "'accepted_forms' is a required property"}
    ]


def test_e4_requires_nonempty_points() -> None:
    assert validate_policy("E4", "2", {"scoring_points": [], "max_score": 2}) == [
        {"path": "/scoring_points", "message": "[] should be non-empty"}
    ]
\`\`\`

- [ ] **Step 2: Verify red**

Run: \`python -m pytest apps/api/tests/test_english_policies.py -q\`

Expected: FAIL because E2@1 and E4@2 are unsupported.

- [ ] **Step 3: Implement closed schemas**

Define:
- E1@2 \`accepted_answers\`, a closed \`normalization\` object (\`unicode_form=NFKC\`, collapse whitespace, case and terminal-punctuation flags), and \`max_score\`;
- E2@1 \`lemma\`, 1–50 \`accepted_forms\`, closed optional \`part_of_speech\`, \`tense\`, \`number\`, \`determiner\` constraints, and \`max_score\`;
- E3@1 \`grammar_feedback_required\`, optional deterministic accepted-answer rule, and \`max_score\`;
- E4@2 1–20 uniquely identified \`scoring_points\`, each with 1–20 evidence phrases and positive score, plus \`similarity_threshold\` in [0, 1] and \`max_score\`.

Register E1/E2 required categories \`correct, incorrect, empty, boundary\`; E3 adds \`grammar_feedback\`; E4 adds \`needs_review\`.

- [ ] **Step 4: Verify green**

Run: \`python -m pytest apps/api/tests/test_policies.py apps/api/tests/test_english_policies.py apps/api/tests/test_question_runs.py -q\`

Expected: PASS.

- [ ] **Step 5: Commit**

\`\`\`powershell
git add apps/api/src/edu_grader_api/policies.py apps/api/src/edu_grader_api/services/questions.py apps/api/tests/test_english_policies.py
git commit -m "feat(api): add versioned English grading policies"
\`\`\`

## Task 2: Implement pure E1/E2 grading

**Files:**
- Modify: \`services/grader/src/edu_grader/english.py\`
- Modify: \`services/grader/tests/test_english.py\`

**Interfaces:** Adds \`grade_english_rule(request: dict[str, object]) -> GradingResult\`; the request contains \`question_type\`, \`policy_version\`, \`rule\`, and \`answer\`.

- [ ] **Step 1: Write failing behavior tests**

\`\`\`python
def test_e1_v2_matches_normalized_abbreviation() -> None:
    result = grade_english_rule({
        "question_type": "E1", "policy_version": "2",
        "rule": {"accepted_answers": ["I am", "I'm"],
                 "normalization": {"unicode_form": "NFKC", "collapse_whitespace": True,
                                   "ignore_case": True, "ignore_terminal_punctuation": True},
                 "max_score": 1},
        "answer": {"answer": "  i'm!  "},
    })
    assert result.decision == "auto_accepted"


def test_e2_wrong_form_records_the_constraint() -> None:
    result = grade_english_rule({
        "question_type": "E2", "policy_version": "1",
        "rule": {"lemma": "go", "accepted_forms": ["went"],
                 "constraints": {"tense": "past"}, "max_score": 1},
        "answer": {"answer": "go"},
    })
    assert [item.code for item in result.criteria] == ["accepted_form", "tense"]
\`\`\`

- [ ] **Step 2: Verify red**

Run: \`python -m pytest services/grader/tests/test_english.py -q\`

Expected: FAIL with \`ImportError\` for \`grade_english_rule\`.

- [ ] **Step 3: Implement the smallest deterministic dispatcher**

Validate the four request keys, bounded nonblank answer text, policy-version/type pairs, and normalization flags. Reuse \`normalize_answer\`. E1 compares only the normalized configured form set and records the matched form. E2 compares only the normalized finite \`accepted_forms\`; on failure it emits \`accepted_form\` plus a failed criterion for each configured constraint. Its evidence must include the stored constraint key and value, for example \`configured tense constraint requires past\`. Do not infer morphology or call LanguageTool.

- [ ] **Step 4: Verify green**

Run: \`python -m ruff format services/grader/src/edu_grader/english.py services/grader/tests/test_english.py; python -m pytest services/grader/tests/test_english.py -q\`

Expected: PASS.

- [ ] **Step 5: Commit**

\`\`\`powershell
git add services/grader/src/edu_grader/english.py services/grader/tests/test_english.py
git commit -m "feat(grader): add deterministic E1 and E2 grading"
\`\`\`

## Task 3: Add LanguageTool and embedding adapters

**Files:**
- Create: \`services/grader/src/edu_grader/english_dependencies.py\`
- Create: \`services/grader/tests/test_english_dependencies.py\`
- Modify: \`services/grader/pyproject.toml\`

**Interfaces:**
- \`GrammarChecker.check(text: str) -> list[GrammarMatch]\`
- \`SemanticSimilarity.score(left: str, right: str) -> float\`
- \`EnglishDependencyError\` maps failed dependencies to review, not rejection.

- [ ] **Step 1: Write failing adapter tests**

\`\`\`python
def test_languagetool_maps_match_offsets_and_replacements() -> None:
    client = LanguageToolClient(
        "http://languagetool:8010/v2", timeout_seconds=1,
        post=lambda url, data, timeout: FakeResponse({
            "matches": [{"offset": 3, "length": 2,
                         "rule": {"id": "EN_A_VS_AN", "issueType": "grammar",
                                  "category": {"id": "GRAMMAR"}},
                         "message": "Use an", "replacements": [{"value": "an"}]}],
        }),
    )
    assert client.check("It a apple.")[0].replacements == ["an"]


def test_similarity_rejects_nan() -> None:
    with pytest.raises(EnglishDependencyError, match="invalid similarity score"):
        StaticSimilarity(float("nan")).score("left", "right")
\`\`\`

- [ ] **Step 2: Verify red**

Run: \`python -m pytest services/grader/tests/test_english_dependencies.py -q\`

Expected: FAIL with \`ModuleNotFoundError\`.

- [ ] **Step 3: Implement bounded adapters**

Use a synchronous injected \`httpx\` post callable with the configured timeout. Send only \`text\` and \`language=en-US\` to \`POST {base_url}/check\`; map each valid match's offset, length, rule ID, category, issue type, message, and replacement values. Reject malformed results. Implement a local \`SentenceTransformerSimilarity\` that loads only a pre-fetched model directory and metadata file; it validates model ID/revision/digest and clamps only finite cosine scores in [0, 1]. It must not download anything at runtime.

- [ ] **Step 4: Pin the library and verify green**

Add \`sentence-transformers==5.6.0\` to \`services/grader/pyproject.toml\`; record the package version together with the model ID, immutable revision, and artifact digest in the model metadata, then run:

Run: \`python -m pytest services/grader/tests/test_english_dependencies.py -q\`

Expected: PASS.

- [ ] **Step 5: Commit**

\`\`\`powershell
git add services/grader/pyproject.toml services/grader/src/edu_grader/english_dependencies.py services/grader/tests/test_english_dependencies.py
git commit -m "feat(grader): add private English dependency adapters"
\`\`\`

## Task 4: Orchestrate E3/E4 and expose the English endpoint

**Files:**
- Create: \`services/grader/src/edu_grader/english_orchestrator.py\`
- Create: \`services/grader/tests/test_english_orchestrator.py\`
- Modify: \`services/grader/src/edu_grader/main.py\`

**Interfaces:** Adds \`grade_english(request, grammar_checker, similarity) -> GradingResult\` and \`POST /v1/grade/english\`.

- [ ] **Step 1: Write the E4 invariant test**

\`\`\`python
def test_e4_similarity_without_evidence_cannot_award_credit() -> None:
    result = grade_english({
        "question_type": "E4", "policy_version": "2",
        "rule": {"scoring_points": [{"id": "cause",
                  "evidence_phrases": ["bridge closed"], "score": 1}],
                 "similarity_threshold": 0.78, "max_score": 1},
        "answer": {"answer": "The road closure delayed them."},
    }, grammar_checker=NoopGrammarChecker(), similarity=StaticSimilarity(0.95))
    assert (result.decision, result.score, result.requires_review) == (
        "needs_review", 0, True
    )
\`\`\`

- [ ] **Step 2: Verify red**

Run: \`python -m pytest services/grader/tests/test_english_orchestrator.py -q\`

Expected: FAIL with \`ImportError\` for \`grade_english\`.

- [ ] **Step 3: Implement orchestration**

For E3, invoke LanguageTool only when required and return mapped grammar feedback without changing a deterministic correct/incorrect decision. A dependency failure yields \`needs_review\`. For E4, first test each evidence phrase with normalized text, then compute and persist similarity signal per scoring point. Always return \`needs_review\` and \`requires_review=true\`; a point without literal/normalized evidence has score zero even above threshold. The endpoint must return structured \`GradingResult\` for dependency errors.

- [ ] **Step 4: Verify green**

Run: \`python -m pytest services/grader/tests/test_english.py services/grader/tests/test_english_dependencies.py services/grader/tests/test_english_orchestrator.py -q\`

Expected: PASS.

- [ ] **Step 5: Commit**

\`\`\`powershell
git add services/grader/src/edu_grader/main.py services/grader/src/edu_grader/english_orchestrator.py services/grader/tests/test_english_orchestrator.py
git commit -m "feat(grader): orchestrate E3 and review-only E4"
\`\`\`

## Task 5: Carry complete English results through the API adapter

**Files:**
- Modify: \`apps/api/src/edu_grader_api/services/grader.py\`
- Create: \`apps/api/tests/test_english_grader_client.py\`

**Interfaces:** \`HttpGraderClient._request\` maps E1-E4 to \`/v1/grade/english\`; \`GradeResult.evidence\` retains criteria, feedback, review flag, confidence, and dependency metadata.

- [ ] **Step 1: Write a failing mapping test**

\`\`\`python
def test_e4_request_keeps_the_policy_version_and_feedback(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        "edu_grader_api.services.grader.httpx.post",
        lambda url, json, timeout: captured.update(url=url, json=json) or FakeResponse(
            {"decision": "needs_review", "score": 0, "max_score": 1,
             "confidence": 0.8, "criteria": [], "feedback": [{"type": "grammar", "message": "Use an"}],
             "requires_review": True, "grader_version": "grader-english-1"}
        ),
    )
    result = HttpGraderClient("http://grader").grade(
        "E4", {"policy_version": "2", "scoring_points": [{"id": "cause",
        "evidence_phrases": ["bridge closed"], "score": 1}], "max_score": 1},
        {"answer": "road closed"},
    )
    assert captured["json"]["policy_version"] == "2"
    assert result.evidence["feedback"][0]["message"] == "Use an"
\`\`\`

- [ ] **Step 2: Verify red**

Run: \`python -m pytest apps/api/tests/test_english_grader_client.py -q\`

Expected: FAIL because E4 is unsupported.

- [ ] **Step 3: Implement exact mapping**

Add \`_english_request\` that validates string answers and requires the policy version stored in the rule. Post \`question_type, policy_version, rule, answer\`. Preserve all response fields except top-level decision and score in evidence; retain M1/M2 behavior exactly.

- [ ] **Step 4: Verify green**

Run: \`python -m pytest apps/api/tests/test_english_grader_client.py apps/api/tests/test_question_runs.py apps/api/tests/test_math_policy_v2.py -q\`

Expected: PASS.

- [ ] **Step 5: Commit**

\`\`\`powershell
git add apps/api/src/edu_grader_api/services/grader.py apps/api/tests/test_english_grader_client.py
git commit -m "feat(api): route English policies to grader"
\`\`\`

## Task 6: Add immutable grading-run persistence

**Files:**
- Modify: \`apps/api/src/edu_grader_api/models.py\`
- Create: \`apps/api/alembic/versions/0004_english_grading_runs.py\`
- Create: \`apps/api/tests/test_english_grading_runs.py\`

**Interfaces:** \`GradingRun\` references an \`AttemptAnswer\`, question version, and policy; \`GradingSignal\` references a run and an ordinal.

- [ ] **Step 1: Write a failing immutability test**

\`\`\`python
def test_run_retains_snapshots_after_answer_and_rule_change(session: Session) -> None:
    run = GradingRun(
        attempt_answer=answer, question_version_id=version.id, grading_policy_id=policy.id,
        policy_version="2", rule_snapshot_json={"scoring_points": [{"id": "cause"}]},
        answer_snapshot_json={"answer": "bridge closed"}, decision="needs_review",
        score=0, max_score=1, confidence=0.8, requires_review=True,
        grader_version="grader-english-1",
        dependency_versions_json={"embedding": {"id": "sentence-transformers/all-MiniLM-L6-v2",
                                  "revision": "pinned", "digest": "sha256:abc"}},
        thresholds_json={"similarity": 0.78}, evidence_json={},
    )
    session.add(run)
    session.commit()
    answer.answer_json = {"answer": "changed later"}
    session.commit()
    assert session.get(GradingRun, run.id).answer_snapshot_json == {"answer": "bridge closed"}
\`\`\`

- [ ] **Step 2: Verify red**

Run: \`python -m pytest apps/api/tests/test_english_grading_runs.py -q\`

Expected: FAIL with \`ImportError\` for \`GradingRun\`.

- [ ] **Step 3: Implement models and migration**

Create nonnullable JSON snapshots, decision/score/max-score/confidence/review flag, grader/dependency versions, thresholds, evidence, and timestamp on \`grading_runs\`. Create ordered \`grading_signals\` with kind, code, passed, score/max score, and evidence JSON, unique on \`(grading_run_id, ordinal)\`. Do not add update helpers or cascade deletes.

- [ ] **Step 4: Verify migration and green**

Run: \`python -m alembic -c apps/api/alembic.ini upgrade head; python -m pytest apps/api/tests/test_english_grading_runs.py -q\`

Expected: both commands exit 0.

- [ ] **Step 5: Commit**

\`\`\`powershell
git add apps/api/src/edu_grader_api/models.py apps/api/alembic/versions/0004_english_grading_runs.py apps/api/tests/test_english_grading_runs.py
git commit -m "feat(api): persist immutable grading evidence"
\`\`\`

## Task 7: Grade at submission and expose teacher evidence

**Files:**
- Modify: \`apps/api/src/edu_grader_api/services/assignments.py\`
- Modify: \`apps/api/src/edu_grader_api/routers/assignments.py\`
- Modify: \`apps/api/tests/test_assignments.py\`
- Modify: \`apps/api/tests/test_english_grading_runs.py\`

**Interfaces:**
- Extend \`submit_attempt(..., grader_client=None)\`.
- Add \`GET /v1/assignments/{assignment_id}/attempts/{attempt_id}/grading-runs\` for an assigned teacher.
- Submission returns item ID, decision, score, max score, review flag, and safe feedback only.

- [ ] **Step 1: Write a failing orchestration test**

\`\`\`python
def test_submit_persists_e4_evidence_without_leaking_rubric(client, session, monkeypatch) -> None:
    student, assignment, item = published_english_assignment_for_student(session, "E4", "2")
    monkeypatch.setattr(
        "edu_grader_api.services.assignments.HttpGraderClient",
        lambda base_url: FakeEnglishGraderClient(),
    )
    response = client.post(
        f"/v1/student/assignments/{assignment.id}/submit",
        headers=authorize(client, student) | {"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200
    assert response.json()["grading"][0]["requires_review"] is True
    assert "evidence_phrases" not in str(response.json())
    assert session.scalar(select(GradingRun)).thresholds_json == {"similarity": 0.78}
\`\`\`

- [ ] **Step 2: Verify red**

Run: \`python -m pytest apps/api/tests/test_english_grading_runs.py::test_submit_persists_e4_evidence_without_leaking_rubric -q\`

Expected: FAIL because the receipt has no \`grading\` field.

- [ ] **Step 3: Implement transactional persistence**

Before marking an attempt submitted, load all items and saved answers, call the Grader for each, copy rule/answer JSON into a \`GradingRun\`, and split criteria/feedback into ordered signals. If a client call raises, persist a \`needs_review\` run with dependency-error evidence and continue. Flush runs before creating the idempotency receipt; a replay must return the receipt without grading again. Add the teacher route after \`get_teacher_assignment\` access control; it returns full evidence only to that teacher.

- [ ] **Step 4: Verify green**

Run: \`python -m pytest apps/api/tests/test_assignments.py apps/api/tests/test_english_grading_runs.py -q\`

Expected: PASS.

- [ ] **Step 5: Commit**

\`\`\`powershell
git add apps/api/src/edu_grader_api/services/assignments.py apps/api/src/edu_grader_api/routers/assignments.py apps/api/tests/test_assignments.py apps/api/tests/test_english_grading_runs.py
git commit -m "feat(api): grade submissions and retain review evidence"
\`\`\`

## Task 8: Package self-hosted dependencies

**Files:**
- Create: \`infra/languagetool/Dockerfile\`
- Create: \`services/grader/scripts/prefetch_english_model.py\`
- Create: \`services/grader/tests/test_deployment.py\`
- Modify: \`services/grader/Dockerfile\`, \`compose.yaml\`, \`.env.example\`, \`Makefile\`

**Interfaces:** Compose resolves \`LANGUAGETOOL_BASE_URL=http://languagetool:8010/v2\`; the \`languagetool\` service has no host port. The Grader contains model \`metadata.json\` with ID, immutable revision, SHA-256 digest, and package version.

- [ ] **Step 1: Write the failing deployment test**

\`\`\`python
def test_compose_keeps_languagetool_private() -> None:
    compose = Path("compose.yaml").read_text()
    service = compose.split("  languagetool:\n", maxsplit=1)[1].split("\n  api:\n", maxsplit=1)[0]
    assert "ports:" not in service
    assert "LANGUAGETOOL_BASE_URL: ${LANGUAGETOOL_BASE_URL:-http://languagetool:8010/v2}" in compose
\`\`\`

- [ ] **Step 2: Verify red**

Run: \`python -m pytest services/grader/tests/test_deployment.py -q\`

Expected: FAIL because no \`languagetool\` service exists.

- [ ] **Step 3: Implement reproducible images**

Create a LanguageTool image accepting required \`LANGUAGETOOL_VERSION\` and \`LANGUAGETOOL_SHA256\`, downloading the upstream release zip, verifying SHA-256, and starting the HTTP server on 8010 without \`--public\`. Add a private Compose health check and no \`ports\` section.

Implement the prefetch script to require model ID, immutable revision, expected digest, and output directory; download only during Docker build, verify the snapshot, and write metadata. Runtime reads this local directory and cannot download.

- [ ] **Step 4: Verify green**

Run: \`docker compose build languagetool grader; python -m pytest services/grader/tests/test_deployment.py -q\`

Expected: both images build and tests PASS.

- [ ] **Step 5: Commit**

\`\`\`powershell
git add infra/languagetool/Dockerfile services/grader/scripts/prefetch_english_model.py services/grader/tests/test_deployment.py services/grader/Dockerfile compose.yaml .env.example Makefile
git commit -m "feat(infra): self-host English grading dependencies"
\`\`\`

## Task 9: Validate calibration corpus and report metrics

**Files:**
- Create: \`services/grader/src/edu_grader/calibration.py\`
- Create: \`services/grader/tests/test_calibration.py\`
- Create: \`services/grader/tests/fixtures/english_calibration.jsonl\`
- Modify: \`Makefile\`

**Interfaces:** \`load_calibration(path) -> list[CalibrationRecord]\`, \`summarize_calibration(records) -> dict[str, CalibrationMetrics]\`, and \`make calibration-report\`.

- [ ] **Step 1: Write failing cardinality and metric tests**

\`\`\`python
def test_fixture_has_one_thousand_answers_for_one_hundred_questions() -> None:
    records = load_calibration(FIXTURE_PATH)
    assert len(records) >= 1_000
    assert len({record.question_id for record in records}) >= 100


def test_e4_coverage_is_always_zero() -> None:
    metrics = summarize_calibration([
        CalibrationRecord(id="e4-1", question_id="q1", question_type="E4", rule={},
                          student_answer="answer", predicted_decision="needs_review",
                          predicted_score=0, human_decision="needs_review", human_score=1,
                          human_scoring_point_ids=["cause"], expected_feedback_codes=[]),
    ])
    assert metrics["E4"].automatic_coverage == 0.0
\`\`\`

- [ ] **Step 2: Verify red**

Run: \`python -m pytest services/grader/tests/test_calibration.py -q\`

Expected: FAIL with \`ModuleNotFoundError\`.

- [ ] **Step 3: Implement records, metrics, and fixture**

Use a Pydantic JSONL record with nonempty ID/question ID, E1–E4 type, object rule, answer, predicted decision/score, human decision/score, point IDs, and feedback codes. Include physical line number in parse errors. Compute error-release rate as disagreeing automatic accepts / automatic accepts; revision rate as changed reviewed scores / reviewed records; automatic coverage as automatic E1-E3 decisions / all E1-E3 records. Return E4 coverage as zero.

Create 25 question IDs per E1-E4 and 10 de-identified varied answers for each: correct, incorrect, blank, boundary, morphology, grammar feedback, high similarity without evidence, and adversarial. This creates exactly 100 IDs and 1,000 records.

- [ ] **Step 4: Verify green**

Run: \`python -m pytest services/grader/tests/test_calibration.py -q; make calibration-report\`

Expected: tests PASS; command outputs E1, E2, E3, E4 metrics.

- [ ] **Step 5: Commit**

\`\`\`powershell
git add services/grader/src/edu_grader/calibration.py services/grader/tests/test_calibration.py services/grader/tests/fixtures/english_calibration.jsonl Makefile
git commit -m "feat(grader): report English calibration metrics"
\`\`\`

## Task 10: Verify the full Issue #6 contract

**Files:**
- Modify only when a fresh verification failure requires a regression test and minimal fix.

- [ ] **Step 1: Check formatting and lint**

Run: \`python -m ruff format --check apps/api services/grader; python -m ruff check apps/api services/grader\`

Expected: exit 0.

- [ ] **Step 2: Run all tests**

Run: \`make test\`

Expected: exit 0; existing math, assignment, question-version, and English suites pass.

- [ ] **Step 3: Verify deployment graph**

Run: \`docker compose build; docker compose config\`

Expected: exit 0; LanguageTool has no host port and Grader uses its private URL.

- [ ] **Step 4: Audit acceptance evidence**

Confirm named passing tests for E1 normalization/alternatives, E2 constraints, LanguageTool mapping, E4 review-only behavior, immutable run/signal storage, 100-question/1,000-answer calibration corpus, and all three per-type metrics. Run \`git diff --check\` and confirm \`git status --short\` contains only Issue #6 changes.

- [ ] **Step 5: Commit verified integration**

\`\`\`powershell
git add apps/api services/grader infra/languagetool compose.yaml .env.example Makefile
git commit -m "feat: implement English E1-E4 grading"
\`\`\`
