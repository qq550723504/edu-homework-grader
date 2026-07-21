# Profile-configured grade-complexity verification design

**Issue:** #40
**Status:** Implemented
**Scope:** Deterministic age/grade suitability rules for generated candidate questions.

## Goal

Replace the global prompt-length lookup with versioned, profile-specific grade rules that
produce explainable warnings when a generated candidate exceeds its target grade's text,
numeric, or math-operation complexity limits. This satisfies the first-stage requirement
for deterministic, inspectable age-adaptation signals without treating a heuristic as an
automatic publication decision.

## Alternatives considered

1. **Recommended — profile-configured deterministic rules.** Store per-grade limits with
   the curriculum profile and evaluate them locally. This matches the existing grade mapping
   ownership model and lets jurisdictions tune rules without code changes.
2. Keep the current global `_GRADE_TEXT_LIMITS`. It is small but cannot represent profile
   differences and only measures character count.
3. Add a readability/NLP package. No such component exists in the repository; it would add
   an uncalibrated dependency and would not cover numeric or MathJSON complexity.

## Data model and administration boundary

`CurriculumGradeMapping` gains a non-null `complexity_rules_json` document, initially
populated by the migration with an empty object. Curriculum import and profile-management
payloads validate it before persistence, following the existing curriculum lifecycle. Candidate
verification revalidates the persisted document and fails closed if a malformed legacy value
is encountered.

The document is optional per metric so a profile can adopt rules incrementally:

```json
{
  "max_prompt_units": 80,
  "max_sentence_units": 20,
  "max_numeric_absolute_value": 1000,
  "max_math_operation_nodes": 8
}
```

Every supplied value is a positive integer. Unknown keys, booleans, fractions, negatives,
zero, and malformed documents are rejected at the curriculum boundary. An empty document
deliberately means that this grade has no adopted complexity threshold yet; it does not
silently inherit a global default.

## Deterministic metrics

The verification service evaluates only configured metrics for the candidate's objective
revision grade mapping:

- **Prompt units:** Latin words/numbers and CJK ideographs each count as one lexical unit;
  punctuation and whitespace do not count.
- **Maximum sentence units:** split on `.`, `!`, `?`, `。`, `！`, and `？`; each non-empty
  segment uses the same lexical-unit rule. A prompt without terminal punctuation is one
  sentence.
- **Maximum numeric absolute value:** inspect numeric scalar values declared in M1 rules and
  numeric leaves in already-normalized M2 MathJSON. Non-finite values remain policy failures,
  not complexity warnings.
- **Maximum math-operation nodes:** count operator nodes only in the safe M2 normalized AST
  returned by the existing Grader normalizer. Core never parses, evaluates, or interprets
  raw MathJSON itself.

M1 and non-math English candidates simply do not produce M2-operation measurements. Missing
metrics are skipped; a configured metric with no applicable candidate value is also skipped.

## Verification flow and persistence

After common candidate/policy gates and before type-specific grading probes, Core obtains the
target `CurriculumGradeMapping.complexity_rules_json`. For M2 it reuses the existing
`normalize_math_answer` dependency result for both safe-MathJSON verification and complexity
measurement, so no second parser or evaluator is added.

Each exceeded threshold appends a warning finding with stable code
`grade_complexity_warning` and safe evidence:

```json
{
  "grade_level": "G5",
  "metric": "max_sentence_units",
  "observed": 24,
  "limit": 20
}
```

Evidence never includes prompt text, MathJSON, numeric literals, normalized AST, provider
responses, learner data, or exception text. The remediation is static. Findings remain
append-only in the existing draft-scoped validation run; they never change a candidate or
`QuestionVersion`. A warning requires the later teacher-review workflow to acknowledge it and
cannot publish a question automatically.

Malformed configured rules are a `grade_complexity_rules_invalid` blocked finding with only
`{"grade_level": "..."}` evidence. Grader-normalizer unavailability for an M2 rule remains
the existing blocked `m2_mathjson_invalid` result rather than being downgraded to a
complexity warning.

## Testing and delivery

Tests cover migration defaults, import/API validation and export round-trip, each metric at
its exact boundary and one unit beyond, CJK/Latin lexical counting, multiple
sentences, M1 numeric magnitude, M2 normalized operation-node counting, no configured rule,
multiple deterministic warnings in stable order, sanitized evidence, and fail-closed malformed
configuration/normalizer behavior. The suite also verifies that the former global mapping is
removed and no `QuestionVersion` is created.

This slice does not estimate semantic reading level, infer prerequisite mastery, classify
misconceptions, calibrate thresholds from outcomes, or create the #42 golden evaluation set.
It also does not implement #41 teacher acknowledgement or a publication workflow; warnings
remain non-publication decisions until that workflow exists.
