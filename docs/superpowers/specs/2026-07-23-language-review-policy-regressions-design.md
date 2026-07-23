# Language and Review-Policy Regressions Design

## Purpose

Complete the language portion of verification hardening issue #83 without changing validation policy or teacher workflow. E1 and E2 need deterministic accepted-answer/form and normalization-conflict coverage. E3 and E4 need deterministic grammar, reading-material, rubric, and mandatory-human-review coverage.

## Selected design

The existing `test_verification_corpus.py` remains the only corpus adapter. Four new JSON files (`e1.json` through `e4.json`) contain declarative case IDs, named scenarios, expected validation status, expected stable finding codes, and—only for E3/E4—the expected `pending_review` teacher state. Test-only builders transform a scenario into one of the existing candidate fixtures and deterministic Grader doubles, then call the real `run_candidate_verification` service.

This keeps the corpus from reimplementing E validators and makes `make verification-regression` the one operator command. Unknown scenarios fail explicitly instead of falling back to a valid candidate. The output adds per-type Finding Code totals and rejects any corpus with fewer than 20 cases.

## Alternatives considered

1. Add a second, language-only test command. Rejected: it breaks the single #83 regression command and creates a second test adapter.
2. Put full candidate JSON in every corpus record. Rejected: duplicative, harder to review, and likely to expose instructional content in failure diagnostics.
3. Add production “teacher review required” findings. Rejected: review is already enforced by draft state and explicit teacher acceptance; a new finding changes policy rather than proving it.

## Acceptance criteria

- E1/E2/E3/E4 each contain at least 20 deterministic cases.
- E1/E2 include valid variants, missing/invalid inputs, normalized duplicates, and Grader failures where the existing verifier probes them.
- E3 includes clean language, grammar warnings, malformed/dependency checker output, accepted-answer variants, and `pending_review` after every validation run.
- E4 includes valid passages/rubrics, missing/oversized/mismatched material, normalized/overlapping points, score errors, Grader failures, and `pending_review` after every validation run.
- The runner reports only case IDs, statuses, teacher state, and stable Finding Codes; no question body, accepted answer, passage, rubric phrase, or raw provider error.
- No schema, migrations, production verifier logic, acceptance endpoint, #42 metric, or #43 governance changes are made.

## Review

The user-defined Release Candidate plan already selected this PR 3 scope and required E3/E4 to remain teacher-reviewed. This document records that approved boundary; no additional behavior is introduced beyond deterministic regression evidence.
