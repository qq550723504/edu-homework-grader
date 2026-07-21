# AI Candidate Question Verification — M2 MathJSON Design

**Issue:** #40
**Status:** Approved design
**Scope:** M2 verification slice

## Goal

Extend the existing draft-scoped AI candidate verification pipeline with deterministic M2@2
MathJSON validation. A run must block a candidate when its expected expression cannot be
normalized safely or when the existing M2 Grader does not accept the configured expression.

## Boundary

- Reuse `HttpGraderClient.normalize_math_answer` and `HttpGraderClient.grade`; the verification
  service does not add an expression parser, symbolic evaluator, or `eval` path.
- Only M2 policy version `2` receives this type-specific probe. Other M2 policy versions remain
  protected by the existing policy-schema gate and receive no implicit compatibility behavior.
- Validation evidence records only stable categories and selected safe metadata. It never stores a
  raw MathJSON expression, normalizer exception text, provider response, or learner data.
- Each invocation appends a `GenerationValidationRun`; it does not edit the candidate or create a
  `QuestionVersion`.

## Verification flow

After the common curriculum, difficulty, policy, safety, and duplicate gates succeed or record
their findings, the M2 verifier performs these steps:

1. Read `expected`, `variables`, `required_form`, `form_score`, and `max_score` from `rule_json`.
2. Reject unsupported policy versions or structurally invalid M2 inputs through the existing
   `policy_schema_invalid` finding.
3. Call `normalize_math_answer` with the expected MathJSON and the declared variable list. A
   normalizer rejection or dependency failure creates `m2_mathjson_invalid` with blocked severity.
4. Call `grade` with the original M2 rule and the expected MathJSON answer. The run passes this
   probe only when the result represents a successful full-score evaluation for the configured rule.
   A failed or unavailable probe creates `m2_grader_probe_failed` with blocked severity.
5. Persist the findings through the existing immutable run mechanism and derive status with the
   existing blocked/warning/passed precedence.

## Stable findings

| Code | Severity | Meaning |
| --- | --- | --- |
| `m2_mathjson_invalid` | blocked | Expected MathJSON cannot be safely normalized for the declared variables. |
| `m2_grader_probe_failed` | blocked | The existing M2 Grader rejects the expected expression or is unavailable. |

## Tests

Tests use a deterministic injected grader client and assert:

- valid M2@2 normalizes and probes successfully;
- an unsafe or malformed MathJSON expression blocks without raw expression/exception evidence;
- normalizer and Grader dependency failures block safely;
- a non-full-score or rejected probe blocks;
- M2 findings append to immutable validation history and do not create `QuestionVersion` rows.

## Deferred work

This slice does not infer alternate correct answers, solve equations, detect under-specified domains,
generate common-misconception cases, or build the 20-case golden set. Those require calibrated
curriculum rules and belong to later #40 evaluation work.
