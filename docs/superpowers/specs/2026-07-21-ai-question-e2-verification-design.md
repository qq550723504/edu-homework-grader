# AI Candidate Question Verification — E2 Word-form Design

**Issue:** #40
**Status:** Approved design
**Scope:** E2 verification slice

## Goal

Add deterministic E2@1 verification for AI candidate drafts. Every configured accepted word form must be accepted at full score by the existing English Grader under the candidate's own lemma and constraints.

## Boundary

- Reuse the existing `VerificationGraderClient.grade` English protocol; do not add a dictionary, lemmatizer, free-form LLM, or LanguageTool dependency.
- Only E2 policy version `1` receives this type-specific probe. Common policy validation remains authoritative for malformed or unsupported rules.
- Evidence records only a stable probe category and accepted-form count; it never stores a form, lemma, grader response, exception text, or learner data.
- Runs remain draft-scoped and immutable; this slice never creates or changes a `QuestionVersion`.

## Verification flow

1. Preserve the existing common curriculum, policy, safety, duplicate, and difficulty gates.
2. For schema-valid E2@1 rules, normalize `accepted_forms` with the existing whitespace/Unicode/case normalizer and block normalized duplicates or empty values with `e2_forms_invalid`.
3. For every configured accepted form, call the existing English Grader with the original E2 rule and a `text-v1` answer envelope.
4. A probe succeeds only on `auto_accepted` with full configured score. Any rejected, partial, review, unavailable, or non-full-score result creates `e2_grader_probe_failed`.
5. Persist sanitized findings through the existing run mechanism.

## Stable findings

| Code | Severity | Meaning |
| --- | --- | --- |
| `e2_forms_invalid` | blocked | Accepted forms are empty or collide after platform normalization. |
| `e2_grader_probe_failed` | blocked | The existing English Grader fails to accept a configured form at full score. |

## Tests

Tests use injected deterministic graders to prove valid constrained forms pass, normalized duplicates block, and rejected, partial, or dependency-failed probes block with sanitized evidence. A schema-invalid E2 rule must retain only `policy_schema_invalid` and never enter the type-specific helper.

## Deferred work

This slice does not validate morphology against an external lexicon, judge prompt grammar, infer unintended alternate answers, or invoke LanguageTool. Those capabilities belong to later E3/E4 and calibrated English evaluation work.
