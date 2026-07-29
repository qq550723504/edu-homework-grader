# API migration image build-only workflow

## Purpose

Publish one immutable API image that contains the current Alembic history, so
the PostgreSQL recovery drill can run the existing digest-pinned migration Job
without relying on local Docker-to-GHCR access or a production deployment.

## Scope

Add one manually dispatched GitHub Actions workflow. It accepts a single
40-character lower-case source SHA, checks out that exact revision, builds only
`apps/api/Dockerfile`, and pushes only
`ghcr.io/<owner>/edu-homework-grader-api:<source-sha>`.

Before the workflow exists on the default branch, a bootstrap path accepts only
the `build-migration-image` label event from a same-repository pull request and
uses that pull request's head SHA. This avoids accepting fork code while keeping
the production release workflow untouched.

The workflow writes the resulting SHA-256 image digest to its job summary and a
short-lived artifact. It has `contents: read` and `packages: write` only.

## Safety boundaries

- No Kubernetes credentials, `kubectl`, deployment script, environment, or
  production URL is present.
- No grader, web, or LanguageTool image is built or published.
- The image tag is derived solely from the validated source SHA.
- The operator must use the emitted `@sha256` reference with
  `scripts/k8s/run-postgres-migration.ps1`; mutable tags are not accepted.
- The workflow is a recovery-drill support tool, not a release workflow.

## Verification

Repository tests inspect the workflow for the manual trigger, restricted
permissions, SHA validation, API-only Dockerfile, digest artifact, and the
absence of deployment/Kubernetes operations. After it is pushed, a manual run
must complete successfully and its digest must be used by the migration Job.
