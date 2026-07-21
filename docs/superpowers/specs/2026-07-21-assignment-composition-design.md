# Multi-Question Assignment Composition Design

**Issue:** #30 — Support multi-question, multi-type assignment composition with correct subject tagging.

## Goal

Allow teachers to create and revise draft English or mathematics assignments containing an ordered, non-duplicated set of published question versions, then publish a frozen student-safe arrangement.

## Root Cause

The current web page hard-codes `mathematics`, exposes one question selector, and calls the API in two requests: create an assignment, then add one item at position 1. The API accepts that caller-supplied position without checking duplicate questions, position continuity, or question-subject compatibility. It has no full-draft update operation. This permits partial drafts and cannot model a real multi-question assignment.

## Chosen Design

The assignment API will accept a complete ordered `question_version_ids` list whenever a draft is created or updated. It will resolve every ID to a tenant-local published version, validate that all types belong to the requested assignment subject, reject empty or repeated IDs, and write positions `1..n` within the same transaction as the assignment mutation. The existing individual-item endpoint remains compatible but receives the same subject, duplicate, and position protections.

Draft updates replace the complete item set and may change title, due time, and late-submission policy. Published assignments reject all composition changes, retaining the current freeze boundary. Student retrieval already orders items by `position`; no student API or answer persistence changes are needed.

## Subject Rules

- `mathematics` accepts only `M1` and `M2`.
- `english` accepts only `E1`, `E2`, `E3`, and `E4`.
- Unknown subjects, an empty list, duplicate IDs, unpublished/foreign versions, and subject mismatches are stable 422 validation errors.
- The service computes positions from list order; clients do not send positions for full composition.

## API Boundary

`POST /v1/assignments` adds a required `question_version_ids: list[UUID]`. It creates the assignment and every item atomically.

`PUT /v1/assignments/{assignment_id}` accepts the same assignment fields and complete ordered list. It is draft-only and replaces all items in one transaction. It returns the draft ID, status, normalized item summaries, and position order.

Teacher question-list responses include `max_score`, read from the published version rule with a safe default of `1`, so assignment composition can display totals without exposing full rules or answers.

## Teacher Experience

The teacher first selects English or mathematics. The available-question list is limited to published versions of that subject. Selecting adds a version once; the composition list shows title, prompt, type, policy version, points, and up/down/remove controls. The page reports item count, total score, and a type distribution. A preview mirrors the student-visible prompt and order but omits answers and rule JSON.

Clicking **保存编排** sends the full ordered selection. A draft can be reopened and revised until publication. Empty selections cannot be saved or published. The client pre-validates duplicates and subject mismatch, but the API is authoritative.

## Verification

- API tests cover atomic create/update, subject mismatch, duplicate/empty input, contiguous positions, draft-only updates, and published freeze behavior.
- Vitest covers composition state, totals, distribution, reorder/remove operations, and BFF request payloads.
- Playwright creates an English assignment with at least five questions from three English types, plus a mathematics assignment containing M1 and M2; it verifies student order and subject boundaries.

## Non-Goals

This change does not add cross-subject assignments, drag-and-drop, assignment version cloning, or changes to student answer synchronization. Up/down controls provide accessible, deterministic reordering without introducing an additional Sortable dependency.
