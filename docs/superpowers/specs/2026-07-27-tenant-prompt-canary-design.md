# Tenant prompt canary design

**Date:** 2026-07-27  
**Status:** approved for specification review

## Problem

`generator-v4` adds the E1 policy-v2 instruction, but it must not become the
production default before real generation and teacher-review evidence exists.
The existing governance system can allow or block a configured prompt version,
but it cannot select `generator-v4` for an approved tenant while other tenants
continue using the `generator-v3` default.

The repository's JSONL evaluation corpus is deterministic regression input. It
is not operational evidence and must never be relabeled to claim that v4 has
been teacher reviewed.

## Decision

Keep `generator-v3` as the global default. Add an explicit tenant-scoped prompt
canary configuration that selects a non-default prompt version only for an
approved tenant. The selected version then passes through the existing
governance pipeline unchanged:

1. A normal tenant job snapshots `generator-v3`.
2. A tenant listed in the canary configuration snapshots `generator-v4`.
3. The existing global `canary` governance entry for `generator-v4`, together
   with that tenant's `canary` override, authorizes the v4 job.
4. Every other tenant remains on v3 and is unaffected by the v4 governance
   state.

The configuration accepts a bounded mapping of tenant IDs to catalogued prompt
versions. Startup rejects unknown prompt templates, duplicate tenant IDs, or a
mapping to the default version. It contains no Provider credentials and is not
exposed through the teacher API.

## Operational evidence boundary

The deterministic AI evaluation fixture remains labeled `generator-v3` and is
described as a regression gate. It will not be coupled to the active default
prompt version.

Promotion of v4 requires a separate operational export selecting genuine v4
attempts and teacher review outcomes. The export must satisfy its versioned
policy and governance checks before any later default-version change. A local
Provider smoke test verifies transport and policy compatibility only; it does
not count as teacher-review evidence.

## Error handling

If a configured canary version is invalid, API startup fails closed. If a
tenant's selected v4 version lacks the required global and tenant governance
entries, job execution fails through the existing safe governance code without
calling the Provider. Jobs retain the selected prompt version as an immutable
snapshot, so regeneration preserves the original experiment assignment.

## Tests

- Default tenants snapshot `generator-v3`.
- A configured tenant snapshots `generator-v4`.
- An unconfigured tenant cannot inherit another tenant's canary version.
- Invalid canary configuration fails startup validation.
- Existing governance tests prove that a v4 canary job needs both global and
  tenant authorization.
- The deterministic gate continues to run against explicitly v3 fixtures, and
  cannot represent v4 operational evidence.

## Scope

This slice adds selection and regression coverage only. It does not deploy a
canary, create governance rows, generate questions, review drafts, or promote
v4. Those are production operations requiring separate evidence and approval.
