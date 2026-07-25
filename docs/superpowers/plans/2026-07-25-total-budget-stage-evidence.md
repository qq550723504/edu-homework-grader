# Total-budget stage evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add deterministic, real-service release evidence for the remaining shared verification-budget stage boundaries.

**Architecture:** Production code keeps its existing timeout behavior. The release-evidence runner supplies a scenario-local monotonic clock to the existing run_budget_aware_candidate_verification clock parameter; its selected invocation returns the configured budget duration, causing the production budget check at that boundary to fail closed. The scenarios keep real PostgreSQL and real HTTP Grader/LanguageTool services, and retain only stable de-identified result fields.

**Tech Stack:** Python 3.12, SQLAlchemy, pytest, httpx, Docker Compose, GitHub Actions.

## Global Constraints

- Do not change VERIFICATION_TOTAL_TIMEOUT_SECONDS, production cancellation behavior, or public API contracts.
- Do not add candidate text, URLs, request bodies, timestamps, exception diagnostics, or infrastructure addresses to reports.
- Each real-service run must use two isolated Compose repetitions and remove containers and volumes.
- A wrong terminal stage, unexpected dependency call, mutable blocked run, QuestionVersion creation, or cleanup failure is a product regression.
- Keep Issue #122 open; remaining capacity dimensions and reusable RC workflow are excluded.

---

## File structure

- Modify apps/api/src/edu_grader_api/services/verification_release_timeout_evidence.py for the deterministic clock, scenario catalog, scenario helper, and runner registration.
- Modify apps/api/tests/test_verification_release_timeout_evidence.py for the clock, catalog, and report-safety contract.
- Modify apps/api/tests/test_budget_aware_verification.py for terminal stage and no-delegate-call regression coverage.
- Modify docs/verification-release-evidence.md for catalog v6 and the completed total-budget scope.

## Task 1: Deterministic clock contract

**Files:**
- Modify: apps/api/src/edu_grader_api/services/verification_release_timeout_evidence.py
- Test: apps/api/tests/test_verification_release_timeout_evidence.py
- Test: apps/api/tests/test_budget_aware_verification.py

**Interfaces:**
- Consumes: run_budget_aware_candidate_verification(..., clock: Callable[[], float]).
- Produces: BudgetBoundaryClock(expire_on_call: int, total_seconds: float), a zero-argument clock with call_count.

- [ ] **Step 1: Write the failing clock tests**

~~~python
def test_budget_boundary_clock_expires_at_selected_invocation() -> None:
    clock = evidence.BudgetBoundaryClock(expire_on_call=4, total_seconds=30.0)

    assert [clock(), clock(), clock(), clock(), clock()] == [0.0, 0.0, 0.0, 30.0, 30.0]
    assert clock.call_count == 5


@pytest.mark.parametrize("expire_on_call", [0, -1])
def test_budget_boundary_clock_rejects_invalid_call(expire_on_call: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        evidence.BudgetBoundaryClock(expire_on_call=expire_on_call, total_seconds=30.0)
~~~

- [ ] **Step 2: Run the test and confirm it fails**

Run: .venv\Scripts\python -m pytest apps/api/tests/test_verification_release_timeout_evidence.py -q

Expected: FAIL because BudgetBoundaryClock is not defined.

- [ ] **Step 3: Implement the minimal helper**

~~~python
@dataclass(slots=True)
class BudgetBoundaryClock:
    expire_on_call: int
    total_seconds: float
    call_count: int = 0

    def __post_init__(self) -> None:
        if self.expire_on_call <= 0 or self.total_seconds <= 0:
            raise ValueError("budget boundary clock requires positive values")

    def __call__(self) -> float:
        self.call_count += 1
        return self.total_seconds if self.call_count >= self.expire_on_call else 0.0
~~~

Keep it in the release-evidence module. Production callers continue using the default monotonic clock.

- [ ] **Step 4: Write the failing duplicate-boundary regression**

Use the existing fake session and fake grader. Supply a sequence clock that expires at the verified duplicate_check invocation, then assert:

~~~python
assert [finding.code for finding in persisted.findings] == ["verification_total_timeout"]
assert persisted.feature_summary_json["verification_budget_signal"]["terminal_stage"] == "duplicate_check"
assert grader.grade_calls == 0
assert persisted.status is ValidationRunStatus.BLOCKED
~~~

- [ ] **Step 5: Add only the necessary test support**

Add grade_calls to the test fake grader and a sequence-clock helper local to the test file. Do not change VerificationBudget, BudgetedGraderClient, or production validation flow.

- [ ] **Step 6: Run focused tests**

Run: .venv\Scripts\python -m pytest apps/api/tests/test_budget_aware_verification.py apps/api/tests/test_verification_release_timeout_evidence.py -q

Expected: PASS.

- [ ] **Step 7: Commit**

~~~powershell
git add apps/api/src/edu_grader_api/services/verification_release_timeout_evidence.py apps/api/tests/test_budget_aware_verification.py apps/api/tests/test_verification_release_timeout_evidence.py
git commit -m "test: define release evidence budget boundary clock"
~~~

## Task 2: Four real-service total-budget scenarios

**Files:**
- Modify: apps/api/src/edu_grader_api/services/verification_release_timeout_evidence.py
- Test: apps/api/tests/test_verification_release_timeout_evidence.py

**Interfaces:**
- Consumes: BudgetBoundaryClock, base._revision, base._run_snapshot, base._question_version_count, run_budget_aware_candidate_verification, and HttpGraderClient.
- Produces: _TOTAL_BUDGET_SCENARIO_IDS and _total_budget_stage_scenario.

- [ ] **Step 1: Write failing catalog and safe-field tests**

~~~python
def test_total_budget_stage_catalog_is_explicit() -> None:
    assert evidence._TOTAL_BUDGET_SCENARIO_IDS == {
        "capacity_preflight": "total_budget_capacity_preflight",
        "duplicate_check": "total_budget_duplicate_check",
        "grader": "total_budget_dependency_boundary",
        "persist": "total_budget_persist",
    }


def test_total_budget_evidence_fields_are_deidentified() -> None:
    assert evidence._total_budget_evidence_fields() == {
        "scenario_id",
        "terminal_stage",
        "outage_status",
        "outage_finding_codes",
        "outage_call_bucket",
        "old_run_immutable",
        "question_version_delta",
        "passed",
    }
~~~

- [ ] **Step 2: Run the focused test and confirm it fails**

Run: .venv\Scripts\python -m pytest apps/api/tests/test_verification_release_timeout_evidence.py -q

Expected: FAIL because the catalog and safe-field helper are absent.

- [ ] **Step 3: Add the catalog and scenario helper**

~~~python
_TOTAL_BUDGET_SCENARIO_IDS: Mapping[BudgetStage, str] = {
    "capacity_preflight": "total_budget_capacity_preflight",
    "duplicate_check": "total_budget_duplicate_check",
    "grader": "total_budget_dependency_boundary",
    "persist": "total_budget_persist",
}


def _total_budget_stage_scenario(
    session: Session, *, stage: BudgetStage, ordinal: int, grader_url: str
) -> dict[str, object]:
    draft = _create_timeout_draft(session, dependency="grader", ordinal=ordinal)
    session.commit()
    revision = base._revision(session, draft)
    versions_before = base._question_version_count(session)
    clock = BudgetBoundaryClock(
        expire_on_call=_BUDGET_STAGE_EXPIRE_ON_CALL[stage],
        total_seconds=float(settings.verification_total_timeout_seconds),
    )
    run = run_budget_aware_candidate_verification(
        session, draft=draft, revision=revision,
        grader_client=HttpGraderClient(grader_url), clock=clock,
    )
    session.commit()
    snapshot = base._run_snapshot(run)
    session.expire_all()
    persisted = session.get(base.GenerationValidationRun, run.id)
    if persisted is None or base._run_snapshot(persisted) != snapshot:
        raise base.ProductRegression("total_budget_stage_mismatch")
~~~

Derive _BUDGET_STAGE_EXPIRE_ON_CALL from the verified production call sequence. The helper must raise base.ProductRegression("total_budget_stage_mismatch") unless the stable finding is verification_total_timeout and the terminal stage exactly equals stage.

- [ ] **Step 4: Register the four scenarios in every repetition**

Append the new scenarios in catalog order after the capacity baseline. Use distinct ordinals repetition * 100 + 80 through +83. Preserve existing timeout/recovery scenarios. Two repetitions must therefore report 28 scenarios.

~~~python
for offset, stage in enumerate(_TOTAL_BUDGET_SCENARIO_IDS, start=80):
    _append_scenario(
        session, scenarios, _TOTAL_BUDGET_SCENARIO_IDS[stage],
        lambda stage=stage, ordinal=repetition * 100 + offset:
            _total_budget_stage_scenario(
                session, stage=stage, ordinal=ordinal, grader_url=context.grader_url
            ),
    )
~~~

- [ ] **Step 5: Make every scenario fail closed**

Require all of the following:

~~~python
passed = (
    run.status.value == "blocked"
    and finding_codes == ["verification_total_timeout"]
    and budget_signal.get("status") == "total_timeout"
    and budget_signal.get("terminal_stage") == stage
    and old_run_immutable
    and versions_after == versions_before
    and (stage not in {"capacity_preflight", "duplicate_check", "grader"} or grader_call_bucket == "none")
)
~~~

For persist also require the blocked run reloads from PostgreSQL; an exception is not evidence of success.

- [ ] **Step 6: Run focused tests and Compose validation**

~~~powershell
.venv\Scripts\python -m pytest apps/api/tests/test_budget_aware_verification.py apps/api/tests/test_verification_release_timeout_evidence.py -q
docker compose --file infra/release-evidence/compose.yaml config --quiet
~~~

Expected: all tests pass and Compose exits 0.

- [ ] **Step 7: Commit**

~~~powershell
git add apps/api/src/edu_grader_api/services/verification_release_timeout_evidence.py apps/api/tests/test_budget_aware_verification.py apps/api/tests/test_verification_release_timeout_evidence.py
git commit -m "feat: add release evidence budget stage scenarios"
~~~

## Task 3: Contract documentation and real verification

**Files:**
- Modify: docs/verification-release-evidence.md
- Modify: apps/api/src/edu_grader_api/services/verification_release_timeout_evidence.py
- Test: apps/api/tests/test_verification_release_timeout_evidence.py

**Interfaces:**
- Consumes: the v6 catalog and generated verification-release-evidence-v1 JSON and Markdown.
- Produces: a documented four-stage contract and a 28-scenario real evidence report.

- [ ] **Step 1: Write the failing version test**

~~~python
def test_total_budget_catalog_version_is_explicit() -> None:
    assert evidence.SCENARIO_CATALOG_VERSION == 6
    assert len(evidence._TOTAL_BUDGET_SCENARIO_IDS) == 4
~~~

- [ ] **Step 2: Run it and confirm it fails**

Run: .venv\Scripts\python -m pytest apps/api/tests/test_verification_release_timeout_evidence.py::test_total_budget_catalog_version_is_explicit -q

Expected: FAIL while the catalog is version 5.

- [ ] **Step 3: Update implementation and documentation**

Set SCENARIO_CATALOG_VERSION to 6. Add a Total verification-budget stage boundaries section describing capacity_preflight, duplicate_check, grader, and persist; remove the completed total-budget item from Current limitations. Retain reusable RC workflow and OIDC browser acceptance as limitations.

- [ ] **Step 4: Run static and focused checks**

~~~powershell
.venv\Scripts\python -m ruff format --check apps/api/src/edu_grader_api/services/verification_release_timeout_evidence.py apps/api/tests/test_budget_aware_verification.py apps/api/tests/test_verification_release_timeout_evidence.py
.venv\Scripts\python -m ruff check apps/api/src/edu_grader_api/services/verification_release_timeout_evidence.py apps/api/tests/test_budget_aware_verification.py apps/api/tests/test_verification_release_timeout_evidence.py
.venv\Scripts\python -m pytest apps/api/tests/test_budget_aware_verification.py apps/api/tests/test_verification_release_timeout_evidence.py -q
~~~

Expected: all commands exit 0.

- [ ] **Step 5: Run real release evidence twice**

~~~powershell
Remove-Item Env:RELEASE_EVIDENCE_LANGUAGE_CONNECT_TIMEOUT_HOST -ErrorAction SilentlyContinue
$env:RELEASE_EVIDENCE_CONNECT_TIMEOUT_NETWORK='172.29.254.0/24'
make verification-release-evidence
~~~

Expected: summary has repetition_count=2, scenario_count=28, all_repetitions_succeeded=true, and all_cleanup_succeeded=true. Each new scenario must report the intended terminal stage, one stable timeout finding, zero QuestionVersion delta, and no forbidden dependency calls.

- [ ] **Step 6: Commit**

~~~powershell
git add docs/verification-release-evidence.md apps/api/src/edu_grader_api/services/verification_release_timeout_evidence.py apps/api/tests/test_verification_release_timeout_evidence.py
git commit -m "docs: cover release evidence budget stages"
~~~

## Task 4: Publish and issue follow-through

**Files:**
- Modify: .github/workflows/verification-release-evidence.yml only if its existing pull-request path filters do not cover every changed service, test, and documentation path.

**Interfaces:**
- Consumes: Tasks 1-3 commits and the existing GitHub release-evidence workflow.
- Produces: a draft PR, all-green CI evidence, and an Issue #122 progress comment without closing the Issue.

- [ ] **Step 1: Check trigger coverage**

Run: Get-Content .github/workflows/verification-release-evidence.yml

Expected: verify the paths include changed implementation, tests, and docs. Do not edit it if coverage already exists.

- [ ] **Step 2: Verify the complete local diff**

~~~powershell
git diff origin/main...HEAD --check
git status --short
git log --oneline origin/main..HEAD
~~~

Expected: only planned service, tests, and documentation changes; no generated artifacts are staged.

- [ ] **Step 3: Push and create the draft PR**

~~~powershell
git push --set-upstream origin codex/total-budget-stage-evidence
~~~

Create a Draft PR targeting main with Refs #122. State the four stages, two real repetitions, 28 scenarios, and the remaining P0 scope. Do not mark ready or merge before all checks pass.

- [ ] **Step 4: Inspect checks and feedback**

Use the GitHub connector for CI, Docs integrity, AI evaluation, performance artifact, and release-evidence status. For a failed Action invoke github:gh-fix-ci before code changes. Inspect comments, reviews, and unresolved review threads before readiness.

- [ ] **Step 5: Update Issue #122 after successful merge**

Post the merged commit, evidence artifact name/digest, 2 repetitions / 28 scenarios, and the remaining capacity/RC-workflow scope. Keep #122 open.

## Plan self-review

- Spec coverage: Tasks 1-2 implement clock-driven evidence for all four boundaries; Task 3 covers de-identification, documentation, Compose, and real-service verification; Task 4 covers CI, PR, and Issue #122.
- Placeholder scan: the plan contains no unresolved markers or unbounded implementation steps.
- Type consistency: BudgetBoundaryClock, _TOTAL_BUDGET_SCENARIO_IDS, _total_budget_stage_scenario, and BudgetStage are named consistently before later tasks consume them.
