# AI Candidate Verification Hardening — Consistency and M1/M2 Corpus Design

**Issue:** #83  
**Status:** Approved approach; implementation plan pending review  
**Scope:** PR 1 of verification hardening

## Goal

Make deterministic candidate validation auditable as a release gate by adding
explainable consistency checks for candidate content and a separately runnable
M1/M2 regression corpus. This slice proves validator behavior; it does not
measure generated-question quality, change teacher workflow, or add governance
controls.

## Current Baseline

`question_verification.py` already validates M1, M2, E1-E4, records immutable
runs, and uses stable findings. Its focused regression suite contains 204
passing tests. The missing release-gate boundary is a versioned corpus with a
single command, type-stratified summary, and explicit cross-field consistency
findings.

## Scope and Boundaries

Included:

- candidate-level checks for question text, `rule_json`, explanation, declared
  total score, and scoring points where the question type has those fields;
- M1 checks for expected numeric answer, tolerance, required answer format, and
  explanation conclusion agreement;
- M2 checks for expected MathJSON, declared variables, required answer form,
  score, and explanation final-expression agreement;
- a deterministic M1/M2 corpus covering correct, incorrect, empty, boundary,
  and common-misconception probes;
- `make verification-regression`, which returns non-zero on a failed case and
  prints counts and finding codes grouped by question type;
- CI invocation of that command.

Excluded:

- E1-E4 corpus and language/review-policy changes (PR 3);
- dependency-failure and malicious-input suite (PR 4);
- the remaining four-type corpus (PR 5);
- accuracy metrics, thresholds, report artifacts, or promotion policy (#42);
- feature flags, quota, provider controls, or Kill Switches (#43);
- any automatic acceptance or publication behavior.

## Design

### Structured assertions and consistency findings

Free-form `explanation` has no machine-readable final conclusion in the current
candidate contract. The validator must not use a natural-language parser or a
regular expression to guess one. `GeneratedCandidate` therefore gains a
strict, JSON-schema-visible `verification_assertions` object:

- `final_answer_text`: the short final conclusion shown at the end of the
  explanation;
- `final_answer_mathjson`: a JSON-encoded MathJSON conclusion for M2, and null
  for M1;
- `declared_max_score`: the candidate's explicit total score.

The active `generator-v3` M1 and M2 contract requires this object. The generator prompt requires the explanation
to end with `Final answer: <final_answer_text>`, and M2 requires the encoded
MathJSON assertion to normalize to the same safe AST as `rule_json.expected`.
M1 requires the final-answer text to parse as the same finite Decimal as
`rule_json.expected`; both types require `declared_max_score` to agree with the
policy's effective maximum score. E1-E4 keep the field null in this PR; their
typed assertion contract is introduced only in their own regression slice.
Earlier Prompt versions retain their historical validation behavior so their
immutable drafts remain readable and auditable; only v3 candidates are blocked
for a missing assertion object.

The verification service adds narrow helpers that operate only on these
supported shapes. Every helper returns an existing finding value object, so the
orchestrator persists it as an immutable finding and derives the existing
`blocked`/`warning` status normally. A legacy M1/M2 candidate without the
assertions is blocked, never silently treated as consistent.

New blocked codes use a stable, type-neutral vocabulary unless a type-specific
reason is necessary:

| Code | Meaning |
| --- | --- |
| `answer_explanation_inconsistent` | A required final-answer assertion is absent from the explanation suffix or conflicts with the canonical rule answer. |
| `score_total_inconsistent` | A declared total does not equal the deterministic sum of supported scoring points. |
| `scoring_point_invalid` | A required scoring-point structure is empty, non-finite, or semantically incomplete. |
| `answer_form_inconsistent` | M1/M2 policy requirements conflict with the candidate answer representation. |
| `unsupported_consistency_structure` | A policy shape cannot be checked safely; validation fails closed instead of assuming consistency. |

Evidence is restricted to field identifiers, counts, canonical type labels, and
rule versions. It must not echo prompts, answer text, MathJSON, system prompts,
provider responses, or raw exceptions.

The helpers deliberately do not infer mathematical or linguistic meaning from
free-form prose. They compare only the structured assertion, the required
explanation suffix, and explicit policy values. Ambiguous structures receive
`unsupported_consistency_structure` rather than a false pass. For v3 M1/M2,
missing assertions are an unsupported structure; legacy prompt versions are not
silently reinterpreted as v3 candidates.

### M1/M2 regression corpus

Corpus cases live under `apps/api/tests/fixtures/verification_corpus/` as
versioned JSON files. A shared test/runner adapter materializes the existing
generation job, curriculum revision, and draft fixtures, then executes the real
verification service with deterministic grader doubles. Cases declare only:

- case ID and question type;
- candidate fixture payload or a named mutation of a safe base payload;
- grader behavior profile;
- expected run status and ordered stable finding codes.

The corpus is not an AI-quality golden set. It must not contain private prompts,
provider outputs, student data, or model judgments. It is a fixed validator
regression contract.

At least 20 cases per type are required in the completed PR 5 corpus. PR 1
creates the loader and M1/M2 case categories, with its initial cases proving
each supported category. PR 2 expands those two files to the 20-case minimum.

### Command and CI

`make verification-regression` runs the corpus adapter. Its final output has a
stable text summary, for example:

```text
verification corpus: M1 total=20 passed=20 failed=0
verification corpus: M2 total=20 passed=20 failed=0
verification corpus findings: answer_explanation_inconsistent=3 m2_grader_probe_failed=2
```

The command exits non-zero if a case expectation differs from the resulting
status or finding codes. CI calls the same target after the API test environment
is configured. Pytest remains the authoritative test executor; the command is a
small discoverable entry point rather than a second validation engine.

## Failure Behavior

- An invalid/unsupported consistency structure emits a sanitized blocked
  finding and does not call an unnecessary downstream grader.
- A corpus case with an intentionally wrong answer or a common misconception
  must fail the expectation if it becomes `passed`.
- Failed validation cannot create or mutate a `QuestionVersion`; it only
  appends a `GenerationValidationRun` and findings.
- E3/E4 stay teacher-review-only: this slice does not modify their validator,
  review decision, acceptance, or publication path.

## Testing Strategy

Implementation follows red-green-refactor for each production helper:

1. add a failing service test for a stable finding and verify the failure;
2. add the minimal helper to produce the finding;
3. run the focused service test and corpus adapter;
4. add corpus cases using the real service and deterministic dependencies;
5. run Ruff, affected API tests, and `make verification-regression`.

The existing 204-test focused suite is the immediate compatibility check. The
full project suite will be run with explicit source paths because the current
`make test` target does not set package discovery paths for this monorepo.

## Delivery Slices

1. PR 1 — consistency helpers, stable codes, corpus adapter, initial M1/M2
   skeleton, Make target, and CI hook.
2. PR 2 — expand M1/M2 correct/error/empty/boundary/misconception probes to at
   least 20 deterministic cases each.
3. PR 3 — E1-E4 language and teacher-review-policy regressions.
4. PR 4 — dependency timeout/invalid-response and malicious-input suite.
5. PR 5 — complete six-type 20-case corpus and final CI evidence.

## Acceptance for This Slice

- wrong M1/M2 answers, wrong expected form, contradictory explanation, and
  contradictory score information produce stable blocked findings;
- malformed or ambiguous consistency structures fail closed;
- corpus failures identify a case ID, type, status mismatch, and finding-code
  mismatch without exposing private candidate content;
- `make verification-regression` is independently runnable and CI-bound;
- no review, acceptance, QuestionVersion, quality-threshold, or governance
  behavior changes.
