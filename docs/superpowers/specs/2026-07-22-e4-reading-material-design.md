# E4 Generated Reading Material Design

## Goal

Make E4@2 candidate scoring-point evidence traceable to a bounded, model-generated reading passage. An E4 candidate may pass verification only when each configured evidence phrase occurs in its own generated reading material after the same normalization used by the E4 Grader.

## Candidate Contract

`GeneratedCandidate` gains a nullable top-level `reading_material` string with a maximum length of 8,000 characters.

- E4 candidates must provide a nonblank `reading_material` after trimming whitespace.
- M1, M2, E1, E2, and E3 candidates must provide `null` or omit the field; non-E4 material is rejected.
- The field belongs to the model-generated candidate payload, not `GenerationRequest`. Teachers cannot inject source passages into the model request through this slice.
- The existing strict Responses JSON schema is regenerated from this Pydantic contract, so the Fake Provider, OpenAI Provider, and Core API consume one schema.
- The material remains inside `candidate_json`, is returned only by the existing teacher-scoped draft endpoint, and participates in the existing content hash. It is not copied into a validation finding, Grader request, log, or error message.

This is generated material only. It does not accept textbook extracts, URLs, external source IDs, attribution claims, or teacher-provided passages. Those require a separate source-governance and copyright workflow.

## Provider and Persistence Flow

1. The Fake Provider emits `reading_material=None` for non-E4 candidates and a deterministic short passage containing its E4 evidence phrase for E4 candidates.
2. The OpenAI Provider receives the updated strict schema. It must return material only for E4 candidates; malformed output is rejected by `GeneratedCandidate` before persistence.
3. Core API persistence continues to serialize `candidate.model_dump(mode="json")`, so the material is immutable with the generation draft and included in its content hash.
4. Existing candidate-list/detail routes return the unchanged `candidate_json` envelope, so teacher review sees the passage without a new public route or table.

## E4 Verification Flow

The existing E4 helper receives `reading_material` from the candidate after the common E4@2 policy gate.

1. A missing, non-string, blank, or over-limit material field produces `e4_reading_material_invalid` as `blocked` and performs no Grader probe.
2. Verification sends the material through the existing candidate safety scan along with prompt, explanation, and rule text. Unsafe material is blocked by the existing sanitized safety finding.
3. Before each isolated E4 Grader probe, normalize the evidence phrase and material with the E4 Grader's fixed NFKC, whitespace, case, and terminal-punctuation rules.
4. A normalized phrase absent from the normalized material produces `e4_evidence_material_mismatch` as `blocked`; probes do not run because the candidate has no explainable evidence source.
5. If all phrases occur, retain the existing isolated scoring-point Grader probes, overlap checks, score-total checks, and `needs_review` requirement.

## Persisted Findings

All results use existing immutable validation-run records. Findings never contain material, phrases, point IDs, prompt text, offsets, snippets, or exception messages.

| Code | Severity | Sanitized evidence | Meaning |
| --- | --- | --- | --- |
| `e4_reading_material_invalid` | `blocked` | `{"reason": "missing_or_blank" | "too_long", "scoring_point_count": N, "evidence_phrase_count": N}` | An E4 candidate lacks a bounded generated reading passage. |
| `e4_evidence_material_mismatch` | `blocked` | `{"probe": "reading_material", "scoring_point_count": N, "evidence_phrase_count": N}` | At least one evidence phrase is not grounded in the generated material. |

## Scope Boundaries

- Do not add a database column or migrate historical drafts; `candidate_json` already persists the new field.
- Do not backfill legacy E4 candidates. A legacy candidate without material blocks when revalidated, preserving fail-closed behavior.
- Do not use semantic embeddings, an LLM judge, or an API-side LanguageTool/similarity client for passage association.
- Do not change E4's review-only Grader decision, teacher confirmation, publication gate, or assignment behavior.
- Do not create copyright assertions from a generated passage. The existing safety scan only applies its established minor-safety terms.

## Tests and Verification

Tests cover contract acceptance/rejection by question type, Responses schema shape, Fake Provider output, Core API persistence and teacher payload round-trip, material safety scanning, missing/blank/oversized material blocking, evidence mismatch blocking before the Grader, normalized material matching, legacy E4 revalidation, and unchanged non-E4 candidates.

Run focused Generator/API verification tests, then the complete Policy/Generator/API/Grader suite, Ruff, formatting, and `git diff --check` before review.

## Self-Review

The design is limited to model-generated E4 reading material and deterministic literal evidence grounding. It uses existing candidate persistence and Grader boundaries, keeps all teacher-review semantics unchanged, and explicitly defers external source, attribution, and copyright governance rather than suggesting false assurance.
