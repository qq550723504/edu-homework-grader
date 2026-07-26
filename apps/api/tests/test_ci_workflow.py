import re
import subprocess
from pathlib import Path


CI_WORKFLOW_PATH = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"
PUBLISH_WORKFLOW_PATH = (
    Path(__file__).resolve().parents[3] / ".github" / "workflows" / "publish-images.yml"
)
ROLLBACK_WORKFLOW_PATH = (
    Path(__file__).resolve().parents[3] / ".github" / "workflows" / "rollback-production.yml"
)
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


def test_ci_runs_for_pull_requests_and_merged_main_revisions() -> None:
    workflow = CI_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "pull_request:" in workflow
    assert re.search(r"push:\n\s+branches: \[main\]", workflow)


def test_publish_waits_for_successful_main_ci_and_uses_its_head_sha() -> None:
    workflow = PUBLISH_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "workflow_run:" in workflow
    assert 'workflows: ["CI"]' in workflow
    assert "types: [completed]" in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.event == 'push'" in workflow
    assert "github.event.workflow_run.head_branch == 'main'" in workflow
    assert "github.event.workflow_run.head_sha" in workflow
    assert "production-release" in workflow


def test_publish_docs_only_gate_excludes_root_markdown() -> None:
    workflow = PUBLISH_WORKFLOW_PATH.read_text(encoding="utf-8")
    eligibility = job_block(workflow, "eligibility")
    root = PUBLISH_WORKFLOW_PATH.parents[2]
    remaining_paths = subprocess.run(
        [
            "git",
            "ls-files",
            "--",
            ".",
            ":(exclude)docs/**",
            ":(exclude)*.md",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    assert "README.md" not in remaining_paths
    assert "CONTRIBUTING.md" not in remaining_paths
    assert "git diff --quiet HEAD^ HEAD -- . ':(exclude)docs/**' ':(exclude)*.md'" in eligibility


def test_release_deploy_is_approved_pinned_and_rejects_superseded_main() -> None:
    workflow = PUBLISH_WORKFLOW_PATH.read_text(encoding="utf-8")
    deploy = job_block(workflow, "deploy")

    assert "needs: [eligibility, publish]" in deploy
    assert "needs.eligibility.outputs.release_eligible == 'true'" in deploy
    assert "needs.publish.result == 'success'" in deploy
    assert re.search(
        r"environment:\n\s+name: production\n\s+url: https://edu\.getkr\.com",
        deploy,
    )
    assert re.search(
        r"permissions:\n\s+contents: read\n\s+packages: read",
        deploy,
    )
    assert "ref: ${{ github.event.workflow_run.head_sha }}" in deploy
    assert "git fetch origin main:refs/remotes/origin/main --depth=1" in deploy
    assert "git rev-parse origin/main" in deploy
    assert 'release_sha="${{ github.event.workflow_run.head_sha }}"' in deploy
    guard = deploy.split("- name: Reject a superseded production release", maxsplit=1)[1].split(
        "- name: Install kubectl", maxsplit=1
    )[0]
    assert 'if [[ "$release_sha" != "$main_sha" ]]' in guard
    assert "exit 1" in guard
    assert "exit 0" not in guard
    assert "azure/setup-kubectl@" in deploy
    assert "imranismail/setup-kustomize@" in deploy
    assert "deploy-production.ps1" in deploy
    assert '-ImageSha "${{ github.event.workflow_run.head_sha }}"' in deploy
    assert deploy.index("Reject a superseded production release") < deploy.index(
        "Configure production kubeconfig"
    )


def test_release_deploy_keeps_kubeconfig_secret_out_of_logs_and_always_cleans_up() -> None:
    deploy = job_block(
        PUBLISH_WORKFLOW_PATH.read_text(encoding="utf-8"),
        "deploy",
    )

    assert "KUBECONFIG_B64: ${{ secrets.KUBECONFIG_B64 }}" in deploy
    assert 'kubeconfig_path="$RUNNER_TEMP/production-kubeconfig"' in deploy
    assert "printf '%s' \"$KUBECONFIG_B64\" | base64 --decode" in deploy
    assert 'echo "KUBECONFIG=$kubeconfig_path" >> "$GITHUB_ENV"' in deploy
    assert 'echo "$KUBECONFIG_B64"' not in deploy
    assert 'KUBECONFIG_B64" >> "$GITHUB_ENV"' not in deploy
    assert "if: ${{ always() }}" in deploy
    assert 'rm -f -- "$RUNNER_TEMP/production-kubeconfig"' in deploy


def test_manual_rollback_is_dispatch_only_approved_and_checks_all_sha_images() -> None:
    workflow = ROLLBACK_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "image_sha:" in workflow
    assert "required: true" in workflow
    assert "type: string" in workflow
    assert "workflow_run:" not in workflow
    assert "pull_request:" not in workflow
    assert re.search(r"(?m)^\s+push:\s*$", workflow) is None
    assert "group: production-release" in workflow
    assert "cancel-in-progress: false" in workflow
    assert re.search(
        r"environment:\n\s+name: production\n\s+url: https://edu\.getkr\.com",
        workflow,
    )
    assert "^[0-9a-f]{40}$" in workflow
    assert "for image in api grader web languagetool" in workflow
    assert "docker manifest inspect" in workflow
    assert "edu-homework-grader-${image}:${IMAGE_SHA}" in workflow
    assert "azure/setup-kubectl@" in workflow
    assert "imranismail/setup-kustomize@" in workflow
    assert "deploy-production.ps1" in workflow
    assert '-ImageSha "$IMAGE_SHA"' in workflow
    assert "git fetch origin main" not in workflow
    assert "git rev-parse origin/main" not in workflow
    assert workflow.index("Validate rollback image SHA") < workflow.index(
        "Configure production kubeconfig"
    )
    assert workflow.index("Verify rollback images exist") < workflow.index(
        "Configure production kubeconfig"
    )


def test_manual_rollback_uses_safe_temporary_kubeconfig_and_always_cleans_up() -> None:
    workflow = ROLLBACK_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert re.search(
        r"permissions:\n\s+contents: read\n\s+packages: read",
        workflow,
    )
    assert "KUBECONFIG_B64: ${{ secrets.KUBECONFIG_B64 }}" in workflow
    assert 'kubeconfig_path="$RUNNER_TEMP/production-kubeconfig"' in workflow
    assert "printf '%s' \"$KUBECONFIG_B64\" | base64 --decode" in workflow
    assert 'echo "KUBECONFIG=$kubeconfig_path" >> "$GITHUB_ENV"' in workflow
    assert 'echo "$KUBECONFIG_B64"' not in workflow
    assert 'KUBECONFIG_B64" >> "$GITHUB_ENV"' not in workflow
    assert "if: ${{ always() }}" in workflow
    assert 'rm -f -- "$RUNNER_TEMP/production-kubeconfig"' in workflow
