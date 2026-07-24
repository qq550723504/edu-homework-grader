# Candidate verification budget contract

## Purpose

`verification-budget-v1` adds one monotonic timeout budget to each production candidate-validation attempt. The budget complements `verification-capacity-v1`:

```text
candidate revision
→ deterministic capacity preflight
→ budget-aware duplicate and dependency work
→ immutable validation run
→ teacher review gate
```

Capacity limits bound the amount of work. The timeout budget prevents a slow or unavailable dependency from allowing later dependency calls to continue indefinitely.

## Versioned contract

| Component | Version |
| --- | --- |
| Core deterministic validator | `verification-v8` / `rules-v8` |
| Capacity-aware wrapper | `verification-v9` / `rules-v9` |
| Budget-aware production wrapper | `verification-v10` / `rules-v10` |
| Capacity rules | `verification-capacity-v1` |
| Timeout budget rules | `verification-budget-v1` |

The configured total budget is read from `VERIFICATION_TOTAL_TIMEOUT_SECONDS`. The setting is a positive finite value with a bounded release range; its default is 30 seconds.

## Monotonic deadline

The budget uses a monotonic clock. It never derives expiry from wall-clock timestamps, timezone changes, NTP corrections or database time.

A test can inject a fake monotonic clock, so exact-boundary and timeout behavior does not rely on `sleep`.

The budget is terminal:

- after `total_timeout`, later dependency calls raise the original total-timeout classification;
- after `dependency_timeout`, later dependency calls raise the original dependency classification;
- the wrapper never invokes the delegate again after either terminal state.

## Stable stages and dependencies

Version 1 recognizes these stage identifiers:

- `capacity_preflight`
- `duplicate_check`
- `normalizer`
- `grader`
- `language`
- `similarity`
- `persist`

It recognizes these dependency identifiers:

- `normalizer`
- `grader`
- `language`
- `similarity`

The initial production integration checks the budget before and after Normalizer, Grader and Similarity calls, and again before final persistence. Additional explicit duplicate-query and LanguageTool stage boundaries remain follow-up work in #110.

## Findings

| Condition | Stable Finding |
| --- | --- |
| Shared budget exhausted | `verification_total_timeout` |
| MathJSON Normalizer timeout | `normalizer_timeout` |
| Grader timeout | `grader_timeout` |
| Language dependency timeout | `language_timeout` |
| Semantic-similarity timeout | `similarity_timeout` |

All timeout Findings are `blocked`. A blocked candidate cannot be accepted individually or in a batch and cannot create a formal `QuestionVersion`.

A recognized timeout may coexist with an older generic probe-failure Finding produced inside the core deterministic validator. The stable timeout Finding is the operational classification. Later core cleanup may remove redundant generic Findings without changing this public contract.

## De-identified evidence

A total-timeout Finding may persist only:

```json
{
  "ruleset_version": "verification-budget-v1",
  "stage": "grader",
  "total_budget_seconds": 30.0
}
```

A dependency-timeout Finding may persist only:

```json
{
  "ruleset_version": "verification-budget-v1",
  "dependency": "grader"
}
```

The internal budget signal contains version, configured total budget, terminal status and stable terminal classification. The teacher API exposes only:

- `availability`
- `version`
- `total_budget_seconds`
- `status`

The following must never appear in Finding evidence, feature summaries, API output or audit metadata:

- prompt, explanation, reading material or expected answer;
- student, class, assignment or submission data;
- raw MathJSON, rule JSON or verification assertions;
- internal URLs, request payloads or HTTP exception text;
- exact start time, exact elapsed trace or provider diagnostics.

## Failure behavior

```text
budget available
→ dependency call may start
→ dependency succeeds within current stage boundary
→ next budget check

budget exhausted before a dependency call
→ delegate is not called
→ stable blocked timeout evidence
→ immutable Validation Run

HTTP dependency timeout
→ stable dependency classification
→ terminal budget
→ later dependency calls are not started
→ immutable blocked Validation Run
```

The wrapper always preserves the current revision ID and content hash in the immutable validation run. Revision mismatch is rejected before budget work starts.

## Current limitations

This contract does not yet claim:

- hard cancellation of arbitrary Python or database work already executing;
- a separate timeout value for every dependency;
- independent LanguageTool timeout classification when the Grader service does not expose it;
- P50, P95 or P99 latency objectives;
- throughput or concurrency objectives;
- release-environment fault-injection completion.

Those items remain in #110 and #108. Performance evidence must be generated before any percentile threshold becomes a protected release gate.
