# English Question Authoring Design

**Issue:** #29 — Repair English E1–E4 policy versions and authoring validation.

## Goal

Enable teachers to create valid E1–E4 draft questions through guided fields, while making the Core API the source of truth for policies that may be created.

## Context and Root Cause

The teacher page currently embeds policy versions and JSON strings. The E1, E2, and E3 defaults fail the Core API's existing JSON Schema validation. The E4 default selects E4@1 even though the Grader only supports E4@2. This lets the browser drift from platform policy and makes ordinary teacher authoring depend on raw JSON.

## Chosen Approach

The Core API will expose a small create-policy catalog. It will list only policies valid for new questions; E4@1 remains in the general schema registry for historical-read compatibility but is absent from the create catalog and rejected for new creation.

The web app will fetch that catalog and use the returned version instead of a hard-coded English version. A pure TypeScript mapper will translate type-specific form values into a `CreateQuestionInput` rule and return field-level client validation errors. The page renders ordinary E1–E4 fields and has an explicit, opt-in advanced JSON mode. Both paths submit through the same mapper and API contract.

## API Boundary

`GET /v1/question-policy-catalog` is teacher-authorized and returns policy metadata required for new-question authoring:

```json
{
  "policies": [
    { "question_type": "E1", "policy_version": "2" },
    { "question_type": "E2", "policy_version": "1" },
    { "question_type": "E3", "policy_version": "1" },
    { "question_type": "E4", "policy_version": "2" }
  ]
}
```

Question creation validates the requested pair against this catalog before normal schema validation. Existing E4@1 records can still be listed and read; the change does not mutate or delete them.

## Web Form Model

The question selector stays type-based. Choosing E1–E4 resets to a valid, structured draft:

- E1: non-empty accepted answers, normalization switches, and maximum score.
- E2: lemma, non-empty accepted forms, constraints, and maximum score.
- E3: accepted answers, an explicit grammar-feedback choice, and maximum score.
- E4: one or more scoring points, each with id, evidence phrases, and score; plus semantic threshold and total score.

The mapper trims text, removes blank repeated entries, rejects invalid finite numeric values, and reports errors using stable field keys. The existing raw JSON textarea is shown only after the teacher enables advanced mode. API 422 JSON Pointer errors are mapped to the corresponding form field and shown without replacing unrelated local input.

## Error Handling

Client validation prevents malformed ordinary submissions. The Core API remains authoritative and returns the existing `detail.errors` payload for schema violations. The web client maps those JSON Pointer paths to visible fields; unknown paths fall back to a form-level message. No answer, student data, token, or question rule is added to logs.

## Verification

- Vitest covers default rules, field validation, E4@2 selection, rule mapping, and JSON Pointer error mapping.
- API tests cover the catalog and confirm new E4@1 creation returns a stable 422 while historical policy validation remains available.
- Existing teacher API/workbench tests remain green.
- Playwright adds one guided creation flow for each E1–E4 type, including the E4@2 request assertion, after deterministic API interception is aligned with the catalog endpoint.

## Non-Goals

This change does not make E3 or E4 automatic final grading, migrate existing E4@1 records, expose policy schemas for arbitrary form generation, or implement #30's assignment composition flow.
