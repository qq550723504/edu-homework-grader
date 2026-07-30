# Production Minimum Email Alerting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send one email to the pilot operator when the weekly production availability probe detects a failed public, API, Grader, or PostgreSQL check.

**Architecture:** A small API-image CLI performs HTTP checks and one `SELECT 1` database probe. A Kubernetes CronJob invokes that CLI weekly and supplies only runtime database access plus a separate SMTP Secret. The release deployer treats the CronJob as a managed API-image workload, keeping its image SHA-pinned and rollback-safe.

**Tech Stack:** Python 3 standard library SMTP/HTTPS, SQLAlchemy, pytest, Kubernetes batch/v1 CronJob and Secret, Kustomize, PowerShell 7/Pester.

## Global Constraints

- Run at `30 4 * * 0` in `Asia/Singapore`; successful scheduled runs send no mail.
- Store SMTP authorization only in `production-alert-smtp`; never in source, GitHub, `edu-grader-runtime`, logs, or email body.
- Check `https://edu.getkr.com/`, `http://api:8000/infrastructure-ready`, `http://grader:8010/health`, and PostgreSQL with `SELECT 1`.
- The failure email names failed checks but contains no response body, database URL, credential, personal data, or stack trace.
- Use `backoffLimit: 0`, `concurrencyPolicy: Forbid`, a 300-second deadline, and one-day Job TTL.

---

### Task 1: Implement the bounded alert CLI with test-first behavior

**Files:**
- Create: `apps/api/src/edu_grader_api/cli/production_alert.py`
- Create: `apps/api/tests/test_production_alert.py`

**Interfaces:**
- Consumes: `ALERT_PUBLIC_URL`, `ALERT_API_URL`, `ALERT_GRADER_URL`, `ALERT_SMTP_HOST`, `ALERT_SMTP_PORT`, `ALERT_SMTP_SENDER`, `ALERT_SMTP_RECIPIENT`, `ALERT_SMTP_AUTH_CODE`, and the existing database engine.
- Produces: `python -m edu_grader_api.cli.production_alert`, exit `0` when all checks pass and exit `1` after any failed check.

- [x] **Step 1: Write the failing tests**

```python
def test_healthy_checks_do_not_open_smtp(monkeypatch) -> None:
    monkeypatch.setattr(alert, "check_http", lambda name, url: None)
    monkeypatch.setattr(alert, "check_database", lambda: None)
    monkeypatch.setattr(alert.smtplib, "SMTP_SSL", fail_if_called)

    assert alert.run() == 0


def test_failed_check_sends_redacted_email_and_returns_one(monkeypatch) -> None:
    monkeypatch.setattr(alert, "check_http", fail_only_api)
    monkeypatch.setattr(alert, "check_database", lambda: None)
    smtp = RecordingSmtp()
    monkeypatch.setattr(alert.smtplib, "SMTP_SSL", lambda *args, **kwargs: smtp)

    assert alert.run() == 1
    assert smtp.messages == [("550723504@qq.com", "550723504@qq.com", "Production alert: api")]
    assert "postgresql://" not in smtp.body
    assert "password" not in smtp.body.lower()
```

- [x] **Step 2: Run the new tests and verify the expected import failure**

Run: `python -m pytest apps/api/tests/test_production_alert.py -q`

Expected: FAIL because `edu_grader_api.cli.production_alert` does not exist.

- [x] **Step 3: Implement only the tested CLI**

```python
def run() -> int:
    failures: list[str] = []
    for name, url in (("public", public_url()), ("api", api_url()), ("grader", grader_url())):
        try:
            check_http(name, url)
        except Exception:
            failures.append(name)
    try:
        check_database()
    except Exception:
        failures.append("postgres")
    if not failures:
        return 0
    send_failure_email(failures)
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
```

`check_http` uses `urllib.request.urlopen` with a 10-second timeout and requires a 2xx response. `check_database` uses the existing SQLAlchemy engine and `text("SELECT 1")`. `send_failure_email` uses `smtplib.SMTP_SSL`, logs in with the Secret-derived authorization code, and sends a fixed subject plus a body containing only the comma-separated check names.

- [x] **Step 4: Run the focused test suite**

Run: `python -m pytest apps/api/tests/test_production_alert.py -q`

Expected: PASS with the health and notification cases passing.

- [x] **Step 5: Commit the CLI slice**

```bash
git add apps/api/src/edu_grader_api/cli/production_alert.py apps/api/tests/test_production_alert.py
git commit -m "feat: add production availability alert CLI"
```

### Task 2: Add the isolated weekly CronJob and manifest contract tests

**Files:**
- Create: `infra/k8s/production/production-alert.yaml`
- Create: `infra/k8s/production/production-alert.tests.ps1`
- Modify: `infra/k8s/production/kustomization.yaml`

**Interfaces:**
- Consumes: Task 1 and Kubernetes Secret `production-alert-smtp`.
- Produces: `CronJob/production-alert` with an API image placeholder replaced by the deployer.

- [x] **Step 1: Write the failing Pester manifest contract**

```powershell
It 'runs weekly with an isolated SMTP Secret and bounded execution' {
    $manifest | Should -Match 'name:\s*production-alert'
    $manifest | Should -Match 'schedule:\s*"30 4 \* \* 0"'
    $manifest | Should -Match 'timeZone:\s*Asia/Singapore'
    $manifest | Should -Match 'concurrencyPolicy:\s*Forbid'
    $manifest | Should -Match 'name:\s*production-alert-smtp'
    $manifest | Should -Not -Match '(?i)authorization[ _-]?code:\s*[^$]'
    $manifest | Should -Not -Match 'edu-grader-runtime[\s\S]*ALERT_SMTP_AUTH_CODE'
}
```

- [x] **Step 2: Run the manifest test and verify the expected missing-file failure**

Run: `Invoke-Pester infra/k8s/production/production-alert.tests.ps1 -CI`

Expected: FAIL because `production-alert.yaml` does not exist.

- [x] **Step 3: Add the CronJob and Kustomize resource**

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: production-alert
spec:
  schedule: "30 4 * * 0"
  timeZone: Asia/Singapore
  concurrencyPolicy: Forbid
  startingDeadlineSeconds: 3600
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 0
      activeDeadlineSeconds: 300
      ttlSecondsAfterFinished: 86400
      template:
        spec:
          restartPolicy: Never
          containers:
            - name: alert
              image: ghcr.io/qq550723504/edu-homework-grader-api:sha-not-published
              command: ["python", "-m", "edu_grader_api.cli.production_alert"]
```

Add target URLs directly as environment values. Add `DATABASE_URL` only from `edu-grader-runtime/DATABASE_URL`; add SMTP keys only from `production-alert-smtp`. Add `production-alert.yaml` to Kustomize resources.

- [x] **Step 4: Run contracts and render**

Run: `Invoke-Pester infra/k8s/production/production-alert.tests.ps1 -CI; kubectl kustomize infra/k8s/production | Select-String 'name: production-alert'`

Expected: Pester passes and rendered output contains the CronJob without an SMTP authorization code.

- [x] **Step 5: Commit the manifest slice**

```bash
git add infra/k8s/production/production-alert.yaml infra/k8s/production/production-alert.tests.ps1 infra/k8s/production/kustomization.yaml
git commit -m "feat: add weekly production alert cronjob"
```

### Task 3: Pin the CronJob image and configure SMTP without plaintext output

**Files:**
- Modify: `scripts/k8s/deploy-production.ps1`
- Modify: `scripts/k8s/deploy-production.tests.ps1`
- Create: `scripts/k8s/configure-production-alert-smtp.ps1`
- Create: `scripts/k8s/configure-production-alert-smtp.tests.ps1`
- Create: `docs/operations/production-alerting.md`

**Interfaces:**
- Consumes: `CronJob/production-alert`, current API image capture, and an operator-supplied `SecureString` authorization code.
- Produces: an alert CronJob patched to the immutable API image, and `Secret/production-alert-smtp` created without printing its data.

- [x] **Step 1: Write failing deployment and bootstrapper contract tests**

```powershell
$expected | Should -Contain 'CronJob/production-alert'
$managedImages.ProductionAlertCronJob | Should -Match '@sha256:'
$script | Should -Match 'Read-Host.*AsSecureString'
$script | Should -Not -Match 'Write-.*AUTH_CODE'
$script | Should -Not -Match '(?i)authorization[ _-]?code:\s*[^$]'
```

- [x] **Step 2: Run focused Pester tests and verify failures**

Run: `Invoke-Pester scripts/k8s/deploy-production.tests.ps1,scripts/k8s/configure-production-alert-smtp.tests.ps1 -CI`

Expected: FAIL because the new CronJob is absent from image capture and the SMTP configuration script does not exist.

- [x] **Step 3: Implement the source-of-truth deploy and configuration paths**

Extend `Get-ManagedImages`, its required image keys, temporary Kustomize patch list, and tests with `ProductionAlertCronJob`, reading and patching container `alert` in `CronJob/production-alert`.

The configuration script requires `-ConfirmProductionAlertSmtp`, restricts `-Namespace` to `edu-homework-grader`, obtains the authorization code using `Read-Host -AsSecureString`, converts it only in process memory, feeds Secret YAML to `kubectl apply --server-side --filename -`, and prints only Secret name and namespace. It sets `smtp.qq.com`, port `465`, sender `550723504@qq.com`, and the same recipient; it has no plaintext command-line parameter.

- [x] **Step 4: Run contracts and server-side dry run**

Run: `Invoke-Pester scripts/k8s/deploy-production.tests.ps1,scripts/k8s/configure-production-alert-smtp.tests.ps1 -CI; kubectl kustomize infra/k8s/production | kubectl apply --dry-run=server --filename -`

Expected: Pester passes and the server accepts the rendered resources.

- [x] **Step 5: Commit the release integration slice**

```bash
git add scripts/k8s/deploy-production.ps1 scripts/k8s/deploy-production.tests.ps1 scripts/k8s/configure-production-alert-smtp.ps1 scripts/k8s/configure-production-alert-smtp.tests.ps1 docs/operations/production-alerting.md
git commit -m "feat: pin production alerting deployment"
```

### Task 4: Merge, deploy, and verify email delivery

**Files:**
- Modify: `docs/operations/production-alerting.md`

**Interfaces:**
- Consumes: the merged immutable API image and configured `production-alert-smtp`.
- Produces: a completed one-off success Job and a received test email.

- [ ] **Step 1: Verify CI before protected-branch merge**

Run: `$pullRequestNumber = gh pr view --json number --jq .number; gh pr checks $pullRequestNumber --repo qq550723504/edu-homework-grader`

Expected: every required check reports success before merge authorization is requested.

- [ ] **Step 2: Configure the isolated Secret interactively**

Run: `pwsh -File scripts/k8s/configure-production-alert-smtp.ps1 -ConfirmProductionAlertSmtp`

Expected: terminal prompts for the authorization code without echoing it and reports only `Secret/production-alert-smtp`.

- [ ] **Step 3: Deploy the approved main image through the existing production workflow**

Run: `gh workflow run publish-images.yml --repo qq550723504/edu-homework-grader --ref main`

Expected: the workflow patches `CronJob/production-alert` to the exact API digest.

- [ ] **Step 4: Run one one-off delivery verification Job**

Run: `$jobName = "production-alert-test-$((Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss'))"; kubectl -n edu-homework-grader create job --from=cronjob/production-alert $jobName; kubectl -n edu-homework-grader wait --for=condition=complete "job/$jobName" --timeout=5m`

Expected: the Job completes and the operator receives the single test email. Delete the completed Job after recording its name and completion time.

- [ ] **Step 5: Record only non-sensitive evidence**

Record the merged SHA, deployed API digest, one-off Job name and completion time, and received-email confirmation in `docs/operations/production-alerting.md`. Do not record the authorization code, SMTP headers, or message body.
