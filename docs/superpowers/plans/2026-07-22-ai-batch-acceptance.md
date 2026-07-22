# Atomic AI Candidate Batch Acceptance Implementation Plan

> Execute test-first in the isolated `codex/verification-gates` worktree.

**Goal:** Add an idempotent, all-or-nothing API that accepts a selected batch of verified AI
candidates without bypassing the existing single-candidate acceptance gate.

## Task 1: Persistence and service contract

- Add failing model/service tests for a batch acceptance record, ordered item rows, replay, warning
  acknowledgement, and rollback on one blocked/stale item.
- Add the migration and ORM records for the immutable batch request plus item-to-review-decision
  mapping.
- Implement a service that locks and preflights every item, then delegates each conversion to
  `accept_review_draft` within the caller transaction.
- Run the focused review-service/model tests and commit the slice.

## Task 2: Tenant-scoped API and audit

- Add failing API tests for authorization, same-job enforcement, body validation, atomic rollback,
  replay, and changed-body idempotency conflict.
- Add the job-scoped route with stable public errors and safe batch audit metadata.
- Run API tests, Ruff, and the full relevant regression suite; review the diff and create a PR.

## Delivery boundary

- Do not add a browser selection UI in this slice.
- Do not publish QuestionVersions or soften `blocked`/`warning` semantics.
- Do not store provider payloads, prompts, secrets, or teacher constraints in batch idempotency data.
