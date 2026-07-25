# Verification release evidence contract

## Purpose

`verification-release-evidence-v1` provides release-candidate evidence for candidate-verification capacity gating and dependency recovery in an isolated, real-service environment.

The first slice runs the production `run_budget_aware_candidate_verification` wrapper against PostgreSQL and the real HTTP Grader/LanguageTool stack. It uses only synthetic curriculum, teacher and candidate records. It does not use real student, teacher, class, assignment or question-bank data.

## Environment

The dedicated Compose definition is `infra/release-evidence/compose.yaml`. It starts:

- PostgreSQL 16;
- the repository LanguageTool image;
- the repository Grader image configured to call that LanguageTool service.

The Core API code runs from the checked-out package on the GitHub runner and connects to the isolated PostgreSQL and Grader ports. Alembic upgrades the database to the production schema before scenarios execute.

Every repetition uses a unique Compose project and a fresh PostgreSQL volume. The runner performs at least two complete repetitions and removes containers and volumes after each repetition.

## Representative scenarios

### Capacity candidate bytes

The runner creates a synthetic E3 candidate larger than the `verification-capacity-v1` total-byte limit. The production wrapper receives an intentionally unreachable Grader endpoint.

The scenario succeeds only when:

- the immutable validation run is `blocked`;
- `candidate_capacity_limit_exceeded` is present;
- the capacity bucket is `oversize`;
- no `QuestionVersion` is created;
- validation completes without contacting the unreachable Grader.

### Language dependency recovery

The runner creates a normal synthetic E3 candidate and uses the real HTTP Grader. It stops LanguageTool, validates the candidate, restarts LanguageTool and validates the same revision again.

The scenario succeeds only when:

- the outage run is `blocked`;
- the recovery run is `passed`;
- the two runs have different identities and independent budgets;
- the old blocked run remains byte-for-byte immutable at the evidence level;
- the recovery budget finishes with `completed`;
- no `QuestionVersion` is created.

This first slice proves dependency failure and recovery. Explicit connect/read timeout injection for all four dependency categories remains follow-up work in Issue #122.

## Evidence outputs

The command is:

```bash
make verification-release-evidence
```

It writes:

```text
artifacts/verification-release-evidence/verification-release-evidence-v1.json
artifacts/verification-release-evidence/verification-release-evidence-v1.md
```

The report records:

- source revision;
- validator, ruleset, capacity and budget contract versions;
- PostgreSQL version and service image identifiers;
- repetition and scenario status;
- stable Finding codes;
- `QuestionVersion` deltas;
- old-run immutability and fresh-budget completion;
- container and volume cleanup results.

## Privacy

The report writer fails closed when a field name or value can expose educational content or infrastructure diagnostics. Reports must not contain:

- prompts, reading material, expected answers, rules or verification assertions;
- request payloads, exception text or tracebacks;
- URLs, database connection strings, tokens, cookies or authorization headers;
- student, teacher, class, assignment or submission data.

Docker and migration output remains operational CI logging; the uploaded JSON and Markdown artifacts contain only stable, de-identified evidence.

## Workflow

`.github/workflows/verification-release-evidence.yml` supports `workflow_dispatch` and relevant pull-request changes. Pull-request runs are observational and non-blocking; manual and release-candidate invocations fail when the evidence runner detects an infrastructure failure or product regression.

Artifacts use the source SHA in their name and are retained for 14 days.

## Current limitations

Version 1 does not yet provide:

- controlled connect/read timeout injection for Normalizer, Grader, LanguageTool and Similarity;
- every total-budget stage boundary in the real-service environment;
- a reusable RC workflow callable from the milestone signing pipeline;
- full OIDC browser acceptance.

Those remain follow-up slices in Issue #122. Performance threshold policy remains separate from this evidence contract.
