import re
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


def job_block(workflow: str, job_name: str) -> str:
    job_start = workflow.index(f"  {job_name}:\n")
    next_job = re.search(r"^  [a-z][a-z0-9-]*:\n", workflow[job_start + 1 :], flags=re.MULTILINE)
    next_job_start = -1 if next_job is None else job_start + 1 + next_job.start()
    return workflow[job_start:] if next_job_start == -1 else workflow[job_start:next_job_start]


def test_ci_skips_heavy_jobs_only_for_docs_only_pull_requests() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "pull-requests: read" in workflow
    assert "  changes:\n" in workflow
    assert "dorny/paths-filter@v4" in workflow
    assert "non_docs:" in workflow
    assert "predicate-quantifier: every" in workflow
    assert "'!docs/**'" in workflow
    assert "'!**/*.md'" in workflow

    for job_name in HEAVY_JOB_NAMES:
        job = job_block(workflow, job_name)
        assert "needs: changes" in job
        assert "github.event_name != 'pull_request'" in job
        assert "needs.changes.outputs.non_docs == 'true'" in job
