# Structured AI Generator Design

**Issue:** #39  
**Date:** 2026-07-21

## Scope

Build an isolated `services/generator/` that turns an active, de-identified curriculum objective and teacher constraints into strictly structured candidate-question drafts. Core API remains responsible for authorization, quotas, persistence, and audit. Generator never creates or publishes `QuestionVersion` records.

The first delivery includes a deterministic fake provider and a production OpenAI Responses API adapter. The adapter is disabled unless both an allowlisted endpoint and controlled credentials are present.

## Boundaries

- Generator input contains only tenant-scoped course objective revision, grade, subject, allowed question types, difficulty range, requested count, and bounded teacher constraints.
- It excludes students, classes, names, emails, OIDC claims, submissions, scores, and complete system prompts.
- `OPENAI_API_KEY` is read only from runtime secret injection; it is never persisted, returned, or logged.
- `GENERATOR_OPENAI_MODEL` is mandatory for the OpenAI adapter and recorded on each attempt. Production uses a fixed snapshot rather than a moving alias.
- Model-specific request/response fields are confined to `OpenAIResponsesProvider`; business services consume the provider-neutral contract.

## Data and State

`GenerationJob` stores tenant/teacher IDs, profile and objective revision IDs, request fingerprint, distribution, lifecycle status, counts, bounded cost/timing metrics, and cancellation metadata. Its states are `queued`, `generating`, `validating`, `ready_for_review`, `partially_failed`, `failed`, and `cancelled`.

`GeneratedQuestionDraft` stores a schema-validated candidate payload, objective revision, question type, policy version, difficulty declaration, content hash, validation state, and teacher state. It has no published state and no foreign key that grants it publication authority.

`GenerationAttempt` records provider name, configured immutable model/version, prompt version, seed, bounded request/response digest, status, token/cost metrics, and sanitized failure code. It does not store secrets or unrestricted model responses.

The idempotency key is unique within a tenant. Retrying the same request returns the existing job; cancellation stops future attempts but does not create published questions.

## Provider and Schema Contract

`GenerationProvider.generate(request) -> GenerationResult` returns only a platform `GeneratedCandidateEnvelope` whose top-level object forbids unknown fields. Each candidate requires objective revision reference, question type, policy version, prompt, rule JSON, explanation, knowledge point, and difficulty declaration. M1/M2/E1–E4 must match existing `GradingPolicy` schemas.

The OpenAI adapter uses Responses API structured output. It sends one bounded developer instruction that declares the immutable schema, then passes curriculum and teacher constraint data in separate data fields. It performs bounded retries for transient network/rate-limit errors and schema-invalid/underfilled responses. The fake provider returns deterministic envelopes for tests.

## Processing Flow

```text
Core API authenticated request
  -> quota/idempotency/active-curriculum checks
  -> GenerationJob queued + audit event
  -> Generator de-identified request
  -> Fake or OpenAI provider
  -> platform JSON Schema + policy validation
  -> GeneratedQuestionDraft rows
  -> ready_for_review or partially_failed/failed
  -> #40 verification gates; #41 teacher review
```

Only a fully schema-valid candidate becomes a draft. Invalid output never reaches a teacher or published question route. A partial result retains valid drafts and records a stable failure reason; a total provider failure marks the job failed.

## API and Verification

Add `POST /v1/ai-question-generation/jobs`, `GET /v1/ai-question-generation/jobs/{id}`, `GET /v1/ai-question-generation/jobs/{id}/questions`, cancellation, and `POST /v1/ai-generated-questions/{id}/regenerate`. All list responses paginate and all error responses use stable codes.

Tests prove deterministic M1/M2/E1/E4 fake generation, idempotency, quota rejection, cancellation, unknown-field/schema rejection, policy mismatch, timeout/rate-limit retry, partial failure, de-identification, secret-free audit/log metadata, and the absence of Generator SDK imports from Core question/grading services. An optional integration test runs the OpenAI adapter only when the controlled environment supplies the required secret and allowlisted endpoint.
