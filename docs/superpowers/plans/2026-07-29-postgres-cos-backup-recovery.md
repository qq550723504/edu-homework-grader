# PostgreSQL COS Backup and Isolated Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add a weekly PostgreSQL logical-backup CronJob to Tencent COS and a confirmation-gated isolated recovery drill for the v0.1 pilot.

**Architecture:** A PostgreSQL 16 init container produces a custom-format dump in an emptyDir; an rclone S3/TencentCOS container uploads the dump plus its SHA-256 sidecar. A separate local operator command creates the COS Secret, and recovery uses a uniquely named temporary PostgreSQL Pod without changing production resources.

**Tech Stack:** Kubernetes batch/v1 CronJob, PostgreSQL 16 pg_dump/pg_restore, rclone S3 TencentCOS backend, PowerShell 7, Pester 6, Kustomize.

## Global Constraints

- The schedule is 15 3 * * 0, timeZone Asia/Singapore, with concurrencyPolicy Forbid and 14-day prefix-scoped retention.
- Backups only use the COS prefix edu-homework-grader/postgres/; no resource or secret from task-processor is referenced.
- COS values are stored only in edu-grader-backup-cos; backup workloads receive only edu-grader-runtime/POSTGRES_PASSWORD, not the complete runtime Secret.
- The dump uses pg_dump --format=custom; dump, upload, checksum, retention, and restore failures are non-zero failures.
- Recovery requires -ConfirmRecovery and a yyyyMMddTHHmmssZ timestamp. It creates no Service, Ingress, or PVC, and never patches/deletes production resources.
- Do not modify scripts/k8s/deploy-production.ps1 or GitHub deployer RBAC. Release deployment must not silently alter backup policy or credentials.

---

### Task 1: Create the COS backup Secret bootstrap command

**Files:**

- Create: scripts/k8s/create-backup-cos-secret.ps1
- Create: scripts/k8s/create-backup-cos-secret.tests.ps1

**Interfaces:**

- Consumes: namespace, bucket, HTTPS endpoint, region, and key pair entered with PowerShell prompts.
- Produces: Secret/edu-grader-backup-cos with exactly COS_S3_ACCESS_KEY_ID, COS_S3_SECRET_ACCESS_KEY, COS_S3_ENDPOINT, COS_S3_REGION, and COS_S3_BUCKET.

- [ ] **Step 1: Write failing safety tests.**

    Describe create-backup-cos-secret {
        BeforeAll { $scriptPath = Join-Path $PSScriptRoot 'create-backup-cos-secret.ps1' }

        It 'requires explicit confirmation before it invokes kubectl' {
            Mock kubectl { throw 'kubectl must not run' }
            { & $scriptPath -Bucket backup-bucket -Endpoint https://cos.example.test -Region na-ashburn } |
                Should -Throw -ExpectedMessage '*-ConfirmBackupCredential*'
            Assert-MockCalled kubectl -Times 0 -Exactly
        }

        It 'rejects a non-HTTPS endpoint before it invokes kubectl' {
            Mock kubectl { throw 'kubectl must not run' }
            { & $scriptPath -Bucket backup-bucket -Endpoint http://cos.example.test -Region na-ashburn -ConfirmBackupCredential } |
                Should -Throw -ExpectedMessage '*HTTPS*'
            Assert-MockCalled kubectl -Times 0 -Exactly
        }

        It 'does not emit credential values' {
            $source = Get-Content -Raw -LiteralPath $scriptPath
            $source | Should -Match 'Read-Host.*AsSecureString'
            $source | Should -Match 'kubectl.*create.*secret.*generic'
            $source | Should -Not -Match 'Write-(Host|Output).*?(ACCESS|SECRET|PASSWORD|CREDENTIAL)'
        }
    }

- [ ] **Step 2: Verify RED.**

Run: Invoke-Pester scripts/k8s/create-backup-cos-secret.tests.ps1 -Output Detailed

Expected: FAIL because the target script does not exist.

- [ ] **Step 3: Implement the minimum prompt-only command.**

Use this public interface:

    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [string]$Namespace = 'edu-homework-grader',
        [Parameter(Mandatory = $true)][string]$Bucket,
        [Parameter(Mandatory = $true)][string]$Endpoint,
        [Parameter(Mandatory = $true)][string]$Region,
        [string]$SecretName = 'edu-grader-backup-cos',
        [switch]$Replace,
        [switch]$ConfirmBackupCredential
    )

Require -ConfirmBackupCredential, reject an existing Secret unless -Replace is supplied, validate an absolute HTTPS endpoint, prompt for access-key ID and secret with Read-Host -AsSecureString, render with kubectl create secret generic --dry-run=client --output=yaml, and pipe directly to kubectl apply --server-side --force-conflicts --filename -. Convert the SecureString only in a try/finally block and free the BSTR in finally.

- [ ] **Step 4: Verify GREEN.**

Run: Invoke-Pester scripts/k8s/create-backup-cos-secret.tests.ps1 -Output Detailed

Expected: PASS without any credential output.

- [ ] **Step 5: Commit.**

    git add scripts/k8s/create-backup-cos-secret.ps1 scripts/k8s/create-backup-cos-secret.tests.ps1
    git commit -m "ops: add COS backup secret bootstrap"

### Task 2: Add the weekly backup CronJob and manifest contract tests

**Files:**

- Create: infra/k8s/production/postgres-backup.yaml
- Create: infra/k8s/production/postgres-backup.tests.ps1
- Modify: infra/k8s/production/kustomization.yaml

**Interfaces:**

- Consumes: edu-grader-runtime/POSTGRES_PASSWORD, all five COS Secret fields, and PostgreSQL Service postgres.
- Produces: CronJob/postgres-backup, with edu_grader.dump and edu_grader.dump.sha256 uploaded under edu-homework-grader/postgres/v1/{UTC timestamp}/.

- [ ] **Step 1: Write a failing rendered-manifest contract test.**

    Describe 'postgres-backup manifest' {
        BeforeAll {
            $manifest = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'postgres-backup.yaml')
        }

        It 'runs weekly without overlap' {
            $manifest | Should -Match '(?m)^kind:\s*CronJob\s*$'
            $manifest | Should -Match '(?m)^\s{2}name:\s*postgres-backup\s*$'
            $manifest | Should -Match '(?m)^\s{2}schedule:\s*"15 3 \* \* 0"\s*$'
            $manifest | Should -Match '(?m)^\s{2}timeZone:\s*Asia/Singapore\s*$'
            $manifest | Should -Match '(?m)^\s{2}concurrencyPolicy:\s*Forbid\s*$'
        }

        It 'creates a verified custom dump and limits cleanup to the backup prefix' {
            $manifest | Should -Match 'pg_dump.*--format=custom'
            $manifest | Should -Match 'sha256sum.*edu_grader.dump'
            $manifest | Should -Match 'provider = TencentCOS'
            $manifest | Should -Match 'edu-homework-grader/postgres/v1/'
            $manifest | Should -Match 'rclone delete.*--min-age 14d'
        }

        It 'keeps database and COS Secret access separate' {
            $manifest | Should -Match 'name:\s*edu-grader-runtime\s*\r?\n\s*key:\s*POSTGRES_PASSWORD'
            $manifest | Should -Match 'name:\s*edu-grader-backup-cos'
            $manifest | Should -Not -Match 'task-processor'
            $manifest | Should -Not -Match '(?i)(AKID|SECRET_ACCESS_KEY:\s*[^$])'
        }
    }

- [ ] **Step 2: Verify RED.**

Run: Invoke-Pester infra/k8s/production/postgres-backup.tests.ps1 -Output Detailed

Expected: FAIL because the manifest does not exist.

- [ ] **Step 3: Implement the manifest.**

Add a batch/v1 CronJob with the exact schedule, timezone, Forbid policy, bounded history, and emptyDir volume named backup. Its postgres:16-alpine init container runs:

    set -eu
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    mkdir -p "/backup/$stamp"
    pg_dump --host=postgres --username=edu_grader --dbname=edu_grader --format=custom --file="/backup/$stamp/edu_grader.dump"
    sha256sum "/backup/$stamp/edu_grader.dump" > "/backup/$stamp/edu_grader.dump.sha256"
    printf '%s' "$stamp" > /backup/timestamp

Its rclone/rclone:1.71.0 main container builds a temporary config with provider = TencentCOS, copies only /backup/$stamp using rclone copy --checksum, and then runs rclone delete --min-age 14d against only cos:$COS_S3_BUCKET/edu-homework-grader/postgres/v1. Read database password with one secretKeyRef; read each COS field from edu-grader-backup-cos; use no envFrom. Add the YAML resource to the production kustomization.

- [ ] **Step 4: Verify GREEN and Kubernetes schema.**

Run:

    Invoke-Pester infra/k8s/production/postgres-backup.tests.ps1 -Output Detailed
    kubectl apply --server-side --dry-run=server -k infra/k8s/production

Expected: Pester passes and the target API accepts the rendered manifests without displaying Secret values.

- [ ] **Step 5: Commit.**

    git add infra/k8s/production/postgres-backup.yaml infra/k8s/production/postgres-backup.tests.ps1 infra/k8s/production/kustomization.yaml
    git commit -m "ops: add weekly PostgreSQL COS backup"

### Task 3: Add the confirmation-gated isolated recovery drill

**Files:**

- Create: scripts/k8s/recovery-drill.ps1
- Create: scripts/k8s/recovery-drill.tests.ps1

**Interfaces:**

- Consumes: -BackupTimestamp in yyyyMMddTHHmmssZ, -ConfirmRecovery, and the COS Secret.
- Produces: a redacted summary with checksum status and row counts for question versions, assignments, student attempts, grading runs, guardian consents, and audit logs.

- [ ] **Step 1: Write failing recovery safety tests.**

    Describe 'recovery-drill' {
        BeforeAll { $scriptPath = Join-Path $PSScriptRoot 'recovery-drill.ps1' }

        It 'requires confirmation before it invokes Kubernetes' {
            Mock kubectl { throw 'kubectl must not run' }
            { & $scriptPath -BackupTimestamp 20260729T031500Z } |
                Should -Throw -ExpectedMessage '*-ConfirmRecovery*'
            Assert-MockCalled kubectl -Times 0 -Exactly
        }

        It 'rejects a non-UTC timestamp before it invokes Kubernetes' {
            Mock kubectl { throw 'kubectl must not run' }
            { & $scriptPath -ConfirmRecovery -BackupTimestamp 2026-07-29 } |
                Should -Throw -ExpectedMessage '*BackupTimestamp*yyyyMMddTHHmmssZ*'
            Assert-MockCalled kubectl -Times 0 -Exactly
        }

        It 'cannot target production resources' {
            $source = Get-Content -Raw -LiteralPath $scriptPath
            $source | Should -Match 'postgres-recovery-\$runId'
            $source | Should -Match 'emptyDir:'
            $source | Should -Not -Match 'delete\s+(statefulset|pod)\s+postgres\b'
            $source | Should -Not -Match '(?i)Write-(Host|Output).*?(SECRET|PASSWORD|ACCESS_KEY)'
        }
    }

- [ ] **Step 2: Verify RED.**

Run: Invoke-Pester scripts/k8s/recovery-drill.tests.ps1 -Output Detailed

Expected: FAIL because the recovery script does not exist.

- [ ] **Step 3: Implement the isolated drill.**

Validate both user inputs before native commands. Derive $runId = "postgres-recovery-$BackupTimestamp" and create only one recovery Pod named from it. Its rclone init container fetches the exact COS dump and checksum into the shared emptyDir and validates sha256sum -c before PostgreSQL starts. Wait for pg_isready, then use the local operator's kubectl exec to invoke pg_restore --clean --if-exists --no-owner inside the recovery Pod. Run these read-only queries inside that Pod:

    SELECT 'question_versions', count(*) FROM question_versions;
    SELECT 'assignments', count(*) FROM assignments;
    SELECT 'student_attempts', count(*) FROM student_attempts;
    SELECT 'grading_runs', count(*) FROM grading_runs;
    SELECT 'student_guardian_consents', count(*) FROM student_guardian_consents;
    SELECT 'audit_logs', count(*) FROM audit_logs;

Delete only the $runId Pod in a finally block, unless -KeepRecoveryArtifacts is passed. Do not delete or patch any production data store, Secret, application workload, Service, PVC, or Ingress.

- [ ] **Step 4: Verify GREEN.**

Run: Invoke-Pester scripts/k8s/recovery-drill.tests.ps1 -Output Detailed

Expected: PASS; unsafe inputs fail before native commands and source contracts enforce production isolation.

- [ ] **Step 5: Commit.**

    git add scripts/k8s/recovery-drill.ps1 scripts/k8s/recovery-drill.tests.ps1
    git commit -m "ops: add isolated PostgreSQL recovery drill"

### Task 4: Document operations and preserve truthful P0 status

**Files:**

- Create: docs/operations/postgres-cos-backup-recovery.md
- Modify: docs/pilot-checklist.md
- Modify: docs/project-status.md
- Modify: docs/status-evidence.json
- Modify: scripts/k8s/recovery-drill.tests.ps1

**Interfaces:**

- Consumes: the CronJob and both operator scripts.
- Produces: secret-safe commands and a machine-readable status that remains false until a real backup and isolated recovery have passed.

- [ ] **Step 1: Add a failing documentation contract test.**

Add a Pester test that requires docs/operations/postgres-cos-backup-recovery.md to contain -ConfirmBackupCredential, -ConfirmRecovery, -BackupTimestamp, -KeepRecoveryArtifacts, postgres-backup, 14 days, and edu-homework-grader/postgres/. Reject AKID, SECRET_ACCESS_KEY=, and POSTGRES_PASSWORD=.

- [ ] **Step 2: Verify RED.**

Run: Invoke-Pester scripts/k8s/recovery-drill.tests.ps1 -Output Detailed

Expected: FAIL because the operations document does not exist.

- [ ] **Step 3: Write the guide and status boundaries.**

Document this safe sequence without literal credentials:

    $bucket = Read-Host 'Approved COS bucket'
    $endpoint = Read-Host 'Approved COS HTTPS endpoint'
    $region = Read-Host 'Approved COS region'
    ./scripts/k8s/create-backup-cos-secret.ps1 -Namespace edu-homework-grader -Bucket $bucket -Endpoint $endpoint -Region $region -ConfirmBackupCredential
    kubectl apply --server-side -k infra/k8s/production
    $jobName = 'postgres-backup-manual-' + (Get-Date -AsUTC -Format 'yyyyMMddTHHmmssZ')
    kubectl -n edu-homework-grader create job --from=cronjob/postgres-backup $jobName
    $backupTimestamp = Read-Host 'UTC timestamp emitted by the successful backup job'
    ./scripts/k8s/recovery-drill.ps1 -Namespace edu-homework-grader -BackupTimestamp $backupTimestamp -ConfirmRecovery

Explain that angle-bracket values are operator inputs, not shell literals. Record the weekly schedule, 14-day retention, six table groups, cleanup behavior, and redacted evidence fields. Keep the pilot checklist and backup_restore_drill_verified false until the live drill passes.

- [ ] **Step 4: Verify docs and tests.**

Run:

    Invoke-Pester scripts/k8s/create-backup-cos-secret.tests.ps1,scripts/k8s/recovery-drill.tests.ps1,infra/k8s/production/postgres-backup.tests.ps1 -Output Detailed
    python scripts/check_docs_status.py
    git diff --check

Expected: all tests and documentation checks pass; the repository does not claim live backup/restore evidence.

- [ ] **Step 5: Commit.**

    git add docs/operations/postgres-cos-backup-recovery.md docs/pilot-checklist.md docs/project-status.md docs/status-evidence.json scripts/k8s/recovery-drill.tests.ps1
    git commit -m "docs: document COS backup recovery evidence"

### Task 5: Execute the live P0 drill only after edu PostgreSQL is deployed

**Files:**

- Modify: docs/status-evidence.json
- Modify: docs/pilot-checklist.md
- Modify: docs/project-status.md

**Interfaces:**

- Consumes: the intended cluster, a Ready StatefulSet/postgres, the two Secrets, one successful backup Job, and one successful isolated recovery.
- Produces: redacted Issue #153 evidence and a truthful completion status.

- [ ] **Step 1: Verify target isolation.**

Run:

    kubectl config current-context
    kubectl -n edu-homework-grader get statefulset postgres
    kubectl -n edu-homework-grader get secret edu-grader-runtime edu-grader-backup-cos

Expected: only the intended context and edu resource names are returned.

- [ ] **Step 2: Create the COS Secret with the prompt-only command.**

Run: set $bucket, $endpoint, and $region by secure operator prompt as in Task 4 Step 3, then invoke create-backup-cos-secret.ps1 with those three variables and -ConfirmBackupCredential.

Expected: only the target Secret name is printed.

- [ ] **Step 3: Apply and run a named backup Job.**

Run:

    kubectl apply --server-side -k infra/k8s/production
    $jobName = 'postgres-backup-manual-' + (Get-Date -AsUTC -Format 'yyyyMMddTHHmmssZ')
    kubectl -n edu-homework-grader create job --from=cronjob/postgres-backup $jobName
    kubectl -n edu-homework-grader wait --for=condition=complete "job/$jobName" --timeout=15m

Expected: the Job completes and redacted logs identify the object prefix and checksum result.

- [ ] **Step 4: Run the recovery drill.**

Run: obtain $backupTimestamp from the completed Job's redacted log and invoke ./scripts/k8s/recovery-drill.ps1 -Namespace edu-homework-grader -BackupTimestamp $backupTimestamp -ConfirmRecovery.

Expected: checksum success, six table-group count labels, and no production-resource change.

- [ ] **Step 5: Record evidence only after success.**

Update the three status documents with UTC timestamp, object prefix, recovery resource name, count labels, exit statuses, and Issue #153 URL. Never include credential values, connection strings, dump URLs, or row contents. Commit separately with git commit -m "docs: record PostgreSQL backup recovery drill".
