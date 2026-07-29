# PostgreSQL COS Backup and Isolated Recovery Design

## Goal

Provide the v0.1 pilot with a weekly, verified logical backup of the application
PostgreSQL database in Tencent COS and a safe, repeatable isolated recovery drill.
The solution protects the data required for the pilot workflow: questions,
assignments, submissions and grades, guardian-consent records, and audit records.

## Scope and constraints

- The production database remains the existing PostgreSQL 16 StatefulSet in the
  `edu-homework-grader` namespace. This work does not replace it or introduce a
  database operator.
- Backups run at 03:15 every Sunday in `Asia/Singapore`, with `Forbid`
  concurrency so an incomplete backup cannot overlap the next run.
- The repository does not contain COS credentials, database dumps, connection
  strings, or rendered Secrets.
- Backups use the existing Tencent COS account but only the
  `edu-homework-grader/postgres/` object prefix. The Kubernetes backup Secret is
  separate from `edu-grader-runtime` and is mounted only by backup and recovery
  workloads.
- Logical backups use PostgreSQL's supported `pg_dump --format=custom` format.
  Point-in-time recovery, WAL archiving, and a new PostgreSQL operator are
  explicitly out of scope for the pilot.
- A live drill is only permitted after the edu PostgreSQL StatefulSet is running
  in the target namespace. No task-processor database, pod, Secret, or volume is
  used for evidence.

## Alternatives considered

1. **Weekly pg_dump plus rclone to COS (chosen).** PostgreSQL's native logical
   backup is compatible with the existing StatefulSet, and rclone's S3 backend
   supports Tencent COS. It meets the pilot's weekly backup and isolated restore
   requirement with bounded operational change.
2. **pgBackRest with WAL archiving.** This offers stronger recovery objectives,
   but requires custom PostgreSQL images, archive configuration, and ongoing WAL
   capacity management. It is deferred until real pilot data establishes an RPO
   and RTO that need it.
3. **Manual dump and recovery script only.** This retains the old recovery
   drill idea but fails the automatic-backup requirement, so it is rejected.

## Components

### `edu-grader-backup-cos` Secret

The Secret contains only the S3-compatible COS settings and the COS access key
pair. Its fields are `COS_S3_ACCESS_KEY_ID`, `COS_S3_SECRET_ACCESS_KEY`,
`COS_S3_ENDPOINT`, `COS_S3_REGION`, and `COS_S3_BUCKET`. The operator creates
or updates it directly through `kubectl`; no value is committed to Git.

The existing `edu-grader-runtime` Secret continues to own PostgreSQL runtime
credentials. The backup workload receives the database password through a
single `secretKeyRef`, rather than importing the entire runtime Secret.

### Weekly backup CronJob

`postgres-backup` is a Kubernetes CronJob with `timeZone: Asia/Singapore`,
schedule `15 3 * * 0`, `concurrencyPolicy: Forbid`, and a bounded deadline. An
init container based on PostgreSQL 16 runs `pg_dump` against the in-namespace
`postgres` Service and writes one custom-format dump to an `emptyDir` volume.

The main rclone container reads that file, computes and stores a SHA-256
sidecar, uploads both files via HTTPS using `provider = TencentCOS`, and verifies
the remote object after upload. It removes only objects within the dedicated
prefix that are older than 14 days. The job emits object names, timestamps,
sizes, hashes, and exit status, but never credentials, URLs containing passwords,
or dump contents.

Objects use this deterministic layout:

```text
edu-homework-grader/postgres/v1/<UTC timestamp>/edu_grader.dump
edu-homework-grader/postgres/v1/<UTC timestamp>/edu_grader.dump.sha256
```

The timestamp is generated once by the Job and is included in both object names.
Versioning the prefix makes a future format migration non-destructive.

### Isolated recovery drill

`scripts/k8s/recovery-drill.ps1` requires the explicit
`-ConfirmRecovery` switch and an exact backup timestamp. It refuses to run
against a missing backup or the production PostgreSQL pod.

The script creates a uniquely named, short-lived PostgreSQL 16 recovery Pod with
an `emptyDir` data directory in the edu namespace. Its rclone init container
receives only the COS Secret, downloads the selected dump and checksum, and
verifies the SHA-256 checksum before the PostgreSQL container starts. The local
operator script invokes `pg_restore` only inside that recovery Pod, which exposes
the database nowhere else. It then verifies the presence of the pilot's critical
tables and records their row counts: question versions, assignments, attempts,
grading runs, guardian consents, and audit logs. A failed checksum, restore, or
validation leaves the production database untouched and returns a non-zero exit
code.

By default, the recovery Pod is deleted only after the validation summary has
been printed. `-KeepRecoveryArtifacts` retains it for operator investigation;
this option does not publish a Service, Ingress, or PVC.

## Failure handling

- A failed dump, upload, checksum verification, or cleanup causes the CronJob
  to fail. The previous backup objects remain intact.
- The CronJob never deletes the current upload, objects outside the dedicated
  prefix, or objects newer than 14 days.
- A failed recovery never changes production Services, StatefulSets, PVCs,
  deployments, or application database credentials.
- The recovery command rejects an empty confirmation, a non-UTC timestamp, and
  a backup object whose checksum does not match.
- Kubernetes job history and the COS object list are the operator evidence for
  backup success. The recovery script's redacted summary is the evidence for the
  restore drill.

## Verification and acceptance

Automated tests first establish that:

1. the CronJob renders the weekly schedule, `Forbid` policy, COS Secret boundary,
   custom dump format, checksum upload, and prefix-scoped retention command;
2. the recovery command refuses to run without `-ConfirmRecovery` or without an
   exact backup timestamp;
3. the rendered manifests contain no literal credentials and include no
   task-processor resource reference; and
4. failure paths preserve the production PostgreSQL resource name and do not
   generate an external Service or Ingress.

The live P0 drill is complete only when a backup Job succeeds, a selected COS
object and checksum are present, the isolated restore succeeds, and the redacted
validation summary confirms all six critical table groups. This evidence is
recorded against Issue #153 and linked from the pilot checklist.

## Rollout order

1. Add and test manifests, Secret bootstrap documentation, and the recovery
   script in Git.
2. Build and publish the immutable backup image reference alongside the pilot
   release artifacts.
3. Create `edu-grader-backup-cos` directly in the target namespace.
4. Deploy the edu PostgreSQL StatefulSet and confirm it is Ready.
5. Apply the backup CronJob, run one named backup immediately, then run the
   isolated recovery drill with explicit confirmation.
6. Record redacted evidence in Issue #153 before treating the P0 gate as passed.
