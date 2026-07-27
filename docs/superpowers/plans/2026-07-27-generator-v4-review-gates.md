# Generator v4 Review Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PR #142's live and offline release checks exercise generator-v4, then resolve the review threads with evidence.

**Architecture:** The opt-in Provider test validates the E1 v2 rule through the platform validator. The deterministic offline fixture is bound to `GENERATION_PROMPT_VERSION`, so policy, corpus, and production default cannot drift silently.

**Tech Stack:** Python 3.13, pytest, Pydantic, GitHub Actions, JSON fixtures.

## Global Constraints

- `golden-v1.jsonl` remains deterministic test data, not teacher-review evidence.
- Reuse `validate_policy`; do not copy E1 schema rules into the test.
- Do not alter production deployment, Kubernetes governance records, Keycloak, or secrets.
- Run Python with `PYTHONPATH=apps/api/src;services/generator/src;packages/processor-policy/src;services/grader/src`.
- Do not reply to or resolve GitHub threads before matching commits and verification exist.

---

### Task 1: Validate E1 policy-v2 in live Provider acceptance

**Files:**
- Modify: `apps/api/tests/test_openai_generation_integration.py:7-91`
- Test: `apps/api/tests/test_openai_generation_integration.py::test_openai_responses_provider_returns_active_contract_representative_batch`

**Interfaces:**
- Consumes: `validate_policy(question_type, policy_version, rule_json) -> list[dict[str, object]]`.
- Produces: a protected acceptance failure for a non-v2 or invalid E1 rule.

- [ ] **Step 1: Add E1 rule assertions**

```python
from edu_grader_api.policies import validate_policy

assert e1.policy_version == "2"
assert validate_policy(e1.question_type, e1.policy_version, e1.rule_json) == []
```

- [ ] **Step 2: Verify the controlled skip boundary**

```powershell
$env:PYTHONPATH = 'apps/api/src;services/generator/src;packages/processor-policy/src;services/grader/src'
python -m pytest apps/api/tests/test_openai_generation_integration.py -q
```

Expected: one intentional skip without protected credentials.

- [ ] **Step 3: Run controlled local Provider acceptance**

```powershell
Get-Content 'D:\code\edu-homework-grader\.env' | ForEach-Object {
  if ($_ -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
    Set-Item -Path ("Env:" + $matches[1]) -Value $matches[2]
  }
}
$env:LIVE_OPENAI_GENERATION = '1'
$env:PYTHONPATH = 'apps/api/src;services/generator/src;packages/processor-policy/src;services/grader/src'
python -m pytest apps/api/tests/test_openai_generation_integration.py -q
```

Expected: one pass without printing secrets.

- [ ] **Step 4: Commit Task 1**

```powershell
git add apps/api/tests/test_openai_generation_integration.py
git commit -m "test: validate E1 v4 provider rules"
```

### Task 2: Bind the deterministic offline fixture to the active Prompt

**Files:**
- Modify: `apps/api/tests/fixtures/ai_evaluation/gate-policy-v1.json:3-9`
- Modify: `apps/api/tests/fixtures/ai_evaluation/policy-v1.json:3-9`
- Modify: `apps/api/tests/fixtures/ai_evaluation/golden-v1.jsonl`
- Modify: `apps/api/tests/test_ai_evaluation.py:15-75`
- Modify: `apps/api/tests/test_ai_evaluation_gate.py:1-38`
- Test: `apps/api/tests/test_ai_evaluation_gate.py::test_release_gate_fixture_matches_active_generation_prompt_version`

**Interfaces:**
- Consumes: `GENERATION_PROMPT_VERSION`, `load_policy`, and `load_records`.
- Produces: a regression failure when the active Prompt differs from policy or corpus metadata.

- [ ] **Step 1: Add the failing active-version test**

```python
from edu_grader_api.services.generation import GENERATION_PROMPT_VERSION

def test_release_gate_fixture_matches_active_generation_prompt_version() -> None:
    policy = _policy()
    records = _records()
    assert policy.approved_prompt_versions == [GENERATION_PROMPT_VERSION]
    assert {record.prompt_version for record in records} == {GENERATION_PROMPT_VERSION}
```

- [ ] **Step 2: Verify it fails before fixture changes**

```powershell
$env:PYTHONPATH = 'apps/api/src;services/generator/src;packages/processor-policy/src;services/grader/src'
python -m pytest apps/api/tests/test_ai_evaluation_gate.py -k active_generation_prompt_version -q
```

Expected: fail because the checked-in fixture identifies `generator-v3`.

- [ ] **Step 3: Update only deterministic version metadata**

Set `approved_prompt_versions` to `generator-v4` in both policy JSON files. Replace only `"prompt_version":"generator-v3"` with `"prompt_version":"generator-v4"` in `golden-v1.jsonl`. Update the in-memory policy and records in `test_ai_evaluation.py` to v4; leave every outcome, fingerprint, cost, and other field unchanged.

- [ ] **Step 4: Verify gate and evaluator**

```powershell
$env:PYTHONPATH = 'apps/api/src;services/generator/src;packages/processor-policy/src;services/grader/src'
python -m pytest apps/api/tests/test_ai_evaluation.py apps/api/tests/test_ai_evaluation_gate.py -q
make ai-evaluation
```

Expected: all pass and `artifacts/ai-evaluation/report.json` says `promotion_eligible: true`.

- [ ] **Step 5: Commit Task 2**

```powershell
git add apps/api/tests/fixtures/ai_evaluation/gate-policy-v1.json apps/api/tests/fixtures/ai_evaluation/policy-v1.json apps/api/tests/fixtures/ai_evaluation/golden-v1.jsonl apps/api/tests/test_ai_evaluation.py apps/api/tests/test_ai_evaluation_gate.py
git commit -m "test: bind evaluation gate to generator v4"
```

### Task 3: Verify, publish, and resolve review threads

**Files:**
- Verify: `apps/api/tests/test_ai_question_generation_api.py`
- Verify: `apps/api/tests/test_openai_generation_integration.py`
- Verify: `apps/api/tests/test_ai_evaluation.py`
- Verify: `apps/api/tests/test_ai_evaluation_gate.py`
- Verify: `services/generator/tests/test_contracts.py`

**Interfaces:**
- Consumes: Task 1 and 2 commits and GitHub PR #142.
- Produces: a pushed branch and no unresolved addressed review thread.

- [ ] **Step 1: Run focused verification**

```powershell
$env:PYTHONPATH = 'apps/api/src;services/generator/src;packages/processor-policy/src;services/grader/src'
python -m pytest apps/api/tests/test_ai_question_generation_api.py apps/api/tests/test_openai_generation_integration.py apps/api/tests/test_ai_evaluation.py apps/api/tests/test_ai_evaluation_gate.py services/generator/tests/test_contracts.py -q
python scripts/check_docs_status.py
git diff --check
```

Expected: tests and documentation integrity pass; live test skips unless enabled.

- [ ] **Step 2: Push and confirm checks**

```powershell
git push origin codex/generation-schema-diagnostics
gh pr checks 142 --repo qq550723504/edu-homework-grader --watch
```

Expected: required checks complete for the new head.

- [ ] **Step 3: Reply and resolve addressed threads**

Reply to the live-acceptance thread: `Fixed: the controlled test now requires E1 policy version 2 and validates rule_json with the platform policy validator.`

Reply to the diagnostics thread: `Fixed in 90ea487: rule diagnostics are now returned for PARTIALLY_FAILED jobs; the review anchor is outdated.`

Reply to the offline-gate thread: `Fixed: the deterministic gate fixture and policy are bound to the active generation Prompt version; operational canary evidence remains a separate deployment gate.`

Resolve those threads and the superseded original live-acceptance thread only after matching commits are visible. Do not resolve a new regression comment.

- [ ] **Step 4: Confirm merge eligibility**

```powershell
gh pr view 142 --repo qq550723504/edu-homework-grader --json mergeStateStatus,reviewDecision,statusCheckRollup,url
```

Expected: merge state no longer reports unresolved comments; use the authenticated Chrome merge panel if GitHub CLI transport fails.
