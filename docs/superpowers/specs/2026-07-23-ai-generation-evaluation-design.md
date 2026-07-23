# AI Generation Evaluation Design

## Goal

Deliver the first independently useful slice of Issue #42: a reproducible,
offline regression gate for AI-generated questions. It evaluates versioned,
non-production candidate snapshots against the same generation contracts and
candidate-verification rules used by the API, and it produces both machine- and
human-readable reports for CI.

This slice establishes the metric definitions and dimensional keys that the
later teacher-feedback dashboard will consume. It deliberately does not add a
production endpoint, database table, dashboard, shadow traffic, or provider
call.

## Scope and Boundaries

The evaluator lives in the API package because it needs the production
generation contract and question-verification service. It is an offline module,
not a new service and not a generic prompt-evaluation framework. A generic
framework would still need adapters for the project's curriculum snapshot,
generation plan, validation findings, and teacher-review semantics, while the
native evaluator preserves the actual production boundary.

The evaluator accepts only repository-controlled fixtures and optional
recorded candidate snapshots. It never reads a production database and never
calls an AI provider. CI results are therefore deterministic and do not depend
on model availability, cost, supplier changes, or sampling randomness.

## Versioned Golden Dataset

The golden dataset is a strict, versioned manifest. Every case has:

- a stable case ID and dataset version;
- `profile`, `grade`, `subject`, `question_type`, and difficulty-band slice
  keys;
- a curriculum objective snapshot, generation-plan item, expected constraints,
  and forbidden patterns;
- a recorded candidate snapshot and reproducibility metadata: provider, model
  ID, Prompt version, curriculum revision, parameters, and seed;
- expected validation outcomes and metric assertions; and
- required review attestations for the question type.

The fixture schema rejects extra identity-bearing fields. It has no tenant,
class, teacher, student, student-answer, or free-form personal-data field.
All examples are original or authorised material.

For M1 and M2, a released case needs a mathematics-review attestation that
identifies the checked standard answer and common-error coverage without
claiming that code performed the human review. For E3 and E4, a released case
needs two independent review records and, when they disagree, one recorded
adjudication. The runner verifies that these records are structurally complete;
it cannot and must not invent teacher approval.

## Execution and Metric Semantics

For every case the runner:

1. validates the fixture and reproducibility metadata;
2. rebuilds the production generation-contract input from the stored snapshot;
3. runs production candidate verification in an isolated session;
4. compares validation findings and candidate fields with the case's expected
   constraints; and
5. records a case result with stable failure codes and the case ID.

The report calculates numerators and denominators globally and for every
profile, grade, subject, question type, difficulty, model, and Prompt slice.
Initial offline metrics are contract/schema pass rate, mathematics answer error
rate, English answer/scoring-point completeness, grade/scope mismatch rate,
exact-or-semantic duplicate rate, and safety-blocking result. Cases that cannot
be evaluated are failures; they are never omitted from a denominator.

The runner also records the supplied per-attempt cost and duration metadata.
Those values are informational in the offline report until a later online slice
can aggregate observed production attempts and teacher decisions.

## Thresholds, Baselines, and Failures

Thresholds are versioned data next to the dataset, never Python constants. A
threshold is either a minimum pass rate or a maximum error rate and can target a
specific slice. A release must satisfy both global thresholds and every
applicable slice threshold.

A baseline report can be supplied for comparison only when its dataset version
and complete slice key set match the current run. Any missing baseline,
unrecognised model or Prompt version, missing expected slice, malformed input,
insufficient sample count, failed report write, failed assertion, or regression
beyond its threshold makes the process return a non-zero exit status. The
runner still writes the JSON and Markdown report before returning failure.

This prevents a high overall average from hiding degradation in a low-grade or
specific-question-type slice.

## Command and CI

`make ai-evaluation-report` runs the evaluator with the repository golden
dataset, threshold configuration, and a caller-selected output directory. It
writes `evaluation-report.json` for tooling and `evaluation-report.md` for
human review.

CI adds an `ai-evaluation` job after the ordinary Python checks. The job uses
only local fixtures, runs the Make target, and uploads the report artifacts
even when the gate fails. It does not introduce a model-provider credential or
network dependency.

## Verification

Tests cover a passing representative case for M1, M2, E1, E2, E3, and E4, plus
the following negative cases:

- an incorrect mathematics answer;
- a candidate outside the allowed grade or curriculum scope;
- an exact or semantic duplicate;
- missing required human-review records;
- a missing required slice or an insufficient sample count; and
- a baseline regression.

Each negative case must produce a stable report entry and a non-zero process
status. Tests also prove the reports exclude prohibited identity and student
answer fields, and that the CI workflow invokes the one supported Make target.

## Deferred Work

The second Issue #42 slice will add read-only online summaries from existing
`GenerationAttempt`, validation-run, and generated-question review-decision
records. It will expose direct-accept, modified-accept, rejection-reason,
cost, latency, and post-publication metrics using the exact definitions and
slice keys established here. Shadow/canary routing belongs to that production
slice, after the offline gate has established a reliable baseline.
