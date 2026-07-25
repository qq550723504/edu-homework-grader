# Verification release evidence contract

## Purpose

`verification-release-evidence-v1` provides release-candidate evidence for candidate-verification capacity gating, stable dependency-timeout classification and dependency recovery in an isolated, real-service environment.

The runner executes the production `run_budget_aware_candidate_verification` wrapper against PostgreSQL and the real HTTP Grader/LanguageTool stack. It uses only synthetic curriculum, teacher and candidate records. It does not use real student, teacher, class, assignment or question-bank data.

## Environment

The dedicated Compose definition is `infra/release-evidence/compose.yaml`. It starts:

- PostgreSQL 16;
- the repository LanguageTool image;
- a containerized, payload-blind LanguageTool response-stall proxy;
- the repository Grader image configured to call LanguageTool through that proxy.

The Core API code runs from the checked-out package on the GitHub runner and connects to the isolated PostgreSQL and Grader ports. Alembic upgrades the database to the production schema before scenarios execute.

Every repetition uses a unique Compose project and a fresh PostgreSQL volume. The runner performs at least two complete repetitions and removes containers and volumes after each repetition.

The Compose project uses an isolated private `/24` bridge. The runner accepts only a private IPv4 `/24` for this network, and before each repetition verifies that four distinct unassigned addresses terminate as `ConnectTimeout` without using environment proxies. These targets are reserved for the Normalizer, Grader, LanguageTool and Similarity connection-timeout scenarios. The CIDR may be overridden through `RELEASE_EVIDENCE_CONNECT_TIMEOUT_NETWORK`; network addresses are never written to the evidence reports.

## Scenario catalog v5

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

### Normalizer, Grader and Similarity read timeouts

The runner places a bounded local HTTP fault proxy between the production Core API wrapper and the real Grader. For each dependency category, the proxy accepts one request and deliberately withholds the response longer than the configured Core API Grader timeout. The same proxy then switches to forwarding mode for a fresh recovery run against the real service.

The three scenarios use production-shaped candidates:

- an M2 candidate reaches MathJSON Normalizer first;
- an M1 candidate reaches the core Grader first;
- an M1 candidate with one distinct synthetic peer reaches Semantic Similarity first.

Each scenario succeeds only when:

- the outage run is `blocked` with `normalizer_timeout`, `grader_timeout` or `similarity_timeout` respectively;
- the budget records `dependency_timeout` and the correct terminal dependency;
- exactly one delegate request reaches the stalled proxy and no new request starts after terminal timeout;
- a fresh run forwards to the real Grader and completes with `passed` and a `completed` budget;
- the old blocked run remains immutable;
- no `QuestionVersion` is created.

The fault proxy never records request bodies, candidate content, network locations or exception text in the evidence artifact.

### Normalizer, Grader and Similarity connect timeouts

For each category, the runner first proves the isolated bridge's network primitive with a separate unassigned preflight address. The outage run then uses a real `HttpGraderClient` targeting that category's distinct unassigned bridge address and a 250 ms connect deadline. It must fail closed with the category-specific stable Finding and a `dependency_timeout` budget signal. A separate recovery run uses the normal real Grader service and must pass with a completed budget.

Each scenario also requires a distinct immutable blocked run and zero `QuestionVersion` creations. The evidence contains only the stable statuses and Finding codes; it does not contain target addresses, URLs, request payloads or exception details.

### LanguageTool connect timeout

The runner starts a second real Grader whose LanguageTool endpoint is a distinct unassigned address on the evidence bridge. The outage run calls that Grader and must be blocked with `language_timeout`; recovery uses the normal real Grader/LanguageTool stack and must pass with a fresh completed budget. This proves the internal LanguageTool connection boundary without replacing either service with a mock.


### Explicit LanguageTool read timeout

A containerized fault proxy sits between the real Grader and LanguageTool. In stall mode it accepts exactly one `/v2/check` request and withholds the response longer than `LANGUAGETOOL_TIMEOUT_SECONDS`; in forward mode it relays a fresh recovery request to the real LanguageTool service.

The scenario succeeds only when:

- the outage run is `blocked` with `language_timeout`;
- the shared budget records `dependency_timeout` and terminal dependency `language`;
- exactly one LanguageTool request reaches stall mode and no additional request starts after terminal timeout;
- a fresh run forwards through the same proxy and completes with `passed` and a `completed` budget;
- the prior blocked run remains immutable;
- no `QuestionVersion` is created.

The proxy control plane exposes only mode and aggregate call counts. It does not persist request bodies, candidate content, upstream locations or exception text.

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
- validator, ruleset, capacity, budget and timeout-fault contract versions;
- PostgreSQL version and service image identifiers;
- repetition and scenario status;
- stable Finding codes and dependency call-count buckets;
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

- every total-budget stage boundary in the real-service environment;
- a reusable RC workflow callable from the milestone signing pipeline;
- full OIDC browser acceptance.

Those remain follow-up slices in Issue #122. Performance threshold policy remains separate from this evidence contract.
