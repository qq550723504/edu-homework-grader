# Infrastructure Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a newly bootstrapped API eligible for Kubernetes traffic when PostgreSQL is usable, without treating an ungoverned AI generation default as ready.

**Architecture:** `GET /infrastructure-ready` owns the infrastructure-only database probe and does not inspect generation governance. `GET /ready` remains the business-readiness endpoint. The production Deployment directs its readiness probe to the new endpoint.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, Kubernetes YAML.

## Global Constraints

- Do not add an AI fallback default or relax signed-evidence/two-person governance.
- Return only database availability in `/infrastructure-ready`; never expose credentials or exceptions.
- Keep `/ready` response semantics unchanged.
- Use the database-aware infrastructure probe, not `/health`, in Kubernetes.

---

### Task 1: Add and lock the infrastructure-only API probe

**Files:**
- Modify: `apps/api/tests/test_health.py`
- Modify: `apps/api/src/edu_grader_api/main.py`

**Interfaces:**
- Produces: `GET /infrastructure-ready -> {"status": "ready", "database": "ready"}` with HTTP 200 when `engine.connect()` succeeds.
- Produces: `GET /infrastructure-ready -> {"status": "degraded", "database": "unavailable"}` with HTTP 503 when the database connection fails.
- Preserves: `GET /ready` validates the governed generation default after its database check.

- [ ] **Step 1: Write failing endpoint tests**

Add these tests to `apps/api/tests/test_health.py` before changing `main.py`:

```python
def test_infrastructure_ready_reports_database_availability(monkeypatch) -> None:
    monkeypatch.setattr("edu_grader_api.main.engine", create_engine("sqlite+pysqlite:///:memory:"))

    response = TestClient(app).get("/infrastructure-ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ready"}


def test_infrastructure_ready_fails_closed_when_database_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("edu_grader_api.main.engine", create_engine("postgresql+psycopg://invalid"))

    response = TestClient(app).get("/infrastructure-ready")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unavailable"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/api/tests/test_health.py -q`

Expected: the two new tests fail with HTTP 404; existing `/ready` tests pass.

- [ ] **Step 3: Add minimal endpoint**

Add this route immediately after `health()` in `apps/api/src/edu_grader_api/main.py`:

```python
@app.get("/infrastructure-ready", tags=["system"], response_model=None)
def infrastructure_ready() -> dict[str, str] | JSONResponse:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        logger.warning("infrastructure readiness check failed", extra={"component": "database"})
        return JSONResponse(
            status_code=503, content={"status": "degraded", "database": "unavailable"}
        )
    return {"status": "ready", "database": "ready"}
```

- [ ] **Step 4: Verify API behavior and the existing governance gate**

Run: `pytest apps/api/tests/test_health.py -q`

Expected: all tests pass, including the existing assertion that `/ready` returns 503 with `generation_default=unconfigured`.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/edu_grader_api/main.py apps/api/tests/test_health.py
git commit -m "feat: add infrastructure readiness probe"
```

### Task 2: Direct the production Deployment to the infrastructure probe

**Files:**
- Modify: `apps/api/tests/test_generation_governance_deployment.py`
- Modify: `infra/k8s/production/application.yaml`

**Interfaces:**
- Consumes: `GET /infrastructure-ready` from Task 1.
- Produces: API Deployment `readinessProbe.httpGet.path: /infrastructure-ready`.

- [ ] **Step 1: Write failing manifest assertion**

Add this test to `apps/api/tests/test_generation_governance_deployment.py`:

```python
def test_production_api_readiness_probe_checks_infrastructure_only() -> None:
    repository_root = Path(__file__).parents[3]
    production = yaml.safe_load_all(
        (repository_root / "infra/k8s/production/application.yaml").read_text(encoding="utf-8")
    )
    api = next(document for document in production if document["metadata"]["name"] == "api")
    probe = api["spec"]["template"]["spec"]["containers"][0]["readinessProbe"]

    assert probe["httpGet"] == {"path": "/infrastructure-ready", "port": "http"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/api/tests/test_generation_governance_deployment.py -q`

Expected: the new test fails because the manifest still probes `/ready`.

- [ ] **Step 3: Change only the production probe path**

In `infra/k8s/production/application.yaml`, set:

```yaml
readinessProbe:
  httpGet:
    path: /infrastructure-ready
    port: http
```

Do not change the API image, secrets, database configuration, or `/ready` endpoint.

- [ ] **Step 4: Verify focused suites**

Run:

```powershell
pytest apps/api/tests/test_health.py apps/api/tests/test_generation_governance_deployment.py -q
Invoke-Pester scripts/k8s/create-prod-secrets.tests.ps1 -Output Detailed
```

Expected: all Python tests and all three PowerShell secret-bootstrap tests pass.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/tests/test_generation_governance_deployment.py infra/k8s/production/application.yaml
git commit -m "fix: probe API infrastructure readiness"
```

### Task 3: Apply and verify the live bootstrap correction

**Files:**
- No repository file changes.

**Interfaces:**
- Consumes: Task 1 route and Task 2 rendered Deployment probe.
- Produces: an Available `Deployment/api`; `/ready` remains business-degraded until governed AI defaults are established.

- [ ] **Step 1: Render the approved production Deployment with the currently published API digest**

Use `kubectl kustomize infra/k8s/production`, replace only the API placeholder image with the published release digest, and select only `Deployment/api`. Do not apply the source-control placeholder image.

- [ ] **Step 2: Server-side dry run and apply**

Run a server-side dry run with the production bootstrap field manager. Apply only `Deployment/api` after the dry run succeeds.

- [ ] **Step 3: Verify infrastructure and business readiness separately**

Run:

```powershell
kubectl -n edu-homework-grader rollout status deployment/api --timeout=180s
kubectl -n edu-homework-grader get deployment api
curl.exe --silent --show-error --resolve edu.getkr.com:443:64.90.22.137 https://edu.getkr.com/api/health
```

Expected: the Deployment is Available and the infrastructure route reports ready. Verify `/ready` separately; it may remain 503 with `generation_default=unconfigured` until a real signed operational evaluation completes the dual-approval workflow.

