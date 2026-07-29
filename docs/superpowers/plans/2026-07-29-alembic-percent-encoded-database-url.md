# Alembic Percent-Encoded Database URL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow the PostgreSQL migration Job to use valid percent-encoded passwords without passing them through `ConfigParser`.

**Architecture:** The online Alembic path creates a SQLAlchemy engine directly from `settings.database_url`. This removes the configuration-parser boundary from runtime credentials, preserves `NullPool`, and leaves offline generation unchanged.

**Tech Stack:** Python 3.13, Alembic, SQLAlchemy 2.x, pytest, GitHub Actions, Kubernetes.

## Global Constraints

- Do not log, commit, or expose runtime database or COS credentials.
- Preserve `pool.NullPool` for one-off Alembic migration connections.
- Prove the regression with a percent-encoded URL before changing production code.
- Use an immutable GHCR digest for the live migration Job.
- Restrict Kubernetes operations to `pilot-64.90.22.137` and `edu-homework-grader`.

---

### Task 1: Capture and repair the Alembic configuration regression

**Files:**
- Create: `apps/api/tests/test_alembic_url_configuration.py`
- Modify: `apps/api/alembic/env.py:10-20,48-53`
- Test: `apps/api/tests/test_alembic_url_configuration.py`

**Interfaces:**
- Consumes: `settings.database_url: str`.
- Produces: online connection construction with `create_engine(settings.database_url, poolclass=pool.NullPool)`.

- [x] **Step 1: Write the failing test**

```python
import os
from pathlib import Path
import subprocess
import sys


def test_offline_alembic_migrations_accept_a_percent_encoded_database_url() -> None:
    api_root = Path(__file__).parents[1]
    environment = os.environ.copy()
    environment["DATABASE_URL"] = (
        "postgresql+psycopg://edu_grader:encoded%2Fpassword@postgres:5432/edu_grader"
    )

    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "0001", "--sql"],
        cwd=api_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "invalid interpolation syntax" not in completed.stderr
```

- [x] **Step 2: Run the test and confirm red**

Run: `python -m pytest apps/api/tests/test_alembic_url_configuration.py -q`

Expected: `FAIL` with `ValueError: invalid interpolation syntax` from `config.set_main_option`.

- [x] **Step 3: Make the minimal implementation change**

Replace the SQLAlchemy import and online connection construction with:

```python
from sqlalchemy import create_engine, inspect, pool, text

config = context.config


def run_migrations_online() -> None:
    connectable = create_engine(settings.database_url, poolclass=pool.NullPool)
```

Delete `config.set_main_option("sqlalchemy.url", settings.database_url)` and delete the `engine_from_config(...)` call.

- [x] **Step 4: Verify green and focused migration coverage**

Run:

```powershell
python -m pytest apps/api/tests/test_alembic_url_configuration.py -q
python -m pytest apps/api/tests/test_curriculum_models.py apps/api/tests/test_question_models.py -q
```

Expected: all selected tests pass.

- [x] **Step 5: Commit**

```powershell
git add apps/api/alembic/env.py apps/api/tests/test_alembic_url_configuration.py
git commit -m "fix: support percent encoded Alembic database URLs"
```

### Task 2: Build and run the immutable migration image

**Files:**
- No source changes.

**Interfaces:**
- Consumes: the pushed fix commit and label `build-migration-image` on PR `#158`.
- Produces: a validated digest-pinned GHCR API image and a successful one-time migration Job.

- [x] **Step 1: Push and trigger a new image build**

Run:

```powershell
git push origin codex/postgres-cos-backup-design
Remove-Item Env:HTTP_PROXY -ErrorAction SilentlyContinue
Remove-Item Env:HTTPS_PROXY -ErrorAction SilentlyContinue
gh api --method DELETE repos/qq550723504/edu-homework-grader/issues/158/labels/build-migration-image
gh api --method POST repos/qq550723504/edu-homework-grader/issues/158/labels -f 'labels[]=build-migration-image'
```

Expected: a `Build API migration image` run starts for the current branch SHA.

- [x] **Step 2: Validate the immutable artifact**

Run:

```powershell
$run = gh run list --workflow 'Build API migration image' --branch codex/postgres-cos-backup-design --limit 1 --json databaseId,status,headSha | ConvertFrom-Json
if ($run.status -ne 'completed' -or $run.headSha -ne (git rev-parse HEAD)) { throw 'Expected migration-image build is not complete for HEAD.' }
$artifactDirectory = Join-Path $env:TEMP ("edu-grader-migration-image-" + $run.databaseId)
gh run download $run.databaseId -n api-migration-image-digest -D $artifactDirectory
$digest = (Get-Content (Join-Path $artifactDirectory 'api-migration-image-digest.txt') -Raw).Trim()
if ($digest -notmatch '^sha256:[a-f0-9]{64}$') { throw 'Migration image digest is invalid.' }
$image = "ghcr.io/qq550723504/edu-homework-grader-api@$digest"
```

Expected: `$image` is a digest-pinned GHCR reference derived from the completed HEAD workflow.

- [x] **Step 3: Run and inspect migration completion**

Run:

```powershell
kubectl config current-context
.\scripts\k8s\run-postgres-migration.ps1 -Namespace edu-homework-grader -Image $image -ConfirmMigration
```

Expected: context is `pilot-64.90.22.137`, the Job completes, and it reports revision `0026_question_content_snapshots`.

### Task 3: Refresh COS recovery evidence on migrated data

**Files:**
- Modify: `docs/operations/postgres-cos-backup-recovery.md` only if the drill succeeds.

**Interfaces:**
- Consumes: the migrated schema, existing backup CronJob, and isolated recovery drill.
- Produces: a fresh successful backup and recovery evidence record without credentials.

- [x] **Step 1: Run a fresh backup**

Run:

```powershell
$jobName = 'postgres-backup-manual-' + (Get-Date -AsUTC -Format 'yyyyMMddHHmmss')
kubectl -n edu-homework-grader create job --from=cronjob/postgres-backup $jobName
kubectl -n edu-homework-grader wait --for=condition=complete "job/$jobName" --timeout=15m
$backupTimestamp = (kubectl -n edu-homework-grader logs "job/$jobName" | Select-String '^backup_timestamp=').Line.Split('=')[1]
```

Expected: the Job completes and logs a UTC COS timestamp.

- [x] **Step 2: Run the isolated recovery drill**

Run:

```powershell
.\scripts\k8s\recovery-drill.ps1 `
  -Namespace edu-homework-grader `
  -BackupTimestamp $backupTimestamp `
  -ConfirmRecovery
```

Expected: checksum verification, isolated restore, and migrated-table checks succeed.

- [x] **Step 3: Record verified evidence**

Update the runbook with the timestamp, successful Job names, and immutable migration image digest. Run `git diff --check`; commit only the runbook evidence update.
