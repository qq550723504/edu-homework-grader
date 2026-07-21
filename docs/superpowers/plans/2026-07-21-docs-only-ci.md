# Docs-Only CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Skip expensive CI jobs for documentation-only pull requests while preserving successful required-check statuses.

**Architecture:** Keep the existing `CI` workflow triggers. A `changes` job uses `dorny/paths-filter@v3` to expose a `non_docs` output; each existing heavy job depends on that job and runs for non-pull-request events or when the pull request includes a non-document file. A focused pytest regression test protects the workflow contract.

**Tech Stack:** GitHub Actions, `dorny/paths-filter@v3`, pytest, Ruff.

## Global Constraints

- Documentation-only means files under `docs/**` and `*.md` files anywhere in the repository.
- Any non-document file, including `.github/**`, must run the complete CI workflow.
- `push` to `main` and `workflow_dispatch` must always run the complete CI workflow.
- Do not add workflow-level `paths-ignore`; required checks must not remain pending.

---

### Task 1: Add a workflow contract regression test

**Files:**
- Create: `apps/api/tests/test_ci_workflow.py`

**Interfaces:**
- Consumes: repository-root `.github/workflows/ci.yml`.
- Produces: `test_ci_skips_heavy_jobs_only_for_docs_only_pull_requests()`.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path


CI_WORKFLOW_PATH = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"
HEAVY_JOB_NAMES = (
    "python",
    "migrations",
    "compose",
    "live-grader-integration",
    "web",
    "browser-e2e",
)


def test_ci_skips_heavy_jobs_only_for_docs_only_pull_requests() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "changes:" in workflow
    assert "dorny/paths-filter@v3" in workflow
    assert "non_docs:" in workflow
    assert "'docs/**'" in workflow
    assert "'**/*.md'" in workflow

    for job_name in HEAVY_JOB_NAMES:
        job_start = workflow.index(f"  {job_name}:\n")
        job_end = workflow.find("\n  ", job_start + 1)
        job = workflow[job_start:] if job_end == -1 else workflow[job_start:job_end]
        assert "needs: changes" in job
        assert "github.event_name != 'pull_request'" in job
        assert "needs.changes.outputs.non_docs == 'true'" in job
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `$env:PYTHONPATH='apps/api/src'; python -m pytest apps/api/tests/test_ci_workflow.py -q`

Expected: FAIL because the existing workflow has no `changes` job or `non_docs` filter.

- [ ] **Step 3: Commit after the workflow implementation in Task 2**

```powershell
git add apps/api/tests/test_ci_workflow.py .github/workflows/ci.yml
git commit -m "ci: skip heavy checks for docs-only pull requests"
```

### Task 2: Gate existing heavy jobs on non-document changes

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `changes.outputs.non_docs` from the new `changes` job.
- Produces: skipped-success jobs for documentation-only pull requests and full execution otherwise.

- [ ] **Step 1: Add the `changes` job before `python`**

```yaml
  changes:
    runs-on: ubuntu-latest
    outputs:
      non_docs: ${{ steps.filter.outputs.non_docs }}
    steps:
      - uses: actions/checkout@v4
      - uses: dorny/paths-filter@v3
        id: filter
        with:
          filters: |
            non_docs:
              - '**'
              - '!docs/**'
              - '!**/*.md'
```

- [ ] **Step 2: Gate every expensive job**

For each of `python`, `migrations`, `compose`, `live-grader-integration`, `web`, and `browser-e2e`, add:

```yaml
    needs: changes
    if: github.event_name != 'pull_request' || needs.changes.outputs.non_docs == 'true'
```

Place the fields directly below each job's name and before `runs-on` or `defaults`.

- [ ] **Step 3: Run the regression test to verify it passes**

Run: `$env:PYTHONPATH='apps/api/src'; python -m pytest apps/api/tests/test_ci_workflow.py -q`

Expected: `1 passed`.

### Task 3: Verify the workflow change and publish it

**Files:**
- Verify: `.github/workflows/ci.yml`
- Verify: `apps/api/tests/test_ci_workflow.py`

**Interfaces:**
- Consumes: final workflow and regression test from Tasks 1-2.
- Produces: a clean branch ready for pull-request CI.

- [ ] **Step 1: Validate the complete Python test suite**

Run: `$env:PYTHONPATH='apps/api/src'; python -m pytest apps/api/tests -q`

Expected: all tests pass, with the existing single skipped test unchanged.

- [ ] **Step 2: Validate Python formatting and linting**

Run: `python -m ruff format --check packages/processor-policy apps/api services/grader`

Expected: all files already formatted.

Run: `python -m ruff check packages/processor-policy apps/api services/grader`

Expected: all checks passed.

- [ ] **Step 3: Inspect the final patch and commit**

Run: `git diff --check`

Expected: exit code 0.

```powershell
git add .github/workflows/ci.yml apps/api/tests/test_ci_workflow.py
git commit -m "ci: skip heavy checks for docs-only pull requests"
git push -u origin codex/ci-skip-docs-checks
```
