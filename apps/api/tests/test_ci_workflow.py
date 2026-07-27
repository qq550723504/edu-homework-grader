import os
import re
import shutil
import subprocess
from pathlib import Path

import yaml


CI_WORKFLOW_PATH = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"
PUBLISH_WORKFLOW_PATH = (
    Path(__file__).resolve().parents[3] / ".github" / "workflows" / "publish-images.yml"
)
ROLLBACK_WORKFLOW_PATH = (
    Path(__file__).resolve().parents[3] / ".github" / "workflows" / "rollback-production.yml"
)
LIVE_GENERATOR_PROVIDER_ACCEPTANCE_WORKFLOW_PATH = (
    Path(__file__).resolve().parents[3]
    / ".github"
    / "workflows"
    / "live-generator-provider-acceptance.yml"
)
HEAVY_JOB_NAMES = (
    "python",
    "migrations",
    "compose",
    "live-grader-integration",
    "web",
    "browser-e2e",
)
REVIEWED_ACTION_REFS = {
    "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
    "azure/setup-kubectl@829323503d1be3d00ca8346e5391ca0b07a9ab0d",
    "docker/build-push-action@10e90e3645eae34f1e60eeb005ba3a3d33f178e8",
    "docker/login-action@c94ce9fb468520275223c153574b00df6fe4bcc9",
    "imranismail/setup-kustomize@53f941b41dca13ed61874bbc6b4b6e1562877530",
}


def job_block(workflow: str, job_name: str) -> str:
    job_start = workflow.index(f"  {job_name}:\n")
    next_job = re.search(r"^  [a-z][a-z0-9-]*:\n", workflow[job_start + 1 :], flags=re.MULTILINE)
    next_job_start = -1 if next_job is None else job_start + 1 + next_job.start()
    return workflow[job_start:] if next_job_start == -1 else workflow[job_start:next_job_start]


def workflow_data(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def named_step(job: dict, name: str) -> dict:
    return next(step for step in job["steps"] if step.get("name") == name)


def run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def bash_executable() -> str:
    if os.name == "nt":
        git = shutil.which("git")
        assert git is not None
        git_bash = Path(git).parents[1] / "bin" / "bash.exe"
        assert git_bash.is_file()
        return str(git_bash)
    bash = shutil.which("bash")
    assert bash is not None
    return bash


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
    deploy_data = workflow_data(PUBLISH_WORKFLOW_PATH)["jobs"]["deploy"]
    steps = deploy_data["steps"]
    first_guard = named_step(deploy_data, "Reject a superseded production release")
    final_guard = named_step(deploy_data, "Recheck release immediately before deploy")
    deploy_step = named_step(deploy_data, "Deploy approved production release")

    assert "needs: [eligibility, publish]" in deploy
    assert "needs.eligibility.outputs.release_eligible == 'true'" in deploy
    assert "needs.publish.result == 'success'" in deploy
    assert re.search(
        r"environment:\n\s+name: production\n\s+url: https://edu\.getkr\.com",
        deploy,
    )
    assert deploy_data["permissions"] == {"contents": "read"}
    assert "ref: ${{ github.event.workflow_run.head_sha }}" in deploy
    assert first_guard["run"] == final_guard["run"]
    assert "git merge-base --is-ancestor" in first_guard["run"]
    assert "git diff --quiet" in first_guard["run"]
    assert ":(exclude)docs/**" in first_guard["run"]
    assert ":(exclude,glob)**/*.md" in first_guard["run"]
    assert "exit 1" in first_guard["run"]
    assert "azure/setup-kubectl@" in deploy
    assert "imranismail/setup-kustomize@" in deploy
    assert "deploy-production.ps1" in deploy
    assert '-ImageSha "${{ github.event.workflow_run.head_sha }}"' in deploy
    assert steps.index(final_guard) == steps.index(deploy_step) - 1
    assert steps.index(first_guard) < steps.index(
        named_step(deploy_data, "Configure production kubeconfig")
    )


def test_release_guard_allows_docs_only_descendant_but_rejects_code_descendant(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    run_git(source, "init", "--initial-branch=main")
    run_git(source, "config", "user.email", "ci@example.invalid")
    run_git(source, "config", "user.name", "CI Test")
    (source / "app.txt").write_text("release\n", encoding="utf-8")
    run_git(source, "add", "app.txt")
    run_git(source, "commit", "-m", "release")
    release_sha = run_git(source, "rev-parse", "HEAD").stdout.strip()

    runner = tmp_path / "runner"
    run_git(tmp_path, "clone", str(source), str(runner))
    run_git(runner, "checkout", "--detach", release_sha)

    (source / "docs").mkdir()
    (source / "docs" / "guide.txt").write_text("docs\n", encoding="utf-8")
    (source / "README.md").write_text("readme\n", encoding="utf-8")
    run_git(source, "add", "docs/guide.txt", "README.md")
    run_git(source, "commit", "-m", "docs only")

    deploy = workflow_data(PUBLISH_WORKFLOW_PATH)["jobs"]["deploy"]
    guard = named_step(deploy, "Reject a superseded production release")["run"].replace(
        "${{ github.event.workflow_run.head_sha }}",
        release_sha,
    )
    docs_result = subprocess.run(
        [bash_executable(), "-euo", "pipefail", "-c", guard],
        cwd=runner,
        capture_output=True,
        text=True,
    )
    assert docs_result.returncode == 0, docs_result.stderr

    (source / "app.txt").write_text("new release\n", encoding="utf-8")
    run_git(source, "add", "app.txt")
    run_git(source, "commit", "-m", "application change")
    code_result = subprocess.run(
        [bash_executable(), "-euo", "pipefail", "-c", guard],
        cwd=runner,
        capture_output=True,
        text=True,
    )
    assert code_result.returncode != 0
    assert "superseded" in code_result.stderr.lower()


def test_production_workflows_pin_every_action_to_an_immutable_commit() -> None:
    for path in (PUBLISH_WORKFLOW_PATH, ROLLBACK_WORKFLOW_PATH):
        workflow = workflow_data(path)
        action_refs = [
            step["uses"]
            for job in workflow["jobs"].values()
            for step in job["steps"]
            if "uses" in step
        ]

        assert action_refs
        assert all(re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", ref) for ref in action_refs)
        assert set(action_refs) <= REVIEWED_ACTION_REFS


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
    rollback = workflow_data(ROLLBACK_WORKFLOW_PATH)["jobs"]["rollback"]
    checkout = named_step(rollback, "Check out trusted deployment tooling")

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
    assert rollback["if"] == "github.ref == 'refs/heads/main'"
    assert checkout["with"]["ref"] == "main"
    assert "^[0-9a-f]{40}$" in workflow
    assert "for image in api grader web languagetool" in workflow
    assert "docker manifest inspect" in workflow
    assert "edu-homework-grader-${image}:${IMAGE_SHA}" in workflow
    assert "azure/setup-kubectl@" in workflow
    assert "imranismail/setup-kustomize@" in workflow
    assert "deploy-production.ps1" in workflow
    assert '-ImageSha "$env:IMAGE_SHA"' in workflow
    assert "git fetch origin main" not in workflow
    assert "git rev-parse origin/main" not in workflow
    assert workflow.index("Validate rollback image SHA") < workflow.index(
        "Configure production kubeconfig"
    )
    assert workflow.index("Verify rollback images exist") < workflow.index(
        "Configure production kubeconfig"
    )


def test_live_generator_acceptance_resolves_manual_refs_to_full_commit_shas() -> None:
    workflow = LIVE_GENERATOR_PROVIDER_ACCEPTANCE_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "github.rest.repos.getCommit" in workflow
    assert "ref: targetRef.trim()" in workflow
    assert "core.setOutput('target_ref', commit.data.sha);" in workflow


def test_manual_rollback_passes_github_environment_sha_to_powershell() -> None:
    rollback = workflow_data(ROLLBACK_WORKFLOW_PATH)["jobs"]["rollback"]
    deploy = named_step(rollback, "Deploy approved rollback")
    pwsh = shutil.which("pwsh")
    assert pwsh is not None
    assert deploy["shell"] == "pwsh"

    expected_sha = "a" * 40
    probe = deploy["run"].replace(
        "./scripts/k8s/deploy-production.ps1",
        "Invoke-Deploy",
    )
    script = (
        f"function Invoke-Deploy {{ param([string]$ImageSha) Write-Output $ImageSha }}\n{probe}"
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-Command", script],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "IMAGE_SHA": expected_sha},
    )

    assert result.stdout.strip() == expected_sha


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


def test_readme_links_the_production_cd_operator_runbook() -> None:
    root = Path(__file__).resolve().parents[3]

    assert (root / "docs" / "production-cd.md").is_file()
    assert "docs/production-cd.md" in (root / "README.md").read_text(encoding="utf-8")
