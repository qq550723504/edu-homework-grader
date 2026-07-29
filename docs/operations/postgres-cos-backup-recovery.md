# PostgreSQL COS backup and isolated recovery

This procedure is for the v0.1 pilot application database only. It backs up
the `edu-homework-grader` PostgreSQL Service to the dedicated COS prefix
`edu-homework-grader/postgres/`. It must never be used against task-processor
or any other namespace.

## Preconditions

- The intended Kubernetes context is selected.
- `StatefulSet/postgres` is Ready in the `edu-homework-grader` namespace.
- An operator has the approved COS bucket, HTTPS endpoint, region, and a COS
  key pair authorized for the backup prefix.
- The operator can create namespace-scoped Secrets, CronJobs, Jobs, and the
  temporary recovery Pod.

Verify only resource names before changing anything:

```powershell
kubectl config current-context
kubectl -n edu-homework-grader get statefulset postgres
kubectl -n edu-homework-grader get secret edu-grader-runtime
```

## Configure the COS Secret

Run the setup script locally. It prompts for the COS key pair and keeps the
secret key hidden. Do not place credentials in shell history, YAML files, or
issue comments.

```powershell
$bucket = Read-Host 'Approved COS bucket'
$endpoint = Read-Host 'Approved COS HTTPS endpoint'
$region = Read-Host 'Approved COS region'
./scripts/k8s/create-backup-cos-secret.ps1 `
  -Namespace edu-homework-grader `
  -Bucket $bucket `
  -Endpoint $endpoint `
  -Region $region `
  -ConfirmBackupCredential
```

The command creates `Secret/edu-grader-backup-cos`. It refuses to replace an
existing Secret unless the operator explicitly adds `-Replace`.

## Build the migration image

Use the **Build API migration image** GitHub Actions workflow with the approved
40-character source SHA. It builds and publishes only the API image; it does
not deploy production or access Kubernetes.

After the workflow succeeds, download its `api-migration-image-digest` artifact
and read the `sha256` value from `api-migration-image-digest.txt`. Form the
digest-pinned image reference without using the mutable SHA tag:

```powershell
$digest = Read-Host 'SHA-256 digest from api-migration-image-digest.txt'
$image = "ghcr.io/qq550723504/edu-homework-grader-api@$digest"
```

## Initialize the application schema

For a newly created PostgreSQL StatefulSet, run the real Alembic history from
the approved API image before treating a backup-and-restore drill as meaningful.
The migration runner accepts only a GHCR image pinned by SHA-256 digest; do not
use a mutable tag or an ad-hoc source container.

```powershell
$image = Read-Host 'Approved API image pinned with @sha256 digest'
./scripts/k8s/run-postgres-migration.ps1 `
  -Namespace edu-homework-grader `
  -Image $image `
  -ConfirmMigration
```

The command creates exactly one bounded Job, reads only `DATABASE_URL` from
`edu-grader-runtime`, waits for completion, and prints the resulting Alembic
revision. Keep the Job logs as part of the P0 evidence.

## Enable and run the weekly backup

The `postgres-backup` CronJob runs every Sunday at 03:15 in Asia/Singapore. It
forbids overlapping runs, creates a PostgreSQL custom-format dump, uploads a
SHA-256 sidecar, verifies the remote copy, and removes only backup-prefix
objects older than 14 days.

Apply the manifest and start one named Job for the initial drill:

```powershell
kubectl apply --server-side -k infra/k8s/production
$jobName = 'postgres-backup-manual-' + (Get-Date -AsUTC -Format 'yyyyMMddHHmmss')
kubectl -n edu-homework-grader create job --from=cronjob/postgres-backup $jobName
kubectl -n edu-homework-grader wait --for=condition=complete "job/$jobName" --timeout=15m
kubectl -n edu-homework-grader logs "job/$jobName"
```

Read the `backup_timestamp` line from the successful Job log. It is the exact
UTC timestamp required for recovery. Do not use a timestamp inferred from local
time or a partially completed Job.

## Run the isolated recovery drill

The drill downloads the selected dump and checksum in an rclone init container,
then starts a one-off PostgreSQL Pod listening only on `127.0.0.1`. It restores
inside that Pod and checks row counts for question versions, assignments,
student attempts, grading runs, student guardian consents, and audit logs.

```powershell
$backupTimestamp = Read-Host 'UTC backup timestamp from the completed backup Job'
./scripts/k8s/recovery-drill.ps1 `
  -Namespace edu-homework-grader `
  -BackupTimestamp $backupTimestamp `
  -ConfirmRecovery
```

The command deletes the temporary recovery Pod after the validation summary.
For operator investigation only, retain the Pod explicitly:

```powershell
./scripts/k8s/recovery-drill.ps1 `
  -Namespace edu-homework-grader `
  -BackupTimestamp $backupTimestamp `
  -ConfirmRecovery `
  -KeepRecoveryArtifacts
```

No production StatefulSet, Service, PVC, application workload, or Secret is
modified by recovery. A non-zero exit means the drill has not passed; preserve
the redacted command output and investigate before retrying.

## Record P0 evidence

Only after both the backup Job and recovery drill succeed, record the UTC
timestamp, COS object prefix, temporary recovery Pod name, checksum result, six
table-group count labels, and command exit statuses in Issue #153. Do not record
credentials, database URLs, dump URLs, dump content, or table rows.

Keep `backup_restore_drill_verified` false until that evidence exists.
