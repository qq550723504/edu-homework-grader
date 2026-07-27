# Development Generator Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use one `generator-v1` development prompt that includes the E1 policy-v2 fix, with no active v2/v3/v4 prompt paths.

**Architecture:** Move the complete current v4 prompt contract into the existing v1 catalog entry and make v1 the generation snapshot default. Align verifier gates with that active contract. Keep evaluation JSONL deterministic fixture data, but remove its claim to be Provider or teacher evidence.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Pydantic, pytest, GitHub Actions.

## Global Constraints

- `generator-v1` is the only catalogued development prompt template.
- E1 requires policy version `2`, required `accepted_answers`, and only `max_score` and `normalization` as optional top-level fields.
- No deployment, database mutation, Provider/model change, canary, or governance configuration is in scope.
- Evaluation JSONL is deterministic regression data, not operational evidence.

---

### Task 1: Consolidate the prompt catalog and contract tests

**Files:**
- Modify: `services/generator/src/edu_generator/prompt_templates.py:48-125`
- Modify: `services/generator/tests/test_contracts.py:28-112, 311-322, 339-345`

**Interfaces:**
- Produces: `resolve_prompt_template("generator-v1", question_types)` returns the sole active `PromptTemplate` using `generated_question_candidates-v2`.
- Removes: catalog lookups for `generator-v2`, `generator-v3`, and `generator-v4`.

- [ ] **Step 1: Write the failing catalog test**

Replace the split v2/v3/v4 tests with:

```python
def test_generator_v1_is_the_only_development_prompt_contract() -> None:
    template = resolve_prompt_template("generator-v1", ["M1", "E1", "E4"])

    assert template.schema_version == "generated_question_candidates-v2"
    assert 'set policy_version to "2"' in template.system_instructions
    assert "accepted_answers is required" in template.system_instructions
    with pytest.raises(ValueError, match="unknown prompt template version"):
        resolve_prompt_template("generator-v4", ["E1"])
```

- [ ] **Step 2: Run the test to verify it fails**

```powershell
$env:PYTHONPATH = 'apps/api/src;services/generator/src;packages/processor-policy/src;services/grader/src'
python -m pytest services/generator/tests/test_contracts.py -q
```

Expected: v1 still has basic instructions and v4 remains catalogued.

- [ ] **Step 3: Implement the sole template**

Replace `_GENERATOR_V1` with the complete current v4 instructions and schema-v2 metadata. Delete `_GENERATOR_V2`, `_GENERATOR_V3`, `_GENERATOR_V4`, and their catalog entries. Change Provider request-capture tests to request and assert v1.

- [ ] **Step 4: Run the contract suite**

Run the command from Step 2. Expected: all contract tests pass.

- [ ] **Step 5: Commit**

```powershell
git add services/generator/src/edu_generator/prompt_templates.py services/generator/tests/test_contracts.py
git commit -m "refactor: consolidate generator prompt contract"
```

### Task 2: Align generation and verification with v1

**Files:**
- Modify: `apps/api/src/edu_grader_api/services/generation.py:53-54`
- Modify: `apps/api/src/edu_grader_api/services/question_verification.py:406,462`
- Modify: `apps/api/tests/test_generation_service.py`
- Modify: `apps/api/tests/test_question_verification.py`
- Modify: `apps/api/tests/test_openai_generation_integration.py`

**Interfaces:**
- Produces: every new job snapshots `GENERATION_PROMPT_VERSION == "generator-v1"`.
- Produces: M1/M2 verification-assertion enforcement for v1 jobs.

- [ ] **Step 1: Write failing active-contract assertions**

Update generation tests to require:

```python
assert GENERATION_PROMPT_VERSION == "generator-v1"
assert job.prompt_version == "generator-v1"
```

Update verifier fixtures that exercise required M1/M2 assertions from v3 to v1. Keep the live E1 `policy_version == "2"` and `validate_policy` assertion.

- [ ] **Step 2: Run focused tests to verify they fail**

```powershell
$env:PYTHONPATH = 'apps/api/src;services/generator/src;packages/processor-policy/src;services/grader/src'
python -m pytest apps/api/tests/test_generation_service.py apps/api/tests/test_question_verification.py apps/api/tests/test_openai_generation_integration.py -q
```

Expected: failures while the active constant is v4 and verifier conditions name v3/v4.

- [ ] **Step 3: Implement active-version alignment**

Set:

```python
GENERATION_PROMPT_VERSION = "generator-v1"
```

Replace the verifier's literal membership check with a comparison to the imported active constant.

- [ ] **Step 4: Run focused tests to verify they pass**

Run Step 2. Expected: all selected tests pass; live integration is skipped without `LIVE_OPENAI_GENERATION=1`.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/edu_grader_api/services/generation.py apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_generation_service.py apps/api/tests/test_question_verification.py apps/api/tests/test_openai_generation_integration.py
git commit -m "refactor: use one generator development contract"
```

### Task 3: Make fixture and documentation language development-only

**Files:**
- Modify: `apps/api/tests/fixtures/ai_evaluation/gate-policy-v1.json`
- Modify: `apps/api/tests/fixtures/ai_evaluation/policy-v1.json`
- Modify: `apps/api/tests/fixtures/ai_evaluation/golden-v1.jsonl`
- Modify: `apps/api/tests/test_ai_evaluation.py`
- Modify: `apps/api/tests/test_ai_evaluation_gate.py`
- Modify: `.github/workflows/live-generator-provider-acceptance.yml`
- Modify: `docs/project-status.md`, `docs/pilot-checklist.md`, `docs/status-evidence.json`
- Delete: `docs/superpowers/specs/2026-07-27-tenant-prompt-canary-design.md`
- Delete: `docs/superpowers/specs/2026-07-27-generator-v4-review-gate-design.md`
- Delete: `docs/superpowers/plans/2026-07-27-generator-v4-review-gates.md`

**Interfaces:**
- Produces: consistently v1 deterministic fixture data without a test that binds the fixture to an operational default.
- Produces: workflow and status text naming one development contract.

- [ ] **Step 1: Write the failing fixture-boundary test**

Replace `test_release_gate_fixture_matches_active_generation_prompt_version` with:

```python
def test_release_gate_fixture_uses_its_explicit_fixture_label() -> None:
    policy = _policy()
    records = _records()

    assert policy.approved_prompt_versions == ["fixture-v1"]
    assert {record.prompt_version for record in records} == {"fixture-v1"}
```

Do not import `GENERATION_PROMPT_VERSION`.

- [ ] **Step 2: Run gate tests to verify they fail**

```powershell
$env:PYTHONPATH = 'apps/api/src;services/generator/src;packages/processor-policy/src;services/grader/src'
python -m pytest apps/api/tests/test_ai_evaluation.py apps/api/tests/test_ai_evaluation_gate.py -q
```

Expected: the fixture still carries relabeled v4 metadata and the old coupling test exists.

- [ ] **Step 3: Implement fixture and wording alignment**

Set fixture policies, records, and in-memory test data to `fixture-v1`. Remove active-version coupling. Update workflow labels and status documents to `generator-v1`. Delete the obsolete v4 gate and canary design documents.

- [ ] **Step 4: Verify**

```powershell
$env:PYTHONPATH = 'apps/api/src;services/generator/src;packages/processor-policy/src;services/grader/src'
python -m pytest apps/api/tests/test_ai_evaluation.py apps/api/tests/test_ai_evaluation_gate.py -q
make ai-evaluation
python scripts/check_docs_status.py
```

Expected: tests pass, the local deterministic report is written, and documentation integrity passes.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/tests/fixtures/ai_evaluation apps/api/tests/test_ai_evaluation.py apps/api/tests/test_ai_evaluation_gate.py .github/workflows/live-generator-provider-acceptance.yml docs
git commit -m "refactor: simplify generator development evidence"
```

### Task 4: Verify and update the PR

**Files:** verify only; no source changes expected.

- [ ] **Step 1: Run full focused regressions**

```powershell
$env:PYTHONPATH = 'apps/api/src;services/generator/src;packages/processor-policy/src;services/grader/src'
python -m pytest apps/api/tests/test_ai_question_generation_api.py apps/api/tests/test_generation_service.py apps/api/tests/test_question_verification.py apps/api/tests/test_ai_evaluation.py apps/api/tests/test_ai_evaluation_gate.py services/generator/tests/test_contracts.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run real Provider E1 verification**

Load root `.env` without printing values, set `LIVE_OPENAI_GENERATION=1`, then run:

```powershell
python -m pytest apps/api/tests/test_openai_generation_integration.py -q
```

Expected: `1 passed`; the one active prompt generates E1 policy-v2 rules accepted by the platform validator.

- [ ] **Step 3: Publish and review**

```powershell
git diff --check
git status --short
git push origin codex/generation-schema-diagnostics
```

Expected: clean source tree and successful push. Reply to the remaining fixture comment that the prior relabel was removed and the controlled Provider test is the relevant development validation; resolve only after this code and CI are visible.

## Self-review

- Spec coverage: Tasks 1 and 2 implement a single prompt and its runtime enforcement; Task 3 removes false release-evidence coupling and stale rollout design; Task 4 verifies the Provider boundary and PR state.
- Placeholder scan: no deferred implementation markers are present.
- Type consistency: `GENERATION_PROMPT_VERSION` remains a `str`; template resolution retains `Iterable[str]` question types.
