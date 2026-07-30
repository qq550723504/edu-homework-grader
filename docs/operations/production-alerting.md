# Production availability email alerting

`CronJob/production-alert` runs every Sunday at 04:30 Asia/Singapore. It sends
an email only when one or more of these checks fail:

- public `https://edu.getkr.com/`;
- in-cluster API infrastructure readiness;
- in-cluster Grader health;
- PostgreSQL `SELECT 1` using the API runtime database connection.

The CronJob uses the deployed API image and must be updated by the normal
production release workflow. It is included in the deployer's exact-image
capture and automatic rollback map.

## SMTP credential

The separate `production-alert-smtp` Secret contains the sender, recipient,
SMTP host, port, and QQ SMTP authorization code. It is independent from
`edu-grader-runtime`; do not copy its values into source files, GitHub
Secrets, application configuration, Job logs, or operational evidence.

Configure it only from an operator terminal with:

```powershell
pwsh -File scripts/k8s/configure-production-alert-smtp.ps1 -ConfirmProductionAlertSmtp
```

The script requests the authorization code through a masked prompt, applies
the namespace-scoped Secret, and prints no Secret values.

## Delivery verification

After a release deploys the CronJob, create a one-off Job with its explicit
test-notification mode enabled, wait for completion, confirm receipt of the
test email, then delete the completed Job:

```powershell
$utcStamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss')
$jobName = "production-alert-test-$utcStamp"
kubectl -n edu-homework-grader create job --from=cronjob/production-alert $jobName --dry-run=client -o yaml |
  kubectl -n edu-homework-grader set env --local --filename - --output yaml ALERT_TEST_NOTIFICATION=true |
  kubectl -n edu-homework-grader apply --filename -
kubectl -n edu-homework-grader wait --for=condition=complete "job/$jobName" --timeout=5m
kubectl -n edu-homework-grader delete job $jobName
```

Record only the release SHA, API digest, Job name, completion time, and email
receipt confirmation. Do not retain the authorization code, SMTP headers, or
message body.
