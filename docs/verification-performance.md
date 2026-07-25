# Verification performance report contract

## Purpose

`verification-performance-v1` creates a repeatable, non-blocking performance baseline for the production candidate-verification path.

The initial report measures the real `run_budget_aware_candidate_verification` wrapper with synthetic curriculum data, an in-memory SQLite database and a deterministic, network-free Grader implementation. It does not use real students, classes, assignments, prompts or provider traffic.

## Matrix

The version 1 matrix contains 18 benchmark units:

- question types: M1, M2, E1, E2, E3 and E4;
- load buckets: small, medium and large;
- one stable case identifier per question-type and bucket pair.

Each candidate contains synthetic padding so its measured capacity bucket matches `verification-capacity-v1`. The padding and candidate content are never included in the report.

## Production contracts

The report records the active versions used by the benchmark:

- validator: `verification-v12`;
- ruleset: `rules-v12`;
- capacity rules: `verification-capacity-v1`;
- timeout budget: `verification-budget-v1`.

A matrix case fails if the production wrapper returns a status other than its declared expected status, if its capacity bucket changes, or if the shared timeout budget does not complete normally.

## Measurement protocol

The default local command is:

```bash
make verification-performance
```

Optional parameters are available through Make variables:

```bash
make verification-performance WARMUPS=2 ITERATIONS=10 SEED=119 OUTPUT=artifacts/verification-performance
```

Version 1 uses:

- one process and concurrency of one;
- a fixed matrix order derived from the configured seed;
- `perf_counter_ns` as the monotonic high-resolution clock;
- one warmup and five measured runs per case by default;
- R-7 linear interpolation for P50, P95 and P99;
- no outlier removal;
- every measured success, unexpected status and execution failure retained in the report.

A failed sample is classified only as `execution_error` or by the stable validation status. Exception messages are not recorded.

## Outputs

The command writes:

```text
artifacts/verification-performance/verification-performance-v1.json
artifacts/verification-performance/verification-performance-v1.md
```

The JSON report contains:

- report and matrix versions;
- a SHA-256 digest of the de-identified matrix metadata;
- source revision;
- validation contract versions;
- warmup, iteration, seed, clock, percentile and failure policies;
- Python, OS, architecture, CPU and runner metadata;
- per-case candidate byte count, sample count, status counts and failure count;
- minimum, P50, P95, P99 and maximum latency in milliseconds;
- throughput in cases per second.

The Markdown report presents the same contract and measurements in a reviewable table.

## Privacy and safety

The report writer fails closed when a report contains fields associated with educational content or internal diagnostics. Reports must not contain:

- prompts, reading material or expected answers;
- grading rules or verification assertions;
- request payloads or exception text;
- internal or external URLs;
- student, teacher, class, assignment or submission data;
- raw provider or dependency responses.

Only synthetic case identifiers, numeric payload observations, stable statuses and environment metadata are allowed.

## Current limitations

Version 1 does not yet provide:

- baseline-versus-candidate comparison;
- a GitHub Actions artifact workflow;
- blocking latency or throughput thresholds;
- multi-process or concurrent-load measurements;
- real PostgreSQL, Grader or LanguageTool fault-injection evidence;
- release-environment acceptance evidence for #31.

Those remain follow-up slices in #119 and #108. Performance thresholds must not become protected release gates until repeated reports demonstrate stable variance and an agreed comparison policy.
