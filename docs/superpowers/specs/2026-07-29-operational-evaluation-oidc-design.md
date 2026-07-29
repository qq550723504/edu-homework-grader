# GitHub OIDC Operational Evaluation Design

## Goal

Run production AI operational evaluations without exposing the production
PostgreSQL service to the internet or granting a public-repository workflow
access to a self-hosted runner. GitHub Actions remains the approval and
artifact surface; the evaluation itself runs as an ephemeral Kubernetes Job in
the production cluster.

## Scope

This change adds a narrowly scoped GitHub OIDC trust boundary, a control-plane
API for starting and retrieving an operational evaluation, and a least-
privileged Kubernetes executor. It updates the existing manual-dispatch
workflow to use that control plane.

It does not create a generation default, fabricate evaluation records, relax
the evidence HMAC validation, expose PostgreSQL, or make the repository
private.

## Chosen Architecture

```text
GitHub protected environment job (main)
  -> short-lived GitHub OIDC JWT
  -> public API control-plane endpoint
  -> ephemeral in-cluster evaluation Job
  -> signed report callback to API
  -> GitHub job downloads report and uploads a 30-day artifact
```

The API accepts only GitHub-issued OIDC tokens with all of these constraints:

- issuer is `https://token.actions.githubusercontent.com`;
- audience equals the deployment-specific operational-evaluation audience;
- repository ID and owner ID match the configured repository, not a mutable
  name alone;
- `repository_visibility` is `public`, so the control plane does not silently
  weaken its public-repository threat model;
- ref is `refs/heads/main` and ref type is `branch`;
- event is `workflow_dispatch`;
- environment is `ai-evaluation-operational`;
- workflow ref identifies
  `.github/workflows/ai-evaluation-operational.yml` on `main`;
- runner environment is `github-hosted`.

The verifier fetches GitHub's OIDC JWKS, validates signature, issuer,
audience, expiry, and required claims. It does not trust an unsigned JWT
payload, a caller-provided repository name, or a static webhook secret.

## API and Run Lifecycle

`POST /v1/internal/operational-evaluations` accepts the exact evaluation
specification and a GitHub OIDC bearer token. A successful request creates one
run in `queued` state and one Kubernetes Job named from the immutable run ID.
The endpoint is idempotent per GitHub run ID and rejects a second distinct spec
for the same run.

`GET /v1/internal/operational-evaluations/{run_id}` returns sanitized status
and an artifact availability indicator to the same verified workflow identity.
`GET /v1/internal/operational-evaluations/{run_id}/report` returns the signed
report only after the Job has completed successfully. It never returns raw
exported records, question bodies, prompt text, database URLs, callback tokens,
or HMAC keys.

The executor receives a per-run callback token from a Kubernetes Secret. It
uses that token only to post completion or failure to a cluster-internal API
endpoint. The API stores only the signed report, SHA-256 digest, status,
timestamps, GitHub run metadata, and a sanitized failure code. No source
records, Prompt text, or question text are persisted by the control plane.

Completed reports and their metadata have a 30-day retention period. A
cluster-owned cleanup job removes expired records and per-run callback Secrets.
The GitHub workflow uploads the same report as a 30-day artifact.

## Kubernetes Boundary

The API service account receives only the permissions needed to create,
inspect, and delete its labelled evaluation Jobs and callback Secrets. The
executor service account has no Kubernetes API permission.

Each executor Job uses:

- a production API image pinned to the release digest;
- a separate evaluation database credential with `SELECT` only on exactly the
  tables used by the exporter;
- a dedicated Secret containing the evidence HMAC key, not the application
  owner credential;
- an internal API callback URL and its per-run callback Secret;
- a finite active deadline, zero retries, TTL cleanup, and resource limits.

Network policy permits the executor only to reach PostgreSQL, the internal API
service, DNS, and the required egress for the pinned image/runtime. It does not
expose PostgreSQL through an Ingress, LoadBalancer, NodePort, or public proxy.

## Workflow Changes

The existing `ai-evaluation-operational` job remains a manual dispatch on
`main`, retains the protected `ai-evaluation-operational` environment, and
adds `id-token: write`. It requests a custom-audience OIDC token, starts one
run, polls the authenticated status endpoint within a bounded timeout,
downloads the completed signed report, and uploads it as the existing
30-day artifact.

The workflow no longer receives `DATABASE_URL` or
`EVALUATION_EVIDENCE_HMAC_KEY`. It therefore cannot access production data or
sign evidence itself.

## Failure Handling

- Invalid OIDC claims fail before a run or Job is created.
- Duplicate requests for the same GitHub run are idempotent; divergent input is
  rejected.
- Job timeout, exporter failure, callback authentication failure, or missing
  report transitions the run to a sanitized terminal failure state.
- A non-promotion-eligible signed report is still a successful technical run;
  the current governance workflow remains responsible for rejecting promotion.
- The workflow fails when the run reaches a terminal technical failure or its
  polling deadline expires.

## Verification

Tests will cover JWT claim acceptance and rejection, run idempotency,
callback-token handling, report redaction and expiry, Job manifest safety,
workflow permissions and secret removal, and Kubernetes/RBAC/network-policy
constraints. A staging-like production verification will prove that the
workflow can produce a signed report from real data only when the dataset is
large enough; the current empty dataset must remain ineligible for promotion.

## Non-Goals

- No self-hosted GitHub runner.
- No GitHub PAT, database password, or HMAC key in a GitHub environment.
- No automatic generation-default approval or application.
- No bypass of the existing two-subject governance rule.
