# Production minimum email alerting

## Goal

Provide a low-noise, weekly production availability check for the v0.1 pilot.
When a checked dependency is unavailable, send one email to the designated
operator mailbox.

## Scope

- A Kubernetes `CronJob` runs weekly on Sunday at 04:30 Asia/Singapore.
- It checks the public web endpoint and the in-cluster API, Grader, and
  PostgreSQL service.
- A failed check sends an SMTP-over-TLS message to the designated QQ mailbox;
  a fully successful run emits no email.
- A separate Kubernetes Secret holds the SMTP sender, recipient, host, port,
  and authorization code. The Secret is not rendered into source control,
  workflow logs, application runtime Secrets, or pod output.
- A one-off Job using the same workload validates the delivery path after
  deployment.

## Boundaries

- This is availability monitoring, not a replacement for Prometheus,
  Alertmanager, or log aggregation.
- It does not inspect application data, customer data, credentials, or
  database contents. PostgreSQL is tested only through connection readiness.
- A successful scheduled run is intentionally silent to avoid weekly mail
  noise. Kubernetes Job status remains the audit trail for success.

## Failure behavior

- The checker records which endpoint failed and exits non-zero after attempting
  notification.
- If SMTP delivery also fails, the Job still exits non-zero, making the failure
  visible through Kubernetes Job status and preventing a false healthy result.
- The job uses bounded execution time, no retries, and completed-job retention
  to prevent repeated stale work.

## Verification

1. Manifest tests assert the weekly schedule, isolated Secret reference,
   required targets, and no literal SMTP authorization code.
2. A one-off production Job sends a test email and completes successfully.
3. A forced unreachable target produces a non-zero Job and a failure email.
4. Existing production workloads remain ready after applying the manifest.
