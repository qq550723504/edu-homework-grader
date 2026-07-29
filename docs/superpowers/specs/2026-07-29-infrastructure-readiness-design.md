# Infrastructure readiness for first production bootstrap

## Problem

A new production database has no approved AI generation default. This is an intentional
business-state gate: `/ready` returns `503` until a separately governed, signed evaluation
has been submitted, approved by a second subject, and applied. The Kubernetes readiness
probe currently uses that endpoint, so it keeps an otherwise healthy API out of service and
prevents the first deployment from completing.

## Decision

Add `GET /infrastructure-ready` to the API. It verifies only the API's required runtime
infrastructure: a PostgreSQL `SELECT 1` connection. It returns `200` with
`{"status":"ready","database":"ready"}` when the database is reachable and `503` with
`{"status":"degraded","database":"unavailable"}` otherwise.

Change the production API Deployment readiness probe to `/infrastructure-ready`.

Keep `GET /ready` unchanged. It remains the operator-facing business-readiness endpoint and
continues to return `503` while the AI generation default is unconfigured or unavailable.
AI generation therefore remains blocked until the signed-evidence and two-person governance
process is complete; this change does not create a fallback default or bypass governance.

## Validation

Tests will establish that:

1. `/infrastructure-ready` returns `200` for a reachable database and `503` for a database
   connection failure.
2. `/ready` still returns `503` when no governed generation default exists.
3. The production API readiness probe targets `/infrastructure-ready`.

Deployment validation will wait for the API Deployment to become available, then verify that
`/ready` still reports the expected `generation_default=unconfigured` state until real
operational evidence is available.
