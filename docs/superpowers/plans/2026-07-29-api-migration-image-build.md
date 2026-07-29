# API Migration Image Build-Only Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish one digest-pinned API image from an explicit source SHA without deploying workloads.

**Architecture:** A dedicated manual GitHub Actions workflow validates the source SHA, checks out only that revision, builds the API Dockerfile, pushes it to GHCR, and returns the digest as a one-day artifact. It does not share a job or deployment path with the production release workflow.

**Bootstrap:** Until the workflow reaches the default branch, a same-repository draft PR labeled `build-migration-image` invokes the same build job using the PR head SHA. Fork PRs and all other labels are rejected by the job condition.

**Tech Stack:** GitHub Actions, Docker Buildx, GHCR, Pester source-contract tests.

## Global Constraints

- Permissions are exactly `contents: read` and `packages: write`.
- Build and publish only `ghcr.io/${{ github.repository_owner }}/edu-homework-grader-api`.
- Tag is the validated 40-character lower-case source SHA; operators use only the emitted `@sha256` reference.
- No Kubernetes credentials, environment, deployment script, or other service Dockerfile is allowed.
- The PR bootstrap is restricted to `pull_request` `labeled` events whose label is `build-migration-image` and whose head repository equals the current repository.

---

### Task 1: Build-only workflow contract

**Files:**
- Create: `.github/workflows/build-api-migration-image.yml`
- Create: `.github/workflows/build-api-migration-image.tests.ps1`

**Interfaces:**
- Consumes: `workflow_dispatch.inputs.source_sha` matching `^[0-9a-f]{40}$`.
- Produces: API image tag and an `api-migration-image-digest` artifact containing `sha256:<64 hex>`.

- [ ] **Step 1: Write the failing workflow contract test**

```powershell
Describe 'build API migration image workflow' {
    BeforeAll {
        $workflow = Get-Content -Raw (Join-Path $PSScriptRoot 'build-api-migration-image.yml')
    }

    It 'builds only a validated API revision without deployment access' {
        $workflow | Should -Match 'workflow_dispatch:'
        $workflow | Should -Match 'packages: write'
        $workflow | Should -Match 'contents: read'
        $workflow | Should -Match '\^\[0-9a-f\]\{40\}\$'
        $workflow | Should -Match 'file: apps/api/Dockerfile'
        $workflow | Should -Not -Match '(?i)kubectl|deploy-production|environment:'
    }
}
```

- [ ] **Step 2: Run the test red**

Run `Invoke-Pester .github/workflows/build-api-migration-image.tests.ps1 -Output Detailed`.

Expected: FAIL because the workflow does not exist.

- [ ] **Step 3: Implement the minimal workflow**

Create a `workflow_dispatch` workflow with one `build` job. Validate
`inputs.source_sha` in Bash with `[[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]]`
before checkout; checkout that SHA; use the repository's already pinned
`docker/login-action` and `docker/build-push-action` revisions; log into GHCR
using `secrets.GITHUB_TOKEN`; invoke `docker/build-push-action` for context
`.` and `apps/api/Dockerfile`; push only the SHA tag. Validate the build digest
against `^sha256:[0-9a-f]{64}$`, write it to
`api-migration-image-digest.txt`, add the full `@sha256` image reference to the
job summary, and upload it as `api-migration-image-digest` for one day.

- [ ] **Step 4: Run the test green and commit**

Run the Task 1 Pester test, then commit the two workflow files with:

```powershell
git add .github/workflows/build-api-migration-image.yml .github/workflows/build-api-migration-image.tests.ps1
git commit -m "ci: add API migration image build workflow"
```

### Task 2: Document workflow-to-migration handoff

**Files:**
- Modify: `docs/operations/postgres-cos-backup-recovery.md`
- Modify: `scripts/k8s/recovery-drill.tests.ps1`

**Interfaces:**
- Consumes: Task 1 artifact digest.
- Produces: an operator sequence that dispatches the build-only workflow, retrieves the artifact, and passes a GHCR `@sha256` reference to `run-postgres-migration.ps1`.

- [ ] **Step 1: Write the failing runbook assertions**

Add these assertions to the existing runbook test:

```powershell
$document | Should -Match 'Build API migration image'
$document | Should -Match 'api-migration-image-digest'
$document | Should -Match '@sha256'
```

- [ ] **Step 2: Run the test red**

Run `Invoke-Pester scripts/k8s/recovery-drill.tests.ps1 -Output Detailed`.

Expected: FAIL because the workflow handoff is absent.

- [ ] **Step 3: Document the handoff**

Before schema initialization, add a short section that states the manual
workflow builds only the API image and does not deploy production. Direct the
operator to use its exact approved source SHA, retrieve the named digest
artifact, form the GHCR `@sha256` reference, and invoke the existing confirmed
migration script.

- [ ] **Step 4: Run full verification and commit**

Run:

```powershell
Invoke-Pester scripts/k8s/create-backup-cos-secret.tests.ps1,scripts/k8s/recovery-drill.tests.ps1,scripts/k8s/run-postgres-migration.tests.ps1,infra/k8s/production/postgres-backup.tests.ps1,infra/k8s/production/kustomization.tests.ps1,.github/workflows/build-api-migration-image.tests.ps1 -Output Detailed
python scripts/check_docs_status.py
git diff --check
```

Commit the runbook changes with:

```powershell
git add docs/operations/postgres-cos-backup-recovery.md scripts/k8s/recovery-drill.tests.ps1
git commit -m "docs: describe migration image build handoff"
```
