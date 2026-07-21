# E3 Candidate Grammar Verification Design

## Goal

Extend Issue #40's candidate-verification pipeline with E3@1 grammar checks for the generated prompt and configured reference answers. Reuse the private, timeout-bounded LanguageTool path that the existing Grader already owns. E3 remains a teacher-review question type and this verification work never creates or publishes a `QuestionVersion`.

## Existing Boundary

The Core API already calls the Grader through `VerificationGraderClient`. The Grader's E3@1 endpoint calls `LanguageToolClient` only when `grammar_feedback_required` is true, returns `needs_review`, and includes grammar feedback in its response. The API must not construct a LanguageTool client, call LanguageTool directly, or persist raw feedback.

## Scope

This slice handles only schema-valid E3@1 candidates.

- Validate the candidate prompt and each configured `accepted_answers` entry, if present.
- Force `grammar_feedback_required` to `true` in an in-memory probe rule. The candidate's stored rule is not changed; the override ensures the validation requirement does not depend on the learner-feedback setting.
- Reuse `VerificationGraderClient.grade("E3", probe_rule, {"format": "text-v1", "text": value}, policy_version="1")` for every probe.
- Treat zero grammar matches as a passing verification signal. E3's independent teacher-review policy remains unchanged.
- Treat one or more grammar matches as a stable warning, not a block. The teacher sees that revision is needed before accepting the candidate.
- Treat a Grader or LanguageTool failure, malformed feedback envelope, or unexpected decision as a stable blocked result. A dependency failure must never pass by default.

This slice does not add a dictionary, LLM, new LanguageTool client, new database table, learner-data flow, E4 scoring validation, CEFR analysis, semantic duplicate detection, or automatic publication logic.

## Candidate Flow

1. The common verification pipeline validates the E3@1 JSON Schema first. Invalid policies retain `policy_schema_invalid` and do not call the Grader.
2. For a valid E3@1 policy, `_e3_findings` makes an in-memory shallow copy of `rule_json` with `grammar_feedback_required=True`.
3. It probes the prompt once, then each string in `accepted_answers` in order. The schema bounds answer cardinality and text size.
4. Each successful response must have `decision="needs_review"` and an evidence `feedback` list. The verifier reads only the list length.
5. A probe with matches produces one `e3_grammar_warning` finding. It does not expose feedback text, offsets, rule IDs, categories, suggestions, probe text, or exception messages.
6. If a probe fails, the helper stops and emits one `e3_grammar_probe_failed` finding. This becomes a blocked validation run.

## Persisted Findings

All findings use the existing immutable `generation_validation_runs` and `validation_findings` path.

| Code | Severity | Sanitized evidence | Meaning |
| --- | --- | --- | --- |
| `e3_grammar_warning` | `warning` | `{"target": "prompt" | "reference_answers", "grammar_match_count": N, "reference_answer_count": N}` | LanguageTool found grammar feedback in a generated text. |
| `e3_grammar_probe_failed` | `blocked` | `{"target": "prompt" | "reference_answers", "reference_answer_count": N}` | The private Grader/LanguageTool path could not produce a safe grammar signal. |

`target` is a fixed category, not candidate content. Counts are integers only. The helper never store copies of Grader evidence, `feedback`, `signals`, dependency versions, error text, or prompt/reference text.

## Teacher Review Semantics

`e3_grammar_warning` is intentionally non-decisive: it tells the candidate-review workflow that a teacher should revise or explicitly review the language. It does not make E3 auto-accepted. Existing subjective-type and publication gates remain the authority for whether a teacher can accept or publish an E3 question.

`e3_grammar_probe_failed` is decisive because a missing or malformed grammar signal means the verification pipeline cannot establish the required safety condition. Retrying after the dependency recovers creates a new immutable validation run.

## Tests and Verification

Focused tests will cover:

- a valid E3 candidate probes the prompt and all configured reference answers with an in-memory `grammar_feedback_required=True` rule;
- clean responses persist a passing run without raw Grader evidence;
- grammar matches generate sanitized warnings with stable category and counts;
- Grader/LanguageTool exceptions, wrong decisions, and malformed feedback produce a sanitized blocked finding;
- schema-invalid E3 policies never call the Grader;
- the stored candidate rule remains unchanged and E3 retains its review-only semantics.

Run focused E3 verification tests, the complete API/Generator/Policy/Grader test suite, Ruff checks, formatting checks, and `git diff --check` before review.

## Self-Review

The design has a single bounded responsibility: candidate-time grammar signals for E3@1. It uses existing Grader and LanguageTool boundaries, makes failure behavior explicit, defines sanitized persisted evidence, and leaves teacher-review, E4, content semantics, and publication behavior outside this slice.
