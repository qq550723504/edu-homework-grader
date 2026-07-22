# Official GPT-5.6 Model ID Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow the current official, versioned GPT-5.6 model IDs for governed generation while retaining rejection of floating aliases.

**Architecture:** Keep `validate_immutable_openai_model_id()` as the sole policy boundary. It will continue accepting dated snapshots and fine-tuned IDs, and additionally accept only the three explicit current OpenAI GPT-5.6 model IDs. Settings and the Provider retain their shared validator, so no route or persistence behavior changes.

**Tech Stack:** Python 3.12, Pydantic Settings, pytest, Ruff.

## Global Constraints

- Accept only `gpt-5.6-sol`, `gpt-5.6-terra`, and `gpt-5.6-luna`; do not accept `gpt-5.6`, `latest`, or pattern-based future aliases.
- Do not log configuration values or credentials in validation failures.
- Preserve date-suffixed snapshots and fine-tuned model ID support.
- Document that the production Provider must use a reviewed model ID and an explicit endpoint allowlist.

---

### Task 1: Extend the centralized model identifier policy

**Files:**
- Modify: `services/generator/tests/test_contracts.py`
- Modify: `apps/api/tests/test_settings.py`
- Modify: `services/generator/src/edu_generator/model_snapshots.py`
- Modify: `.env.example`
- Modify: `docs/ai-question-generation-plan.md`

**Interfaces:**
- Produces: `validate_immutable_openai_model_id(model: str) -> str` accepting the official GPT-5.6 IDs and preserving existing safe failure behavior.

- [x] **Step 1: Write failing Provider and production Settings cases**

Add `gpt-5.6-sol`, `gpt-5.6-terra`, and `gpt-5.6-luna` to the valid-model parametrization in both test modules. Add `gpt-5.6-sol-latest` and `gpt-5.6-terra-preview` to the rejected Provider parametrization.

- [x] **Step 2: Verify the new Provider case fails for the intended reason**

Run:

```powershell
$env:PYTHONPATH = "$PWD\apps\api\src;$PWD\services\generator\src;$PWD\packages\processor-policy\src"
python -m pytest services/generator/tests/test_contracts.py::test_openai_provider_preserves_a_valid_immutable_model_id -q
```

Expected: FAIL because `gpt-5.6-terra` is rejected with `provider_model_not_pinned`.

- [x] **Step 3: Implement the minimal explicit allowlist**

In `model_snapshots.py`, declare:

```python
_VERSIONED_GPT_5_6_MODEL_IDS = frozenset({
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
})
```

Return the model immediately only when it belongs to this set, before applying the existing fine-tuned and dated-snapshot checks. Do not introduce a permissive GPT-5.6 regular expression.

- [x] **Step 4: Verify unit and Settings behavior**

Run:

```powershell
$env:PYTHONPATH = "$PWD\apps\api\src;$PWD\services\generator\src;$PWD\packages\processor-policy\src"
python -m pytest services/generator/tests/test_contracts.py apps/api/tests/test_settings.py -q
ruff check services/generator/src/edu_generator/model_snapshots.py services/generator/tests/test_contracts.py apps/api/tests/test_settings.py
ruff format --check services/generator/src/edu_generator/model_snapshots.py services/generator/tests/test_contracts.py apps/api/tests/test_settings.py
```

Expected: all selected tests and lint/format checks pass.

- [x] **Step 5: Update operating documentation**

In `.env.example` and `docs/ai-question-generation-plan.md`, state that approved current OpenAI IDs are the explicit `gpt-5.6-sol`, `gpt-5.6-terra`, and `gpt-5.6-luna`; require an endpoint-specific `GENERATOR_PROVIDER_ALLOWED_HOSTS` entry for a compatible proxy.

- [ ] **Step 6: Verify the external boundary and commit**

With the user-provided configuration loaded from the primary checkout, run one M1 `GenerationRequest` through the Provider. Report only provider, configured model, candidate count, and candidate types. Then run `git diff --check`, commit the five files with `fix: accept official gpt-5.6 model ids`, and open a draft PR before merge.

**Execution note (2026-07-22):** The code and regression checks passed. The external M1 request and a minimal Responses request both received HTTP 403 from the configured proxy, so the live acceptance portion remains blocked on proxy/key permission and this issue must not be closed yet.
