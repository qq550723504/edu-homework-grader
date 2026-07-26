# Production CD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Release a successful main merge through one approved, SHA-pinned Kubernetes deployment with health verification, automatic rollback and a reviewed manual rollback path.

**Architecture:** CI validates pull requests and main. A workflow-run release pipeline builds immutable images for the exact successful CI SHA, waits at the production Environment, and calls a PowerShell deploy script. That script renders a temporary namespace-only Kustomize copy, applies the SHA, verifies health, and restores captured images on failure.

**Tech Stack:** GitHub Actions, GitHub Environments, GHCR, Kubernetes RBAC, Kustomize, PowerShell 7, Pester and pytest.

## Global Constraints

- Namespace is edu-homework-grader; public URL is https://edu.getkr.com.
- The protected GitHub Environment is named production, owns KUBECONFIG_B64,
  has required reviewers and restricts deployment branches server-side to
  protected main.
- Only lower-case 40-character Git SHAs are valid image versions.
- The deploy identity cannot read or mutate Kubernetes Secrets, Pods, pod subresources or cluster-scoped resources.
- The deploy Role grants `get`, `watch` and `patch` only on Deployments api,
  grader, web and languagetool; `get` and `patch` only on CronJob
  student-activation-expiry; and `get` only on the Endpoints object api.
- The bootstrap command accepts no repository destination: it writes only to `qq550723504/edu-homework-grader` production after validating the TokenRequest lifetime is at least 30 days.
- Automatic release checks out github.event.workflow_run.head_sha; manual
  rollback checks out trusted main deployment tooling.
- Pin api, grader, web, languagetool and the API expiry CronJob to the same GHCR SHA.
- Release and rollback share concurrency group production-release with cancel-in-progress false.
- Automatic release allows docs/** and Markdown-only descendants of its SHA,
  but rejects a non-ancestor or any later non-documentation source/config
  change. It checks once before loading kubeconfig and again immediately before
  deployment.
- Do not add Argo CD, Flux, canary delivery, secret rotation or database recovery work.

---

### Task 1: Gate image publication on successful main CI

**Files:**
- Modify: .github/workflows/ci.yml
- Modify: .github/workflows/publish-images.yml
- Modify: apps/api/tests/test_ci_workflow.py

**Interfaces:**
- Consumes: CI workflow-run conclusion, event, head_branch and head_sha.
- Produces: release_eligible and four immutable GHCR images built from the exact head SHA.

- [ ] **Step 1: Add failing workflow contract tests**

Add this to apps/api/tests/test_ci_workflow.py:

~~~python
PUBLISH_WORKFLOW_PATH = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "publish-images.yml"

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
~~~

- [ ] **Step 2: Verify RED**

Run:

~~~powershell
python -m pytest apps/api/tests/test_ci_workflow.py -q
~~~

Expected: FAIL because CI lacks a main push trigger and publishing still triggers directly on push.

- [ ] **Step 3: Implement the CI and release gates**

Set the ci.yml events to pull_request, push branches main, and workflow_dispatch. Change publish-images.yml to a workflow_run completion of CI. Add:

~~~yaml
concurrency:
  group: production-release
  cancel-in-progress: false
~~~

Create an eligibility job that runs only when the CI event is a successful push on main, checks out the workflow-run head SHA at depth two, and writes release_eligible=false for a docs-only diff:

~~~bash
git diff --quiet HEAD^ HEAD -- docs '*.md'
~~~

Make the matrix publish job depend on eligibility, run only when eligible, and use the workflow-run head SHA for every image tag. Retain packages write, all existing Docker contexts and fail-fast false.

- [ ] **Step 4: Verify GREEN and commit**

Run:

~~~powershell
python -m pytest apps/api/tests/test_ci_workflow.py -q
git diff --check
git add .github/workflows/ci.yml .github/workflows/publish-images.yml apps/api/tests/test_ci_workflow.py
git commit -m "ci: gate production images on main CI"
~~~

Expected: tests and whitespace check pass.

### Task 2: Create a least-privilege deploy identity

**Files:**
- Create: infra/k8s/production/github-production-deployer-rbac.yaml
- Create: scripts/k8s/bootstrap-production-deployer.ps1
- Create: scripts/k8s/bootstrap-production-deployer.tests.ps1

**Interfaces:**
- Consumes: an administrator kubectl context, authenticated gh and namespace edu-homework-grader.
- Produces: ServiceAccount github-production-deployer, namespace Role and RoleBinding, and Environment secret KUBECONFIG_B64 without writing credential material to disk or output.

- [ ] **Step 1: Add failing Pester tests**

Create scripts/k8s/bootstrap-production-deployer.tests.ps1:

~~~powershell
$scriptPath = Join-Path $PSScriptRoot 'bootstrap-production-deployer.ps1'
$rbacPath = Join-Path $PSScriptRoot '..\..\infra\k8s\production\github-production-deployer-rbac.yaml'

Describe 'bootstrap-production-deployer' {
    It 'requires confirmation before creating a deploy credential' {
        { & $scriptPath -WhatIf } |
            Should Throw '*-ConfirmProductionCredential*'
    }
    It 'does not print credentials' {
        $source = Get-Content -Raw $scriptPath
        $source | Should Not Match 'Write-(Host|Output).*?(TOKEN|KUBECONFIG|SECRET)'
        $source | Should Match 'gh secret set KUBECONFIG_B64 --env production'
        $source | Should Match 'kubectl create token'
    }
    It 'excludes Secrets and cluster-wide RBAC' {
        $manifest = Get-Content -Raw $rbacPath
        $manifest | Should Match 'kind: ServiceAccount'
        $manifest | Should Match 'kind: RoleBinding'
        $manifest | Should Match 'deployments'
        $manifest | Should Match 'cronjobs'
        $manifest | Should Not Match 'secrets'
        $manifest | Should Not Match 'ClusterRole'
        $manifest | Should Not Match 'pods/exec|pods/attach|pods/portforward'
    }
    It 'validates the issued token lifetime before uploading it' {
        $source = Get-Content -Raw $scriptPath
        $source | Should Match 'MinimumTokenLifetimeHours'
        $source | Should Match 'TokenRequest lifetime'
    }
}
~~~

- [ ] **Step 2: Verify RED**

Run:

~~~powershell
Invoke-Pester scripts/k8s/bootstrap-production-deployer.tests.ps1
~~~

Expected: FAIL because both files are absent.

- [ ] **Step 3: Implement RBAC and confirmed bootstrap**

Define one ServiceAccount, Role and RoleBinding in edu-homework-grader. The
final Role grants `get`, `watch` and `patch` on the four named Deployments
(`api`, `grader`, `web`, `languagetool`), `get` and `patch` on the named
`student-activation-expiry` CronJob, and `get` on the named `api` Endpoints
object. It grants nothing for StatefulSets, ConfigMaps, Services, Ingresses,
Secrets, Pods or pod subresources. Do not add it to the normal production
kustomization.

Use this script boundary:

~~~powershell
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Namespace = 'edu-homework-grader',
    [switch]$ConfirmProductionCredential,
    [int]$MinimumTokenLifetimeHours = 720
)

if (-not $ConfirmProductionCredential) {
    throw 'Pass -ConfirmProductionCredential to create the GitHub production deploy credential.'
}
if (-not $PSCmdlet.ShouldProcess('qq550723504/edu-homework-grader production environment', 'replace KUBECONFIG_B64')) { return }

& kubectl apply --server-side --filename $rbacManifest
$token = & kubectl create token github-production-deployer --namespace $Namespace --duration=8760h
[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($deployKubeconfig)) |
    & gh secret set KUBECONFIG_B64 --env production --repo qq550723504/edu-homework-grader
~~~

Build deployKubeconfig with only the cluster, context and deployer token. Decode only the JWT payload in memory, require exp minus now to meet MinimumTokenLifetimeHours, and throw TokenRequest lifetime is shorter than the required minimum before calling gh when it does not. Use Write-Information for resource names only.

- [ ] **Step 4: Verify GREEN and commit**

Run:

~~~powershell
Install-Module Pester -Scope CurrentUser -Force -MinimumVersion 5.5.0
Invoke-Pester scripts/k8s/bootstrap-production-deployer.tests.ps1
kubectl apply --dry-run=client --filename infra/k8s/production/github-production-deployer-rbac.yaml
git add infra/k8s/production/github-production-deployer-rbac.yaml scripts/k8s/bootstrap-production-deployer.ps1 scripts/k8s/bootstrap-production-deployer.tests.ps1
git commit -m "feat: add production deploy identity bootstrap"
~~~

Expected: tests and client render pass without credential output.

### Task 3: Implement SHA-pinned deploy and rollback

**Files:**
- Create: scripts/k8s/deploy-production.ps1
- Create: scripts/k8s/deploy-production.tests.ps1
- Modify: infra/k8s/production/kustomization.yaml only if a release-safe resource list is needed

**Interfaces:**
- Consumes: ImageSha or an exact managed-image map, KUBECONFIG, production manifests and https://edu.getkr.com.
- Produces: redacted summary; zero only after four Deployment rollouts, ready API Service endpoints and public health. Failure restores captured images before throwing.

- [ ] **Step 1: Add failing Pester tests**

Create scripts/k8s/deploy-production.tests.ps1:

~~~powershell
$scriptPath = Join-Path $PSScriptRoot 'deploy-production.ps1'

Describe 'deploy-production' {
    It 'rejects mutable image references before kubectl runs' {
        Mock kubectl { throw 'kubectl must not run' }
        { & $scriptPath -ImageSha 'latest' } | Should Throw '*40-character lower-case Git SHA*'
        Assert-MockCalled kubectl -Times 0
    }
    It 'rolls back captured images after rollout failure' {
        Mock kubectl {
            param([Parameter(ValueFromRemainingArguments = $true)]$Arguments)
            if (($Arguments -join ' ') -match 'rollout status') { throw 'rollout timed out' }
            return '{"items":[]}'
        }
        { & $scriptPath -ImageSha ('a' * 40) -SkipPublicHealthCheck } | Should Throw '*rollback*'
        Assert-MockCalled kubectl -ParameterFilter { ($Arguments -join ' ') -match 'apply' } -Times 2
    }
    It 'does not query or print Secrets' {
        $source = Get-Content -Raw $scriptPath
        $source | Should Not Match 'get secret|create secret|Write-(Host|Output).*?(TOKEN|PASSWORD|SECRET|KUBECONFIG)'
        $source | Should Match 'get endpoints api'
        $source | Should Match 'https://edu.getkr.com/'
    }
}
~~~

- [ ] **Step 2: Verify RED**

Run:

~~~powershell
Invoke-Pester scripts/k8s/deploy-production.tests.ps1
~~~

Expected: FAIL because the script does not exist.

- [ ] **Step 3: Implement temporary Kustomize render and restore**

Implement Assert-ImageSha, Get-ManagedImages, New-RenderedRelease, Wait-ProductionHealthy and Restore-ManagedImages. New-RenderedRelease accepts either a validated ImageSha (for a new release) or the exact image map returned by Get-ManagedImages (for rollback); it must not infer rollback versions from a tag.

~~~powershell
function Assert-ImageSha([string]$ImageSha) {
    if ($ImageSha -notmatch '^[0-9a-f]{40}$') {
        throw 'ImageSha must be a 40-character lower-case Git SHA.'
    }
}
function New-RenderedRelease([string]$Sha, [string]$Destination) {
    Copy-Item $ProductionManifestPath $Destination -Recurse
    $kustomization = Join-Path $Destination 'kustomization.yaml'
    $copiedKustomization = Get-Content -Raw $kustomization
    $withoutNamespace = $copiedKustomization -replace '(?m)^\s*-\s+namespace\.yaml\r?\n', ''
    Set-Content -LiteralPath $kustomization -Value $withoutNamespace -NoNewline
    Push-Location $Destination
    try {
        & kustomize edit set image "ghcr.io/qq550723504/edu-homework-grader-api=ghcr.io/qq550723504/edu-homework-grader-api:$Sha"
        & kustomize edit set image "ghcr.io/qq550723504/edu-homework-grader-grader=ghcr.io/qq550723504/edu-homework-grader-grader:$Sha"
        & kustomize edit set image "ghcr.io/qq550723504/edu-homework-grader-web=ghcr.io/qq550723504/edu-homework-grader-web:$Sha"
        & kustomize edit set image "ghcr.io/qq550723504/edu-homework-grader-languagetool=ghcr.io/qq550723504/edu-homework-grader-languagetool:$Sha"
        return (& kustomize build .)
    } finally { Pop-Location }
}
~~~

Capture API, Grader, Web, LanguageTool and expiry CronJob images before applying rendered YAML with server-side kubectl. Wait for all four Deployments, poll `kubectl get endpoints api --output json` until it has a ready address (the API Deployment readiness probe already calls `/ready`), then check https://edu.getkr.com/ from the runner. On any failure call New-RenderedRelease with the captured image map, apply that result, recheck rollouts, and throw Production release sha failed; rollback succeeded or failed. Remove the temporary directory in finally.

- [ ] **Step 4: Verify GREEN and commit**

Run:

~~~powershell
Invoke-Pester scripts/k8s/deploy-production.tests.ps1
kustomize build infra/k8s/production | Select-String 'sha-not-published'
git add scripts/k8s/deploy-production.ps1 scripts/k8s/deploy-production.tests.ps1 infra/k8s/production/kustomization.yaml
git commit -m "feat: add production deployment rollback script"
~~~

Expected: Pester passes and placeholders remain only in the committed base.

### Task 4: Wire approved deploy and manual rollback workflows

**Files:**
- Modify: .github/workflows/publish-images.yml
- Create: .github/workflows/rollback-production.yml
- Modify: apps/api/tests/test_ci_workflow.py

**Interfaces:**
- Consumes: release_eligible, deploy-production.ps1, KUBECONFIG_B64 and the CI head SHA.
- Produces: approved deploy job and dispatch-only rollback workflow with image_sha input.

- [ ] **Step 1: Add failing workflow tests**

Append:

~~~python
ROLLBACK_WORKFLOW_PATH = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "rollback-production.yml"

def test_release_deploy_is_production_approved_and_pins_the_ci_sha() -> None:
    deploy = job_block(PUBLISH_WORKFLOW_PATH.read_text(encoding="utf-8"), "deploy")
    assert "needs: publish" in deploy
    assert "production" in deploy
    assert "KUBECONFIG_B64" in deploy
    assert "github.event.workflow_run.head_sha" in deploy
    assert "git fetch origin main" in deploy
    assert "deploy-production.ps1" in deploy

def test_manual_rollback_requires_a_sha_and_production_approval() -> None:
    workflow = ROLLBACK_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "image_sha:" in workflow and "required: true" in workflow
    assert "production" in workflow
    assert "docker manifest inspect" in workflow
    assert "deploy-production.ps1" in workflow
~~~

- [ ] **Step 2: Verify RED**

Run:

~~~powershell
python -m pytest apps/api/tests/test_ci_workflow.py -q
~~~

Expected: FAIL because deploy and rollback workflow are absent.

- [ ] **Step 3: Add approved deploy**

Append deploy after the publish matrix. It needs publish, uses Environment
production with URL https://edu.getkr.com and only `contents: read`. It checks
out the CI head SHA with full history, installs kubectl and Kustomize, and
rejects a target that is not an ancestor of `origin/main` or whose descendant
range contains a change outside `docs/**` and Markdown files. It then decodes
KUBECONFIG_B64 to RUNNER_TEMP/production-kubeconfig, writes only its path to
GITHUB_ENV, repeats the same docs-aware supersession guard immediately before
invoking deploy-production.ps1 with the head SHA, and deletes the temporary
kubeconfig in an always cleanup step.

- [ ] **Step 4: Add manual rollback**

Create .github/workflows/rollback-production.yml:

~~~yaml
name: Roll back production
on:
  workflow_dispatch:
    inputs:
      image_sha:
        description: Immutable 40-character commit SHA to deploy
        required: true
        type: string
concurrency:
  group: production-release
  cancel-in-progress: false
~~~

Its one main-only production job checks out trusted `main` tooling. The
Environment approval protects the whole job and therefore occurs before any
step. After approval, it rejects input not matching ^[0-9a-f]{40}$ and verifies
each of four GHCR images with docker manifest inspect, retaining
`packages: read` only for that registry preflight, before configuring the
temporary kubeconfig or accessing the cluster. It invokes deploy-production.ps1
with the validated SHA and intentionally has no latest-main image guard.

- [ ] **Step 5: Verify GREEN and commit**

Run:

~~~powershell
python -m pytest apps/api/tests/test_ci_workflow.py -q
git diff --check
git add .github/workflows/publish-images.yml .github/workflows/rollback-production.yml apps/api/tests/test_ci_workflow.py
git commit -m "ci: deploy approved production releases"
~~~

Expected: both checks pass.

### Task 5: Document and verify the operator path

**Files:**
- Create: docs/production-cd.md
- Modify: README.md
- Modify: apps/api/tests/test_ci_workflow.py

**Interfaces:**
- Consumes: bootstrap command, production approval and rollback workflow.
- Produces: an operator runbook for setup, approval, automatic rollback and manual rollback.

- [ ] **Step 1: Write failing runbook-link test**

Add:

~~~python
def test_readme_links_the_production_cd_operator_runbook() -> None:
    root = Path(__file__).resolve().parents[3]
    assert (root / "docs" / "production-cd.md").is_file()
    assert "docs/production-cd.md" in (root / "README.md").read_text(encoding="utf-8")
~~~

- [ ] **Step 2: Verify RED**

Run:

~~~powershell
python -m pytest apps/api/tests/test_ci_workflow.py::test_readme_links_the_production_cd_operator_runbook -q
~~~

Expected: FAIL because the runbook and README link are absent.

- [ ] **Step 3: Write the runbook**

Create docs/production-cd.md covering: create production reviewers and run confirmed bootstrap; merge green PR and approve production; automatic rollback and response to rollback failure; Actions manual rollback using a prior SHA; and kubeconfig handling and rotation after revocation. Link it in README:

~~~markdown
- [Production CD operator runbook](docs/production-cd.md)
~~~

- [ ] **Step 4: Run final verification**

Run:

~~~powershell
python -m pytest apps/api/tests/test_ci_workflow.py -q
Invoke-Pester scripts/k8s/bootstrap-production-deployer.tests.ps1
Invoke-Pester scripts/k8s/deploy-production.tests.ps1
cd apps/web; npm test
cd ../..
git diff origin/main...HEAD --check
~~~

Expected: all checks pass. Reviewer setup and the first real production approval remain authorized operator actions after merge.

- [ ] **Step 5: Commit Task 5**

~~~powershell
git add docs/production-cd.md README.md apps/api/tests/test_ci_workflow.py
git commit -m "docs: add production CD operator runbook"
~~~
