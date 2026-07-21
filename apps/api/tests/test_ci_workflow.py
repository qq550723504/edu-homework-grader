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


def test_ci_completes_required_jobs_without_heavy_steps_for_docs_only_pull_requests() -> None:
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
        assert "if: github.event_name != 'pull_request'" not in job
        assert "Skip docs-only pull request" in job
        assert "if: needs.changes.outputs.non_docs != 'true'" in job
        assert "if: needs.changes.outputs.non_docs == 'true'" in job

    for job_name in ("web", "browser-e2e"):
        job = job_block(workflow, job_name)
        assert re.search(
            r"- name: Skip docs-only pull request\n"
            r"\s+if: needs\.changes\.outputs\.non_docs != 'true'\n"
            r"\s+working-directory: \.\n"
            r"\s+run: echo",
            job,
        )
