# Development generator consolidation design

**Date:** 2026-07-27  
**Status:** ready for review

## Goal

The application has not been deployed. It therefore has one development
generator contract, not a production prompt-version migration problem. Keep the
E1 policy-v2 fix and remove the development-only v2/v3/v4 prompt-version
complexity.

## Decision

- Use one active template named `generator-v1`.
- Put the current E1-safe instructions in that template: policy version `2`,
  required `accepted_answers`, and only `max_score` and `normalization` as
  optional top-level E1 rule fields.
- Remove unused later development templates and update code, tests, workflow
  labels, and documentation to use `generator-v1`.
- Keep the deterministic evaluation JSONL as a test fixture only. It is not a
  Provider run or teacher-review evidence and is not coupled to the active
  template version.
- Remove the unpushed tenant-canary design, because no rollout mechanism is in
  scope before the first deployment.

## Validation

The contract suite and API generation suite must pass. The controlled live
Provider E1 test must generate a candidate with policy version `2` and pass the
platform policy validator. The deterministic evaluation gate must still pass as
a fixture regression test without claiming operational approval.

## Scope

No deployment, production database changes, real teacher review, canary,
governance change, or model/provider change is included.
