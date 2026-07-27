# Generator v4 Review Gate Design

## Goal

Make the generator-v4 promotion checks exercise the E1 policy-v2 contract and
make the offline evaluation fixture fail closed when the active Prompt version
is not represented by its policy and records.

## Scope

- The controlled live Provider acceptance test uses the active generation
  Prompt version and, for E1, asserts policy version `"2"` and validates the
  returned rule with the platform policy validator.
- The offline release-gate fixture represents `generator-v4` and a regression
  test requires its approved Prompt version and every fixture record to match
  `GENERATION_PROMPT_VERSION`.
- The fixture remains deterministic test data. It is not production canary
  evidence and cannot replace the separate operational evaluation export.

## Non-goals

- Do not change the production deployment path, Keycloak configuration, or
  generation governance state.
- Do not relabel operational records or claim synthetic fixture data is teacher
  review evidence.

## Validation

- The E1 live-acceptance assertion is covered with an isolated test double and
  exercised by the opt-in real Provider test when its protected credentials are
  available.
- The release-gate fixture test fails if the active Prompt version changes
  without coordinated policy and corpus evidence updates.
- Existing API, generator-contract, and documentation integrity tests remain
  green.
