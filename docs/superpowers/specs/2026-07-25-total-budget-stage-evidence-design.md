# Total-budget stage evidence design

## Goal

Extend `verification-release-evidence-v1` with deterministic, real-service evidence
for the four remaining shared-budget boundaries in Issue #122:

- `capacity_preflight`;
- `duplicate_check`;
- a dependency-call boundary;
- `persist`.

Each scenario must prove the production budget-aware wrapper creates a stable,
immutable blocked validation run with `verification_total_timeout`, does not create a
`QuestionVersion`, and leaves the isolated environment clean after two repetitions.

## Approach

The release-evidence runner will use the production wrapper's existing injectable
monotonic `clock` argument. A small scenario-local clock advances only at the
selected stage boundary. PostgreSQL, the Core API code, and all applicable Grader /
LanguageTool services remain real; no production wrapper, persistence function, or
HTTP client is monkeypatched.

This makes expiry deterministic without depending on CI scheduling, `sleep`, or a
machine-specific performance threshold. Production requests continue to use the
normal monotonic clock.

## Scenario behavior

| Scenario | Trigger | Required evidence |
| --- | --- | --- |
| Capacity preflight | Clock is expired before capacity evaluation. | Stable timeout at `capacity_preflight`; no dependency call. |
| Duplicate check | Clock advances after capacity preflight and before duplicate work. | Stable timeout at `duplicate_check`; no downstream dependency call. |
| Dependency boundary | Clock advances immediately before the selected production dependency call. | Stable timeout at that dependency stage; no request reaches the Grader. |
| Persistence | Clock advances after successful validation and before the final persistence check. | Stable timeout at `persist`; blocked run is persisted with the terminal signal. |

All scenarios use synthetic candidate data. Reports will retain only scenario IDs,
stable stages, finding codes, dependency call-count buckets, run immutability,
QuestionVersion deltas, recovery/cleanup results, and version identifiers.

## Changes

1. Add a scenario-local, deterministic clock/control point to the release-evidence
   runner, wired only through the existing production `clock` parameter.
2. Add four total-budget scenarios and report assertions to the current scenario
   catalog. Reuse the existing real-service fixture, cleanup, de-identification, and
   immutable-run checks.
3. Add focused unit tests for the control point and report contracts, then run the
   complete real release-evidence command twice.
4. Update `docs/verification-release-evidence.md`, including the scenario catalog
   version and removal of the completed total-budget limitation.
5. Update Issue #122 after CI has verified the merged PR; do not close it because
   remaining capacity dimensions and a reusable RC workflow are still outstanding.

## Error handling and safety

- Treat an unexpected stage, a live dependency call where none is permitted, missing
  timeout Finding, mutable blocked run, QuestionVersion creation, or cleanup failure
  as a product regression.
- Preserve the current report's fail-closed de-identification rules. Do not add
  timestamps, URLs, candidate text, request bodies, or exception diagnostics.
- Do not modify the production timeout setting, cancellation behavior, or external
  API contract.

## Validation

- Focused unit and report-contract tests must pass.
- Compose configuration must validate.
- The real runner must produce two successful repetitions with all scenarios and
  cleanup successful.
- GitHub CI, documentation integrity, AI evaluation, and performance-artifact checks
  must pass before the PR is made ready or merged.
