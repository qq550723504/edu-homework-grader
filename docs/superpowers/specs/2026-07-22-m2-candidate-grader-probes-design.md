# M2 Candidate Grader-Probe Verification Design

**Issue:** #40

## Goal

Strengthen M2@2 candidate verification so it exercises the existing Grader with a
fixed set of safe MathJSON answer probes. The verifier must prove that a candidate
accepts its declared expected expression, rejects a deterministic non-equivalent
answer, and sends missing, invalid-domain, and resource-limit answers to the
Grader's existing review path. Any unavailable, malformed, or unexpected response
blocks the candidate.

## Existing Boundary and Root Cause

Core currently calls the Grader for only the expected expression. That proves the
candidate's expected answer can receive full credit, but not that a nearby wrong
answer is rejected or that the candidate's policy stays fail-closed for empty,
zero-denominator, and bounded-resource inputs.

The Grader already owns all relevant semantics:

- `normalize_mathjson` enforces the supported shorthand, variable allow-list,
  zero-denominator rule, and depth/node/arity limits.
- `/v1/grade/math/expression-v2` turns malformed or unsupported MathJSON into a
  stable `needs_review` result with zero score.
- `grade_normalized_expression` owns algebraic equivalence and the `expanded`
  form requirement.
- its M2 golden fixture covers accepted, incorrect, boundary, partial, and
  invalid MathJSON examples.

Core therefore must neither parse/evaluate MathJSON nor use SymPy, `eval`, or a
second solver. It builds only bounded raw MathJSON envelopes and asks the existing
injected Grader to judge each one.

## Probe Contract

For every schema-valid M2@2 rule, Core runs these probes in this fixed order and
continues after a failure so the external call shape remains deterministic.

| Probe ID | Student MathJSON | Required Grader result |
| --- | --- | --- |
| `expected_mathjson` | the rule's `expected` value | `auto_accepted` and full `max_score` |
| `one_unit_offset` | `["Add", expected, 1]` | non-accepting (`auto_rejected` or `needs_review`) and score `0` |
| `empty_mathjson` | `null` | `needs_review` and score `0` |
| `zero_denominator` | `["Divide", 1, 0]` | `needs_review` and score `0` |
| `resource_limit` | 21 nested `["Negate", …]` nodes | `needs_review` and score `0` |

The offset is mathematically distinct from every supported real-valued expected
expression, including constants, rationals, and expressions in the declared
variables. When an already-valid expected expression is at the Grader's depth
limit, wrapping it once can instead trigger that existing resource guard. Both a
rejection and review are non-accepting zero-score outcomes, so both prove the
candidate does not incorrectly accept the offset without disallowing a
Grader-supported depth-limit expression. The probe deliberately is not labelled
a learner ``common misconception``: inferring one from arbitrary generated prose
or expressions would be unsupported semantic classification. Curated
misconception corpora and outcome calibration remain #42 work.

`null` must travel through `HttpGraderClient` to the Grader instead of being
rejected locally. The Grader has an explicit `Any` request field and produces the
required review result, so this tests the deployed adapter boundary rather than a
new Core interpretation of an empty answer.

## Verification Flow and Safe Persistence

1. Existing policy schema validation and the one expected-answer normalization run
   first. A malformed expected value remains `m2_mathjson_invalid` and no grade
   probes run.
2. `_m2_findings` creates all five probe envelopes in memory and invokes
   `VerificationGraderClient.grade("M2", rule_json, envelope, policy_version="2")`
   once for each.
3. Each response is checked only for its expected stable decision and finite,
   zero/full score. The first mismatch or exception produces one blocked
   `m2_grader_probe_failed` finding with evidence exactly `{"probe": "<id>"}`.
   Core does not persist raw MathJSON, prompt text, Grader evidence, feedback, or
   exception text.
4. Existing immutable `generation_validation_runs` persistence appends that
   result. This slice never creates or edits `QuestionVersion`, changes a
   candidate, or implements teacher acknowledgement/publication.

## Adapter Compatibility

`HttpGraderClient._mathjson_request` must distinguish a missing answer key from a
provided `null` MathJSON value. For these internal probes it forwards the latter
unchanged to the current Grader route. It keeps rule validation, policy version,
and all non-M2 answer envelopes unchanged.

## Testing

Tests cover the exact call order and answer envelopes; accepted/full, rejected/
zero, and review/zero contracts; continuation after a failed early probe; malformed
or non-finite Grader results; no leakage of raw candidate/probe/exception data;
the adapter's null forwarding; and the existing full verifier, Grader golden, and
service test suites.

## Non-Goals

- No candidate-authored or teacher-authored test-case schema.
- No NLP/model inference of common misconceptions.
- No custom MathJSON parser, evaluator, symbolic transformation, HTTP endpoint,
  migration, or dependency.
- No change to the #41 teacher review/acknowledgement workflow or #42 evaluation
  datasets/calibration.
