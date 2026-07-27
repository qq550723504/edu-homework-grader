# Final Review Fixes Report: generation diversity

## Scope

- Worktree: `D:\code\edu-homework-grader\.worktrees\fix-generation-diversity`
- Review source: `.superpowers/sdd/final-branch-review.md`
- Implementation authority:
  - `docs/superpowers/specs/2026-07-27-generation-diversity-design.md`
  - `docs/superpowers/plans/2026-07-27-generation-diversity.md`
- Change boundary: existing diversity generation/verification implementation and
  tests only; no frontend, route, public API, persistence migration, or state
  machine changes.

## Findings resolved

### P1: deterministic cross-job pending duplicate checks

`_fingerprint_match_category()` now checks current revisions of scoped
cross-job `pending_review` candidates after published questions and same-job
batch candidates. Exact and normalized matches return `pending_candidate`
before semantic similarity is called.

The existing `_pending_current_revision_candidates()` query remains the single
source for tenant, objective revision, other-job, state, current-revision,
newest-first, and 20-row constraints. Existing safe evidence, category
precedence, comparator counts, and fail-closed semantic behavior are unchanged.

Regression coverage verifies:

- a byte-identical pending prompt produces `duplicate_exact_prompt`;
- a Unicode/whitespace-normalized pending prompt produces
  `duplicate_normalized_prompt`;
- both expose only safe `pending_candidate` evidence;
- `comparison_counts.pending_candidate == 1`;
- the semantic client is not called even when its queued score would be `0.1`.

### P2: complete validation at the outbound OpenAI boundary

`OpenAIResponsesProvider.generate()` now dumps the request to Python data and
reconstructs it through `GenerationRequest.model_validate()` immediately
before JSON serialization and SDK construction. This reuses the canonical
Pydantic field bounds, item-count validator, and de-identification validators
instead of duplicating individual rules in the provider.

Regression coverage uses `model_copy(update=...)` to bypass ordinary
construction and verifies that the SDK is not called for:

- more than 8 `avoid_prompts`;
- an item longer than 1,200 characters;
- a non-string item;
- PII-bearing prompt text (existing regression retained).

### P3: explicit pairwise diversity within one response

The existing `generator-v3` instruction now states that every candidate must
differ materially from every other candidate in the same response in at least
two of context/objects, values/conditions, and cognitive action/solution
structure. It separately states that candidates with the same `question_type`
must differ in both context/objects and cognitive action/solution structure.
No prompt version was added.

## TDD evidence

Each production change followed an observed RED then GREEN cycle:

1. Cross-job exact/normalized tests initially failed because neither expected
   finding existed; after the fingerprint-source fix, both passed.
2. Three provider-boundary cases initially reached the mocked SDK and returned
   `provider_request_failed`; after canonical revalidation, all returned
   `invalid_generation_request` without constructing the SDK client.
3. The template assertion initially failed because the instruction only said
   candidates should follow the same rule; after the wording change, it passed.

All test commands used an explicit current-worktree `PYTHONPATH` because the
machine has an editable `edu_generator` installation pointing at another
worktree.

## Verification

Focused suite:

```text
PYTHONPATH=apps/api/src;services/generator/src;services/grader/src;packages/processor-policy/src
python -m pytest -p no:cacheprovider \
  services/generator/tests/test_contracts.py \
  apps/api/tests/test_generation_service.py \
  apps/api/tests/test_question_verification.py \
  packages/processor-policy/tests/test_processor_policy.py -q

320 passed in 30.75s
```

Additional checks:

- `ruff format --check` on the five changed Python implementation/test files:
  all files formatted.
- `ruff check` on the four changed files without the known pre-existing
  full-file findings in `question_verification.py`: all checks passed.
- `git diff --check`: clean.
- Import-path probe confirmed both `edu_generator.openai_provider` and
  `edu_grader_api.services.question_verification` resolved inside this
  worktree.
