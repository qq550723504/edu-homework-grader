# Operational Evaluation OIDC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run protected production operational evaluations through GitHub OIDC and an ephemeral in-cluster Job without exposing PostgreSQL or a long-lived credential to GitHub Actions.

**Architecture:** A GitHub-hosted job in the protected environment obtains a short-lived OIDC JWT and calls an API control plane. The API verifies immutable repository and workflow claims, persists an idempotent run, and creates a constrained Kubernetes Job. The Job reads production facts through a distinct `SELECT`-only database role, signs a redacted report, and returns it through a one-time callback. The API retains the signed report and audit metadata for 30 days.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, PyJWT, official Kubernetes Python client, Kubernetes RBAC/NetworkPolicy/Job/CronJob, GitHub Actions OIDC.

## Global Constraints

- GitHub OIDC issuer is `https://token.actions.githubusercontent.com`; no static GitHub webhook secret or PAT is used.
- Accept only `qq550723504/edu-homework-grader`, its immutable repository and owner IDs, `repository_visibility=public`, `refs/heads/main`, `workflow_dispatch`, `ai-evaluation-operational`, `.github/workflows/ai-evaluation-operational.yml@refs/heads/main`, and `github-hosted` runners.
- GitHub workflow has no `DATABASE_URL` or `EVALUATION_EVIDENCE_HMAC_KEY`.
- Executor uses a dedicated `SELECT`-only database role and a dedicated evidence-key Secret; it never receives `edu-grader-runtime`.
- Persist only signed report JSON, digest, sanitized status/failure code, run metadata, and expiry; never source records, question bodies, Prompt text, credentials, or callback tokens.
- Retain reports for exactly 30 days, then delete database metadata and per-run callback Secrets.
- Job has `backoffLimit: 0`, an active deadline, TTL cleanup, resource limits, and a release-digest image.
- Existing two-subject generation-default approval and apply rules remain unchanged.

---

## File Structure

- `apps/api/src/edu_grader_api/github_oidc.py`: verifies GitHub OIDC JWTs and returns immutable workflow identity.
- `apps/api/src/edu_grader_api/services/operational_evaluation_runs.py`: manages idempotent run lifecycle, callback digest validation, report redaction, and expiry.
- `apps/api/src/edu_grader_api/services/operational_evaluation_kubernetes.py`: creates only labelled executor Jobs and callback Secrets through the official Kubernetes client.
- `apps/api/src/edu_grader_api/routers/operational_evaluations.py`: exposes GitHub-OIDC protected trigger, status, report, and in-cluster callback endpoints.
- `apps/api/src/edu_grader_api/services/operational_evaluation_executor.py`: executes the existing exporter and posts a sanitized completion result.
- `apps/api/src/edu_grader_api/models.py` and `apps/api/alembic/versions/0028_operational_evaluation_runs.py`: durable 30-day run metadata and signed-report retention.
- `infra/k8s/production/operational-evaluation.yaml`: executor RBAC, network policy, cleanup CronJob, and secret references.
- `infra/k8s/production/application.yaml`: API service-account, OIDC configuration, and no broad executor credential sharing.
- `.github/workflows/ai-evaluation-operational.yml`: protected GitHub-hosted OIDC trigger/poll/download workflow.
- `docs/operations/ai-evaluation-operational.md`: operator runbook and report retention/recovery instructions.

### Task 1: GitHub OIDC verifier and production configuration

**Files:**
- Create: `apps/api/src/edu_grader_api/github_oidc.py`
- Modify: `apps/api/src/edu_grader_api/settings.py`
- Modify: `apps/api/pyproject.toml`
- Test: `apps/api/tests/test_github_oidc.py`
- Test: `apps/api/tests/test_settings.py`

**Interfaces:**
- Produces `GitHubWorkflowIdentity(repository_id: str, owner_id: str, run_id: str, workflow_ref: str)`.
- Produces `GitHubOidcVerifier.verify(token: str) -> GitHubWorkflowIdentity`.
- Consumes `Settings.github_operational_evaluation_audience`, `github_operational_evaluation_repository_id`, and `github_operational_evaluation_owner_id`.

- [ ] **Step 1: Write failing verifier and production-settings tests**

```python
def test_verifier_accepts_only_the_protected_main_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = GitHubOidcVerifier(expected=GitHubOidcTrust.from_settings(settings))
    monkeypatch.setattr(verifier, "jwk_client", StaticJwkClient(signing_key))

    identity = verifier.verify(
        signed_token(
            repository_id="expected-repository-id",
            repository_owner_id="expected-owner-id",
            ref="refs/heads/main",
            event_name="workflow_dispatch",
            environment="ai-evaluation-operational",
            workflow_ref="qq550723504/edu-homework-grader/.github/workflows/ai-evaluation-operational.yml@refs/heads/main",
            runner_environment="github-hosted",
        )
    )

    assert identity.run_id == "123"


@pytest.mark.parametrize("claim,value", [("ref", "refs/heads/feature"), ("environment", "production"), ("runner_environment", "self-hosted"), ("repository_visibility", "private")])
def test_verifier_rejects_a_wrong_trust_claim(claim: str, value: str) -> None:
    claims = protected_claims()
    claims[claim] = value
    with pytest.raises(InvalidTokenError, match="GitHub workflow is not trusted"):
        verifier.verify(signed_token(**claims))
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `PYTHONPATH=apps/api/src python -m pytest apps/api/tests/test_github_oidc.py apps/api/tests/test_settings.py -q`

Expected: FAIL because `GitHubOidcVerifier` and required settings do not exist.

- [ ] **Step 3: Implement the smallest verifier surface**

```python
@dataclass(frozen=True)
class GitHubWorkflowIdentity:
    repository_id: str
    owner_id: str
    run_id: str
    workflow_ref: str


class GitHubOidcVerifier:
    def verify(self, token: str) -> GitHubWorkflowIdentity:
        claims = jwt.decode(token, self.jwk_client.get_signing_key_from_jwt(token).key,
                            algorithms=["RS256"], audience=self.expected.audience,
                            issuer="https://token.actions.githubusercontent.com")
        self.expected.require(claims)
        return GitHubWorkflowIdentity(str(claims["repository_id"]), str(claims["repository_owner_id"]), str(claims["run_id"]), str(claims["workflow_ref"]))
```

Add `kubernetes` to the API dependency list, add the three non-empty GitHub trust settings, and reject missing or development values when `APP_ENV=production`.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `PYTHONPATH=apps/api/src python -m pytest apps/api/tests/test_github_oidc.py apps/api/tests/test_settings.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/pyproject.toml apps/api/src/edu_grader_api/github_oidc.py apps/api/src/edu_grader_api/settings.py apps/api/tests/test_github_oidc.py apps/api/tests/test_settings.py
git commit -m "feat: verify protected GitHub OIDC evaluation jobs"
```

### Task 2: Persist operational-evaluation runs and retention state

**Files:**
- Modify: `apps/api/src/edu_grader_api/models.py`
- Create: `apps/api/alembic/versions/0028_operational_evaluation_runs.py`
- Create: `apps/api/src/edu_grader_api/services/operational_evaluation_runs.py`
- Test: `apps/api/tests/test_operational_evaluation_runs.py`

**Interfaces:**
- Produces `OperationalEvaluationRun` and `OperationalEvaluationRunStatus` (`queued`, `running`, `succeeded`, `failed`).
- Produces `create_run(session, *, identity, spec_json, now) -> CreatedOperationalEvaluationRun`.
- Produces `complete_run(session, *, run_id, callback_token, report_json, now) -> OperationalEvaluationRun`.
- Produces `purge_expired_runs(session, *, now) -> list[UUID]`.

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_same_github_run_and_spec_is_idempotent(session: Session) -> None:
    first = create_run(session, identity=identity("42"), spec_json=SPEC, now=NOW)
    second = create_run(session, identity=identity("42"), spec_json=SPEC, now=NOW)
    assert second.run.id == first.run.id
    assert second.callback_token is None


def test_callback_persists_only_signed_report_and_expires_after_thirty_days(session: Session) -> None:
    created = create_run(session, identity=identity("42"), spec_json=SPEC, now=NOW)
    completed = complete_run(session, run_id=created.run.id, callback_token=created.callback_token, report_json=SIGNED_REPORT, now=NOW)
    assert completed.expires_at == NOW + timedelta(days=30)
    assert completed.report_json == SIGNED_REPORT
    assert purge_expired_runs(session, now=completed.expires_at) == [completed.id]
```

- [ ] **Step 2: Run lifecycle tests to verify they fail**

Run: `PYTHONPATH=apps/api/src python -m pytest apps/api/tests/test_operational_evaluation_runs.py -q`

Expected: FAIL because the model and lifecycle service do not exist.

- [ ] **Step 3: Implement migration, model, and lifecycle service**

Create table `operational_evaluation_runs` with a unique `github_run_id`, SHA-256 spec and callback-token digests, status, signed-report JSON, report digest, sanitized failure code, created/completed/expires timestamps, and repository/workflow audit metadata. Use `secrets.token_urlsafe(32)` for the callback token, persist only `sha256(token)`, use `hmac.compare_digest`, and reject raw record keys (`records`, `candidate_json`, `prompt`) before persistence.

- [ ] **Step 4: Run lifecycle tests to verify they pass**

Run: `PYTHONPATH=apps/api/src python -m pytest apps/api/tests/test_operational_evaluation_runs.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/edu_grader_api/models.py apps/api/alembic/versions/0028_operational_evaluation_runs.py apps/api/src/edu_grader_api/services/operational_evaluation_runs.py apps/api/tests/test_operational_evaluation_runs.py
git commit -m "feat: retain signed operational evaluation runs"
```

### Task 3: Control-plane API and constrained Kubernetes launcher

**Files:**
- Create: `apps/api/src/edu_grader_api/services/operational_evaluation_kubernetes.py`
- Create: `apps/api/src/edu_grader_api/routers/operational_evaluations.py`
- Modify: `apps/api/src/edu_grader_api/main.py`
- Test: `apps/api/tests/test_operational_evaluations_api.py`

**Interfaces:**
- Consumes `GitHubOidcVerifier`, `create_run`, `complete_run`, and `OperationalEvaluationJobLauncher`.
- Produces `POST /v1/internal/operational-evaluations`, `GET /v1/internal/operational-evaluations/{id}`, `GET /v1/internal/operational-evaluations/{id}/report`, and `POST /v1/internal/operational-evaluations/{id}/completion`.
- Produces `OperationalEvaluationJobLauncher.launch(run, callback_token) -> None`.

- [ ] **Step 1: Write failing API/launcher tests**

```python
def test_valid_github_oidc_request_creates_exactly_one_job(client: TestClient, launcher: FakeLauncher) -> None:
    response = client.post("/v1/internal/operational-evaluations", json={"spec": SPEC}, headers=github_headers())
    assert response.status_code == 202
    assert launcher.launched_run_ids == [response.json()["id"]]


def test_report_endpoint_never_returns_source_records(client: TestClient) -> None:
    response = client.get(f"/v1/internal/operational-evaluations/{completed_run.id}/report", headers=github_headers())
    assert response.status_code == 200
    assert "records" not in response.text


def test_launcher_uses_pinned_image_and_never_mounts_runtime_secret() -> None:
    launcher = KubernetesOperationalEvaluationJobLauncher(
        namespace="edu-homework-grader",
        image="ghcr.io/qq550723504/edu-homework-grader-api@sha256:" + "a" * 64,
        runtime_secret_name="operational-evaluation-runtime",
        callback_base_url="http://api:8000",
        batch_api=FakeBatchApi(),
        core_api=FakeCoreApi(),
    )
    manifest = launcher.manifest_for(run, "callback")
    assert "@sha256:" in manifest["spec"]["template"]["spec"]["containers"][0]["image"]
    assert "edu-grader-runtime" not in json.dumps(manifest)
```

- [ ] **Step 2: Run API tests to verify they fail**

Run: `PYTHONPATH=apps/api/src python -m pytest apps/api/tests/test_operational_evaluations_api.py -q`

Expected: FAIL because the router and launcher do not exist.

- [ ] **Step 3: Implement API dependencies and launcher**

Use an independent `HTTPBearer` dependency for GitHub OIDC. Require the same verified identity for start/status/report endpoints, validate a JSON operational spec before launch, and map invalid token to `401`, wrong identity to `403`, unknown runs to `404`, and non-terminal reports to `409`. The completion endpoint accepts only the callback token from the executor, deletes its callback Secret after a terminal callback, and writes a sanitized failure code rather than an exception body.

Implement the launcher with `kubernetes.client.BatchV1Api` and `CoreV1Api`. Create a per-run callback Secret and a `batch/v1` Job labelled `app.kubernetes.io/component=operational-evaluation` and `edu.getkr.com/run-id=<uuid>`. The Job receives the exact validated spec, a dedicated read-only `DATABASE_URL`, the evidence key Secret, and the callback token Secret; it never references `edu-grader-runtime`.

- [ ] **Step 4: Run API tests to verify they pass**

Run: `PYTHONPATH=apps/api/src python -m pytest apps/api/tests/test_operational_evaluations_api.py apps/api/tests/test_operational_evaluation_runs.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/edu_grader_api/services/operational_evaluation_kubernetes.py apps/api/src/edu_grader_api/routers/operational_evaluations.py apps/api/src/edu_grader_api/main.py apps/api/tests/test_operational_evaluations_api.py
git commit -m "feat: dispatch OIDC operational evaluation jobs"
```

### Task 4: Executor callback and signed-report redaction

**Files:**
- Create: `apps/api/src/edu_grader_api/services/operational_evaluation_executor.py`
- Test: `apps/api/tests/test_operational_evaluation_executor.py`

**Interfaces:**
- Consumes the existing `run_operational_evaluation` and `write_operational_artifacts` functions.
- Produces `run_executor(*, spec_json, callback_url, callback_token, output_dir) -> int`.
- Posts only `{status, report, report_sha256}` or `{status, failure_code}` to the completion endpoint.

- [ ] **Step 1: Write failing executor tests**

```python
def test_executor_posts_signed_report_without_exported_records(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    posted: list[dict[str, object]] = []
    monkeypatch.setattr(executor, "post_completion", lambda **kwargs: posted.append(kwargs["payload"]))
    assert executor.run_executor(spec_json=SPEC_JSON, callback_url="http://api:8000/callback", callback_token="token", output_dir=tmp_path) == 0
    assert posted[0]["status"] == "succeeded"
    assert "records" not in posted[0]["report"]


def test_executor_maps_exception_to_sanitized_failure_code(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(executor, "run_operational_evaluation", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("source record")))
    posted: list[dict[str, object]] = []
    monkeypatch.setattr(executor, "post_completion", lambda **kwargs: posted.append(kwargs["payload"]))
    assert executor.run_executor(spec_json=SPEC_JSON, callback_url="http://api:8000/callback", callback_token="token", output_dir=tmp_path) == 1
    assert posted == [{"status": "failed", "failure_code": "evaluation_execution_failed"}]
```

- [ ] **Step 2: Run executor tests to verify they fail**

Run: `PYTHONPATH=apps/api/src python -m pytest apps/api/tests/test_operational_evaluation_executor.py -q`

Expected: FAIL because the executor module does not exist.

- [ ] **Step 3: Implement the minimal executor**

Parse the validated JSON spec, open a SQLAlchemy session through the executor's read-only `DATABASE_URL`, call the existing operational evaluator with `EVALUATION_EVIDENCE_HMAC_KEY`, read only `report.json` and its SHA-256 from the generated artifacts, remove any raw-record key if encountered, and post completion with a timeout. Map expected export, policy, database, and callback failures to stable codes; do not post stack traces.

- [ ] **Step 4: Run executor tests to verify they pass**

Run: `PYTHONPATH=apps/api/src python -m pytest apps/api/tests/test_operational_evaluation_executor.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/edu_grader_api/services/operational_evaluation_executor.py apps/api/tests/test_operational_evaluation_executor.py
git commit -m "feat: return signed operational evaluation evidence"
```

### Task 5: Production RBAC, job policy, database reader, and cleanup

**Files:**
- Create: `infra/k8s/production/operational-evaluation.yaml`
- Create: `infra/k8s/production/operational-evaluation.tests.ps1`
- Modify: `infra/k8s/production/kustomization.yaml`
- Modify: `infra/k8s/production/application.yaml`
- Modify: `scripts/k8s/deploy-production.ps1`
- Test: `scripts/k8s/deploy-production.tests.ps1`

**Interfaces:**
- Produces API `ServiceAccount` and a Role limited to labelled Jobs and callback Secrets.
- Produces executor `ServiceAccount` with no RoleBinding.
- Produces `operational-evaluation-retention` CronJob with a 30-day cleanup command.
- Consumes `operational-evaluation-runtime` Secret (`DATABASE_URL`, `EVALUATION_EVIDENCE_HMAC_KEY`) created outside Git.

- [ ] **Step 1: Write failing manifest and deploy-script tests**

```powershell
It 'keeps executor credentials separate from the application runtime secret' {
    $manifest | Should -Match 'name: operational-evaluation-runtime'
    $manifest | Should -Not -Match 'name: edu-grader-runtime'
}

It 'bounds the executor and grants it no Kubernetes API permissions' {
    $manifest | Should -Match 'activeDeadlineSeconds: 900'
    $manifest | Should -Match 'backoffLimit: 0'
    $manifest | Should -Not -Match 'kind: RoleBinding\s+[\s\S]*operational-evaluation-executor'
}
```

- [ ] **Step 2: Run manifest tests to verify they fail**

Run: `Invoke-Pester infra/k8s/production/operational-evaluation.tests.ps1 -Output Normal`

Expected: FAIL because the production manifest does not exist.

- [ ] **Step 3: Implement constrained manifests and deployment ownership**

Add a dedicated API service account/Role/RoleBinding for `create`, `get`, `list`, `watch`, and `delete` only on Jobs and Secrets with the operational-evaluation component label. Add the executor service account with no RoleBinding, default-deny network policy plus egress only to `postgres`, `api`, and kube DNS, resource requests/limits, `activeDeadlineSeconds: 900`, `backoffLimit: 0`, and `ttlSecondsAfterFinished: 3600`. Add a daily cleanup CronJob using the API release image and a service account permitted to delete expired callback Secrets. Extend `deploy-production.ps1` managed-resource checks to render and apply this manifest without accepting mutable images.

Create the read-only PostgreSQL role at deployment time with `NOINHERIT`, no schema creation rights, and `SELECT` only on: `generation_jobs`, `generation_attempts`, `generated_question_drafts`, `generated_question_draft_revisions`, `generated_question_review_decisions`, `generation_validation_runs`, `generation_governance_entries`, `curriculum_objective_revisions`, `curriculum_objectives`, `curriculum_grade_mappings`, `curriculum_profiles`, and `question_versions`. Store its URL and the evidence key only in `operational-evaluation-runtime`.

- [ ] **Step 4: Run manifest/deploy tests to verify they pass**

Run: `Invoke-Pester infra/k8s/production/operational-evaluation.tests.ps1,scripts/k8s/deploy-production.tests.ps1 -Output Normal`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add infra/k8s/production/operational-evaluation.yaml infra/k8s/production/operational-evaluation.tests.ps1 infra/k8s/production/kustomization.yaml infra/k8s/production/application.yaml scripts/k8s/deploy-production.ps1 scripts/k8s/deploy-production.tests.ps1
git commit -m "feat: constrain production operational evaluation jobs"
```

### Task 6: GitHub workflow, operations runbook, and structural gates

**Files:**
- Modify: `.github/workflows/ai-evaluation-operational.yml`
- Modify: `docs/operations/ai-evaluation-operational.md`
- Create: `apps/api/tests/test_operational_evaluation_workflow.py`

**Interfaces:**
- Consumes `ACTIONS_ID_TOKEN_REQUEST_URL` and `ACTIONS_ID_TOKEN_REQUEST_TOKEN` to obtain an audience-bound JWT.
- Produces a 30-day `operational-ai-evaluation-${{ github.run_id }}` artifact containing only signed report files.

- [ ] **Step 1: Write failing workflow structure tests**

```python
def test_operational_workflow_uses_github_oidc_not_production_secrets() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "id-token: write" in workflow
    assert "ACTIONS_ID_TOKEN_REQUEST_URL" in workflow
    assert "DATABASE_URL" not in workflow
    assert "EVALUATION_EVIDENCE_HMAC_KEY" not in workflow
    assert "runs-on: ubuntu-latest" in workflow
```

- [ ] **Step 2: Run workflow test to verify it fails**

Run: `PYTHONPATH=apps/api/src python -m pytest apps/api/tests/test_operational_evaluation_workflow.py -q`

Expected: FAIL because the existing workflow still uses database and evidence secrets.

- [ ] **Step 3: Implement protected OIDC dispatch/poll/download flow**

Set `permissions.id-token: write`, request an OIDC token with the configured custom audience, submit the spec to the API with `Authorization: Bearer`, poll a bounded status URL, download only the report endpoint after `succeeded`, and upload it with `retention-days: 30`. Keep `workflow_dispatch`, the `main` guard, protected environment, immutable checkout, and a 20-minute timeout. Update the runbook with exact setup inputs, report retrieval, retention, failure codes, and the statement that empty production data is technically runnable but promotion-ineligible.

- [ ] **Step 4: Run workflow test to verify it passes**

Run: `PYTHONPATH=apps/api/src python -m pytest apps/api/tests/test_operational_evaluation_workflow.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ai-evaluation-operational.yml docs/operations/ai-evaluation-operational.md apps/api/tests/test_operational_evaluation_workflow.py
git commit -m "feat: trigger operational evaluations with GitHub OIDC"
```

### Task 7: Full verification and production bootstrap

**Files:**
- Modify: `docs/operations/ai-generation-default-governance.md`
- Test: `apps/api/tests/test_github_oidc.py`
- Test: `apps/api/tests/test_operational_evaluation_runs.py`
- Test: `apps/api/tests/test_operational_evaluations_api.py`
- Test: `apps/api/tests/test_operational_evaluation_executor.py`
- Test: `apps/api/tests/test_operational_evaluation_workflow.py`

- [ ] **Step 1: Run the complete focused verification suite**

Run: `PYTHONPATH=apps/api/src python -m pytest apps/api/tests/test_github_oidc.py apps/api/tests/test_operational_evaluation_runs.py apps/api/tests/test_operational_evaluations_api.py apps/api/tests/test_operational_evaluation_executor.py apps/api/tests/test_operational_evaluation_workflow.py apps/api/tests/test_generation_default_governance_deployment.py -q`

Expected: PASS.

- [ ] **Step 2: Run formatting, lint, manifest, and workflow checks**

Run: `python -m ruff format --check apps/api && python -m ruff check --config ruff.toml apps/api && Invoke-Pester infra/k8s/production/operational-evaluation.tests.ps1,scripts/k8s/deploy-production.tests.ps1 -Output Normal`

Expected: PASS.

- [ ] **Step 3: Bootstrap the live cluster without echoing secrets**

Create `operational-evaluation-runtime`, generate the reader password, grant only the listed tables, configure the immutable GitHub repository and owner IDs plus OIDC audience, apply the release-generated manifest, and prove the executor's database role cannot write. Do not start a promotion run against empty data and do not create a generation default.

- [ ] **Step 4: Update governance runbook and commit**

Add the OIDC-triggered evidence retrieval path to the generation-default governance document, preserving its signed-report and two-subject requirements.

```bash
git add docs/operations/ai-generation-default-governance.md
git commit -m "docs: operate OIDC evaluation evidence"
```
