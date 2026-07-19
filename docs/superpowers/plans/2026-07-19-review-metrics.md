# Review Metrics Implementation Plan

**Goal:** Add teacher-scoped review duration, score-adjustment, and reason metrics.

1. Add failing API tests for tenant/class filtering, time ranges, zero-result ranges, durations, adjustment rate, and reason counts.
2. Add `review_metrics` service aggregation over resolved `ReviewTask` and immutable `ReviewDecision` records.
3. Add `GET /v1/review-metrics` teacher route with optional dates, class, and assignment filters.
4. Run Ruff, API tests, Compose config, then merge and close Issue #7 after publication.
