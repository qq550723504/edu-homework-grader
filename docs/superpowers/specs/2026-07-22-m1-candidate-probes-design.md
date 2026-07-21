# M1 Candidate Numeric-Probe Verification Design

**Issue:** #40

## Goal

Strengthen M1@1 candidate verification so it proves the configured numeric rule behaves correctly through the existing Grader, rather than only proving that the expected answer is accepted. Every schema-valid candidate receives deterministic in-memory probes for the expected value, an empty answer, both tolerance boundaries, and values immediately outside each boundary. Any unavailable, malformed, unexpected, or non-finite Grader response blocks the candidate.

## Existing Boundary and Root Cause

The Core verifier already rejects non-finite `expected`/`tolerance` values and probes only `str(expected)`. The Grader owns decimal parsing, finite-number rejection, tolerance comparison, accepted/rejected decisions, score assignment, and public feedback. Therefore Core currently cannot establish that blank input is rejected, that the advertised tolerance boundary is inclusive, or that a candidate rule does not accidentally accept an outside answer.

This slice reuses `VerificationGraderClient.grade("M1", rule_json, {"format": "text-v1", "text": answer}, policy_version="1")` once for each probe. Core must not add an alternative numeric grader, parser, `eval`, symbolic solver, HTTP route, migration, or QuestionVersion mutation. The existing Grader remains the single authority for judging every generated probe.

## Probe Construction

For an M1@1 rule with finite numeric `expected` and non-negative finite `tolerance`, Core converts `str(expected)` and `str(tolerance)` to `Decimal` only to construct probe text. It does not compare a learner answer or decide whether a value is correct.

| Probe ID | Probe answer | Required Grader result |
| --- | --- | --- |
| `expected_answer` | `expected` | `auto_accepted` with finite score greater than zero |
| `empty_answer` | empty text | `auto_rejected` with score zero |
| `lower_tolerance_boundary` | `expected - tolerance` | `auto_accepted` with finite score greater than zero |
| `upper_tolerance_boundary` | `expected + tolerance` | `auto_accepted` with finite score greater than zero |
| `below_tolerance_boundary` | `expected - tolerance - 1` | `auto_rejected` with score zero |
| `above_tolerance_boundary` | `expected + tolerance + 1` | `auto_rejected` with score zero |

`Decimal` is used because binary float addition can collapse a small tolerance or perturbation at large magnitudes. The resulting scientific or decimal text must stay within the Grader's existing M1 text envelope limit. A construction failure, non-finite intermediate, or oversized probe blocks with a stable sanitized finding instead of omitting the probe.

The lower/upper probes are both retained when tolerance is zero, even if their text equals the expected value. They document that both endpoints use the same inclusive Grader rule and keep the persisted evidence independent of candidate values.

## Verification Flow

1. Common schema validation runs first. `_m1_findings` applies type-specific probes only to policy version `"1"`; invalid or other versions retain `policy_schema_invalid` and do not call the Grader.
2. The helper validates finite numeric inputs, creates all six `text-v1` envelopes in the table order in memory, and invokes the existing injected Grader once per probe with policy version `"1"`.
3. It validates only `decision` and numeric finiteness/zero-vs-positive score. It never saves Grader evidence, feedback, answer text, exception strings, Decimal values, or prompt text.
4. The first unexpected or failed probe emits one blocked finding. The existing immutable `generation_validation_runs` and `validation_findings` persistence path appends the result; no candidate data is edited.

## Stable Findings

| Code | Severity | Evidence | Meaning |
| --- | --- | --- | --- |
| `m1_answer_invalid` | blocked | `{"expected_is_numeric": bool, "tolerance_is_valid": bool}` or `{"reason": "probe_construction"}` | The configured M1 numeric rule cannot yield safe bounded probes. |
| `m1_grader_probe_failed` | blocked | `{"probe": "expected_answer" | "empty_answer" | "lower_tolerance_boundary" | "upper_tolerance_boundary" | "below_tolerance_boundary" | "above_tolerance_boundary"}` | The existing Grader did not produce the required result for a deterministic probe. |

Evidence deliberately contains no numeric answer, tolerance, score, Grader response, exception, learner data, or candidate prompt. Remediation remains a fixed teacher-facing instruction.

## Scope and Deferred Work

This slice satisfies the per-candidate M1 standard-answer, finite/tolerance, and existing-Grader gate. The in-memory probes are validation test cases; they are not a curriculum-labelled golden corpus.

It does not infer prompt-specific misconceptions, generate semantic distractors, define course-dependent common-error models, build 20 M1 golden samples, calibrate answer-error rates, or provide #42 offline/online evaluation. The misconception/distractor and golden-corpus work remains explicitly deferred to the #40/#42 follow-up scope because it requires curriculum and evaluation governance that this deterministic M1 rule cannot infer safely.

## Tests

Tests use injected deterministic Grader fakes and cover:

- successful six-probe call ordering and no candidate-rule mutation;
- empty, lower/upper boundary, and outside probes with their required decision/score contracts;
- zero tolerance, negative expected values, and decimal tolerance construction;
- rejected expected answer, accepted empty/outside answer, rejected boundary, non-finite score, unexpected decision, and Grader exception, all fail closed with a sanitized probe ID;
- invalid numeric inputs and probe-construction failures never leak raw inputs or call the Grader;
- invalid M1 policy schema never invokes type-specific probes;
- appended immutable validation runs still do not create a `QuestionVersion`.

Run focused M1 tests, all verifier tests, full relevant monorepo tests, Ruff, formatting, and `git diff --check` before review.

## Self-Review

The design uses the existing mature numeric Grader as the only grading authority, keeps Core's Decimal use limited to safe probe construction, explicitly handles fail-closed behavior, and defines a narrow stable evidence contract. It improves candidate-time correctness checks without claiming to solve curriculum-specific misconceptions or #42 quality evaluation.
