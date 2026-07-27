# Active generator alignment report

## Scope

- Worktree: `D:\code\edu-homework-grader\.worktrees\fix-generation-diversity`
- Branch: `codex/fix-generation-diversity`
- Base inspected: `origin/main` at `076dad3`
- Requested boundary: keep one server-owned active generator contract, preserve
  the current schema and question-type rules, add no selector or migration, and
  do not push

## Root cause

The rebase retained three diversity-test and two diversity-document references
to `generator-v3`, while the current prompt catalog no longer contains v3.

The current mainline is one consolidation step newer than the assignment
wording: commit `eb8bd3a` removed v2, v3, and v4 catalog entries and moved the
complete v4 behavior (schema v2, M1/M2 verification assertions, E1 policy v2,
and E4 reading-material rules) onto the sole development contract,
`generator-v1`. Commit `4af52d5` then set `GENERATION_PROMPT_VERSION` to
`generator-v1`.

Therefore, restoring either v3 or v4 would reverse current mainline
consolidation. The correct current alignment is the sole active
`generator-v1`, which already carries the former v4 schema and rules.

The migration history confirms prompt versions are persisted as opaque string
metadata and governance keys: `0015_ai_generation_jobs.py` adds the job and
attempt `prompt_version` columns, and
`0024_generation_governance_entries.py` adds `prompt_version` as a governance
target type. No migration stores a prompt-template catalog or is required for
this alignment.

## TDD evidence

The focused regression was reproduced before editing:

```text
python -m pytest \
  services/generator/tests/test_contracts.py::test_generator_v3_requires_materially_different_context_and_reasoning \
  -q

FAILED: ValueError: unknown prompt template version
```

After aligning the diversity contract tests with the sole active template:

```text
python -m pytest \
  services/generator/tests/test_contracts.py::test_active_generator_requires_materially_different_context_and_reasoning \
  services/generator/tests/test_contracts.py::test_generation_request_rejects_more_than_eight_or_overlong_avoid_prompts \
  services/generator/tests/test_contracts.py::test_generation_request_rejects_pii_in_avoid_prompts \
  -q

3 passed
```

## Changes

- Updated diversity `GenerationRequest` fixtures to use `generator-v1`.
- Renamed and aligned the diversity prompt-template test with the active
  contract, retaining assertions for all diversity instructions.
- Minimally corrected the diversity design and implementation plan from v3 to
  the current sole active v1, including the internal `_GENERATOR_V1` name.
- Left the server constant, generated request `prompt_version`, active template
  schema, E1/M1/M2/E4 rules, public request model, database schema, and UI
  unchanged because the rebase had already preserved current mainline behavior.

## Boundary review

- No `generator-v3` reference remains in diversity production code, tests, or
  the diversity design/plan.
- The prompt catalog still contains exactly one template.
- No frontend version selector, public payload field, API route, database
  migration, or governance model was added.
- No push or force-push was performed.

## Verification

Full focused generation suite:

```text
python -m pytest \
  services/generator/tests/test_contracts.py \
  apps/api/tests/test_generation_service.py \
  apps/api/tests/test_question_verification.py \
  packages/processor-policy/tests/test_processor_policy.py \
  -q

321 passed in 24.04s
```

Additional checks:

- `ruff format --check services/generator/tests/test_contracts.py`: passed
- `ruff check services/generator/tests/test_contracts.py`: passed
- `python scripts/check_docs_status.py`: passed
- `git diff --check`: passed
- scoped stale-version scan: no `generator-v3`, `_GENERATOR_V3`, or
  `test_generator_v3` reference remains
