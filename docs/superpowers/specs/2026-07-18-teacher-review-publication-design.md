# Teacher Review, Audit, and Grade Publication Design

## Scope

This document specifies the first delivery slice for Issue #7: a teacher review
queue, immutable review decisions, and controlled grade publication. Student
appeals, corrections, and operational analytics remain follow-up slices.

The slice builds on the immutable `GradingRun` and `GradingSignal` records
introduced for English grading. Those records remain the system's original
automatic-grading evidence and are never updated by a teacher action.

## Goals

- Give an assigned teacher a filtered queue of answers that require a decision.
- Show the submitted answer, rule and scoring evidence, system recommendation,
  confidence, and review reason for each task.
- Record a teacher confirmation, score change, regrade request, or rule-problem
  report as an immutable decision with a mandatory reason for score changes.
- Prevent automatic publication of subjective or review-required work.
- Keep grades, answers, and automatic-grading evidence private from students
  until the teacher publishes them.
- Reject cross-tenant, unassigned-teacher, duplicate, and stale concurrent
  operations.

## Non-goals

- Student appeal requests, correction attempts, and correction-versus-original
  answer storage.
- Review-time, score-change-rate, and reason analytics endpoints.
- A dedicated web UI; this slice provides stable API contracts for that UI.
- Mutating a `GradingRun`, `GradingSignal`, or its snapshots after submission.

## Data Model

### ReviewTask

One task is created for every submitted answer's latest automatic result. It
carries the assignment, attempt answer, current grading run, queue reason,
status, and an optimistic-lock version. A unique open-task constraint on the
attempt answer prevents duplicate active dispositions. The normal teacher view
defaults to manual work, while deterministic `auto_confirmation` tasks remain
available to the batch-confirm operation.

Queue reasons are `needs_review`, `auto_confirmation`, `regrade_requested`,
and `rule_problem`.
Statuses are `open`, `resolved`, and `superseded`. Regrading creates a new
automatic `GradingRun`, supersedes the old task, and opens a replacement task
for the replacement grading result.

### ReviewDecision

Each teacher action creates an append-only decision row attached to a task:

- `confirm` accepts the automatic result.
- `adjust_score` records the original score, new score, and required reason.
- `request_regrade` records the required reason and marks the task for a new
  grader execution.
- `report_rule_problem` records the required reason without changing the score.

The row includes the actor, decision time, original score, final score, reason,
and a snapshot of the grading-run identifier and decision version. `AuditLog`
receives a matching domain event for each decision.

### GradePublication

Publication is recorded per submitted attempt. It carries a status of `draft`
or `published`, the publishing teacher, and timestamp. An attempt can be
published only when every answer is eligible:

- deterministic, non-subjective automatic results must be batch-confirmed;
- `needs_review` and subjective results require a resolved review task;
- a task under regrade is not eligible.

The published student result is assembled from the final teacher decision when
one exists, otherwise the automatic grading run. The rule and evidence remain
teacher-only.

## API Boundaries

Teacher routes are tenant- and class-membership-scoped:

- `GET /v1/review-tasks` lists open tasks and supports `class_id`,
  `assignment_id`, `subject`, `question_type`, and `reason` filters.
- `GET /v1/review-tasks/{task_id}` returns student answer, question prompt,
  rule/point snapshots, automatic evidence, signals, confidence, and decisions.
- `POST /v1/review-tasks/{task_id}/decisions` accepts a decision action,
  optimistic-lock version, optional score, and reason. Score adjustments and
  rule/regrade actions require a non-empty reason.
- `POST /v1/assignments/{assignment_id}/review-tasks/batch-confirm` confirms
  only eligible deterministic automatic tasks for that teacher's class.
- `POST /v1/assignments/{assignment_id}/attempts/{attempt_id}/publish-results`
  publishes an eligible attempt.

Student assignment and submission responses expose no score, correct answer,
or grading evidence before the attempt's publication record exists. After
publication, they expose only the final score, maximum score, and approved
student-safe feedback; teacher-only rule snapshots and signals remain hidden.

## Processing Flow

1. Submission persists automatic runs and creates a disposition task for every
   result in the same transaction: `auto_confirmation` for deterministic work
   and `needs_review` for manual work.
2. A teacher lists and filters tasks in classes they teach, then opens a task
   detail using the immutable grading evidence.
3. The teacher submits one decision with the task's version. A stale version or
   already-resolved task returns `409` without writing a second decision.
4. Eligible deterministic tasks may be confirmed in a batch. Subjective and
   review-required tasks are rejected from that endpoint.
5. Once all answers in an attempt are eligible, a teacher publishes its final
   results. Student responses then reveal only the bounded published view.

## Error Handling and Authorization

- Missing, cross-tenant, or non-assigned-class resources return `404`.
- Invalid transitions, ineligible batch confirmation, and premature publication
  return `409`.
- Score adjustments outside the grading run's `[0, max_score]` range and empty
  mandatory reasons return `422`.
- The task version is required for any mutating decision and prevents two
  teachers from silently overwriting each other.
- Repeated requests with a resolved task cannot create another final decision.

## Testing

Tests cover:

- queue creation, every supported filter, detail evidence, and teacher class
  authorization;
- confirmation, score changes, reason validation, immutable decision/audit
  records, duplicate processing, and optimistic-lock conflicts;
- deterministic-only batch confirmation and subjective-result rejection;
- publishing eligibility and student visibility before and after publication;
- cross-tenant and unassigned-teacher attempts for all read and write routes.

## Follow-up Slices

The next Issue #7 slices add student appeal requests and status, correction
answers stored independently from originals, then review throughput and outcome
statistics. They consume `ReviewTask`, `ReviewDecision`, and `GradePublication`
without changing their audit guarantees.
