# Student Appeals and Corrections Design

## Scope

This Issue #7 slice adds student review appeals and teacher-approved correction
attempts. It builds on immutable grading runs, review tasks, decisions, and
per-attempt publication records. Review analytics remains a separate slice.

## Goals

- Let a student appeal only a grade that has already been published to them.
- Let an assigned teacher approve or reject an appeal with an append-only,
  versioned decision and audit event.
- Create a correction attempt only after approval; preserve the original
  attempt, answers, grading runs, review decisions, and publication unchanged.
- Route correction grading through the existing review and publication controls.
- Keep students limited to their own appeal status and published correction
  result, while teachers retain the full evidence trail.

## Data Model

`ReviewAppeal` is attached to the original `StudentAttempt` and has the
student's reason, status (`open`, `approved`, `rejected`, or `superseded`), a
version, decision reason, deciding teacher, and timestamps. There may be one
open appeal per original attempt.

`CorrectionAttempt` links the original attempt to a new `StudentAttempt` with
an incremented attempt number. Its answers are separate `AttemptAnswer` rows;
it never updates the original answer or grading history. The correction uses
the same assignment item and question-version snapshots as the original.

## Flow

1. After a teacher publishes an attempt, its student may create one open
   appeal with a non-empty reason.
2. An assigned teacher approves or rejects that appeal using its current
   version. Approval creates the correction attempt and marks the appeal
   approved; rejection records the decision reason.
3. The student edits and submits correction answers. Existing grading creates
   immutable runs and review tasks for the correction attempt.
4. Teachers resolve any correction review tasks and publish the correction
   attempt separately. Students can see both published result records without
   any unpublished scores or teacher evidence.

## Authorization and Errors

- Students can read/create appeals only for their own published attempts.
- Teachers can read/decide appeals only for classes they teach.
- Missing or inaccessible resources return `404`.
- Empty student appeal reason, empty teacher rejection reason, and invalid
  state transitions return `422`.
- Stale appeal versions, a duplicate open appeal, and repeated decisions return
  `409`.

## API

- `POST /v1/student/attempts/{attempt_id}/appeals`
- `GET /v1/student/appeals`
- `GET /v1/review-appeals?class_id=&assignment_id=&status=`
- `POST /v1/review-appeals/{appeal_id}/decisions`

The existing student assignment endpoint will expose correction-attempt status
and published correction summaries, but not their rules, grading signals, or
unpublished scores.

## Testing

Cover published-only appeal creation, tenant and class authorization, mandatory
reasons, duplicate/open appeal and stale-version conflicts, independent
correction answer storage, correction grading/review/publication flow, and
student response privacy before publication.
