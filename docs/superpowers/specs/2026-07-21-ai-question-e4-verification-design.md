# E4 Candidate Scoring-Point Verification Design

## Goal

Extend Issue #40's candidate-verification pipeline with deterministic E4@2 scoring-point integrity checks and isolated Grader probes. The verifier must reject internally inconsistent rubrics and evidence phrases that cannot earn their configured point, while preserving E4's existing teacher-review-only behavior.

## Existing Boundary

The E4@2 policy supplies `scoring_points`, each with an `id`, `evidence_phrases`, and `score`, plus optional `max_score` and `similarity_threshold`. The existing Grader evaluates E4 through the private local similarity adapter and always returns `needs_review`; a literal normalized evidence-phrase match is what awards provisional score. The Core API already reaches it through `VerificationGraderClient`.

The candidate contract has no separately named reading-material field. This slice therefore does not claim to validate a phrase against a reading passage by matching it to the prompt. That would be a false association check. A later, separate contract change can add a source passage or source-reference field and validate that relationship honestly.

## Scope

This slice handles only schema-valid E4@2 candidates.

- Verify normalized scoring-point IDs are unique.
- Verify normalized evidence phrases are unique across the complete rubric, so the same student phrase cannot silently award multiple points.
- Reject normalized evidence phrases from different scoring points when either phrase contains the other. The existing E4 Grader uses substring matching, so overlapping phrases could otherwise award multiple points to one answer.
- Verify the sum of all point scores equals the configured `max_score`, using the existing default of `1` when `max_score` is absent and `math.isclose` for floating-point safety.
- Reject non-finite point scores or `max_score` before arithmetic or Grader probes. JSON Schema treats `NaN` as a number, so this guard must be explicit and fail closed.
- For every evidence phrase, construct an in-memory rule containing only its scoring point, with `max_score` set to that point's score. Probe it through `VerificationGraderClient.grade("E4", single_point_rule, {"format": "text-v1", "text": phrase}, policy_version="2")`.
- Require the probe decision to be `needs_review` and its score to equal the isolated point's score. This verifies literal evidence linkage and the review-only Grader contract without treating semantic similarity as automatic credit.
- Treat any Grader/similarity dependency failure, malformed response, wrong decision, or partial/no score as blocked.

This slice does not create an API-side similarity client, modify the pinned embedding model, persist raw Grader evidence or semantic signals, change `QuestionVersion` publication, add a database migration, verify a source passage that the contract does not carry, or implement E4 automatic acceptance.

## Candidate Flow

1. The common pipeline validates E4@2 JSON Schema first. Invalid policies retain `policy_schema_invalid` and do not call the Grader.
2. `_e4_findings` reads the schema-valid rubric and performs deterministic ID, phrase, and score-total checks before any remote probe.
3. For each scoring point and each evidence phrase, it creates an in-memory isolated rule preserving that point's phrases and the candidate threshold but replacing `scoring_points` with the one point and `max_score` with that point's score.
4. The phrase is sent as a `text-v1` answer to the existing E4 Grader. The candidate rule and persistent draft are never mutated.
5. A matching `needs_review` response with the exact isolated point score passes the probe. A different decision, a non-finite/nonmatching score, or any exception blocks the candidate.
6. Findings continue through the existing immutable validation-run and validation-finding records.

## Persisted Findings

Findings store only stable categories, counts, and numeric score values. They never include point IDs, phrases, prompt text, Grader criteria, feedback, signals, model metadata, similarity values, or exception text.

| Code | Severity | Sanitized evidence | Meaning |
| --- | --- | --- | --- |
| `e4_scoring_points_invalid` | `blocked` | `{"reason": "normalized_duplicate_id" | "normalized_duplicate_phrase" | "overlapping_phrase", "scoring_point_count": N, "evidence_phrase_count": N}` | The rubric can award ambiguous or duplicate credit. |
| `e4_score_total_invalid` | `blocked` | `{"scoring_point_count": N, "point_score_total": N, "max_score": N}` or `{"reason": "non_finite_score", "scoring_point_count": N, "evidence_phrase_count": N}` | Configured point values do not add up to the rubric maximum or contain a non-finite number. |
| `e4_grader_probe_failed` | `blocked` | `{"probe": "evidence_phrases", "scoring_point_count": N, "evidence_phrase_count": N}` | An isolated point could not safely demonstrate its configured credit through the review-only Grader. |

## Teacher Review Semantics

Passing all candidate verification checks does not make E4 automatically accepted, publishable, or final. E4's existing `needs_review` decision and teacher-confirmation path remain authoritative. Candidate verification only establishes that the generated rubric is structurally consistent and each configured literal evidence phrase is gradeable as its intended isolated scoring point.

## Tests and Verification

Focused tests will cover:

- a valid two-point E4 candidate probes every phrase with isolated rules and leaves the stored candidate rule unchanged;
- normalized duplicate point IDs and phrases block before any Grader call;
- overlapping phrases from different points block before any Grader call;
- point-score total mismatch uses floating-point tolerance and blocks invalid totals;
- `NaN` point scores and `NaN` maximum scores block before any Grader call;
- wrong decision, partial score, non-finite score, malformed result, and Grader/similarity exceptions yield only the sanitized blocked finding;
- schema-invalid E4 policies do not call the Grader;
- an otherwise valid E4 run remains candidate-verification `passed` without changing E4's external review-only policy.

Run focused E4 tests, the complete API/Generator/Policy/Grader suite, Ruff checks, formatting checks, and `git diff --check` before review.

## Self-Review

The design is limited to E4@2 rubric integrity and existing Grader probes. It does not invent a missing reading-material relation, expand the processor boundary, or alter teacher-review behavior. Every failure mode defaults to blocked, and every persisted evidence field is non-content metadata.
