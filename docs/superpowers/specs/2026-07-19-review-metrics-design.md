# Review Metrics Design

Add a teacher-scoped `GET /v1/review-metrics` endpoint with optional `from`,
`to`, `class_id`, and `assignment_id` filters. The endpoint aggregates only
review tasks in classes taught by the current teacher and filters by final
decision time.

It returns handled-task count, average and median duration from task creation
to final decision, score-adjustment rate, and top reason counts grouped by
task reason and teacher decision reason. It returns no student answers, rules,
signals, or other grading evidence. Empty ranges return zero counts and empty
reason lists.
