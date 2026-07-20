# Kubernetes Production Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the application to the current Kubernetes cluster at `edu.getkr.com` with fail-fast secret injection and a reproducible recovery drill.

**Architecture:** Native Kubernetes Secrets match the cluster's existing deployment pattern. Immutable GHCR images feed namespace-scoped Deployments and StatefulSets behind Traefik/cert-manager; rotation and recovery use scripts that never write secret values to disk.

**Tech Stack:** Kubernetes, Traefik Ingress, cert-manager, PostgreSQL 16, Keycloak, GitHub Actions, GHCR, PowerShell, Docker Compose image definitions.

## Global Constraints

- Namespace: `edu-homework-grader`.
- Hostname: `edu.getkr.com`; issuer: `letsencrypt-prod`; ingress class: `traefik`.
- Secret values are created only with CSPRNG at deployment time and never committed or printed.
- Images use immutable SHA tags or digests under `ghcr.io/qq550723504`; never `latest`.
- API must start only with HTTPS OIDC and non-default secrets; `/ready` is the deployment gate.

---

### Task 1: Add production manifest structure and validation

**Files:**
- Create: `infra/k8s/production/namespace.yaml`
- Create: `infra/k8s/production/kustomization.yaml`
- Create: `infra/k8s/production/services.yaml`
- Test: `infra/k8s/production/kustomization.yaml` through `kubectl kustomize`

**Interfaces:**
- Consumes: current cluster `local-path` StorageClass and `traefik` ingress class.
- Produces: a kustomize root that all deployment and recovery commands target.

- [ ] **Step 1: Write a failing manifest validation command**

Run: `kubectl kustomize infra/k8s/production`

Expected: FAIL because the production kustomization does not yet exist.

- [ ] **Step 2: Create namespace and kustomization**

Create `namespace.yaml` with `metadata.name: edu-homework-grader` and `kustomization.yaml` that declares `namespace: edu-homework-grader`, common labels `app.kubernetes.io/part-of: edu-homework-grader`, and the concrete resource list.

- [ ] **Step 3: Create ClusterIP Services**

Define named ports for `api` (8000), `grader` (8010), `web` (3000), `keycloak` (8080), `languagetool` (8011), and `redis` (6379). Do not expose database, Redis, or Grader externally.

- [ ] **Step 4: Verify rendering**

Run: `kubectl kustomize infra/k8s/production`

Expected: YAML containing only namespace-scoped resources and no Secret `data` values.

- [ ] **Step 5: Commit**

Run: `git add infra/k8s/production && git commit -m "feat: add Kubernetes production manifest base"`

### Task 2: Add non-persistent secret creation and rotation commands

**Files:**
- Create: `scripts/k8s/create-prod-secrets.ps1`
- Create: `scripts/k8s/rotate-prod-secrets.ps1`
- Create: `scripts/k8s/create-prod-secrets.tests.ps1`

**Interfaces:**
- Consumes: `kubectl`, namespace `edu-homework-grader`, and caller-provided `-OidcIssuer`.
- Produces: Secret `edu-grader-runtime` with `AUDIT_HMAC_KEY`, database, Keycloak, and OIDC settings; no plaintext output.

- [ ] **Step 1: Write a failing Pester test**

```powershell
It 'rejects a non-HTTPS production issuer' {
  { ./scripts/k8s/create-prod-secrets.ps1 -OidcIssuer 'http://issuer.example' -WhatIf } |
    Should -Throw '*HTTPS*'
}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `Invoke-Pester scripts/k8s/create-prod-secrets.tests.ps1`

Expected: FAIL because the command does not exist.

- [ ] **Step 3: Implement the secret command**

Use `[System.Security.Cryptography.RandomNumberGenerator]::GetBytes()` with Base64 conversion for every generated value, including `REDIS_PASSWORD`. Validate an `https://` issuer and invoke `kubectl create secret generic edu-grader-runtime --dry-run=client -o yaml | kubectl apply -f -`; never use `Write-Output` for secret values.

- [ ] **Step 4: Implement rotation**

Create a replacement Secret with an immutable timestamp suffix, patch Deployment `envFrom.secretRef.name`, run `kubectl rollout status`, then delete the superseded Secret only after API `/ready` returns HTTP 200 via `kubectl exec`.

- [ ] **Step 5: Verify red/green and static safety**

Run: `Invoke-Pester scripts/k8s/create-prod-secrets.tests.ps1`

Expected: PASS and `rg -n 'Write-Output.*(KEY|PASSWORD|TOKEN)' scripts/k8s` returns no matches.

- [ ] **Step 6: Commit**

Run: `git add scripts/k8s && git commit -m "feat: add Kubernetes secret rotation commands"`

### Task 3: Deploy production workloads and HTTPS ingress

**Files:**
- Create: `infra/k8s/production/postgres.yaml`
- Create: `infra/k8s/production/keycloak.yaml`
- Create: `infra/keycloak/edu-grader-production-realm.json`
- Create: `infra/k8s/production/application.yaml`
- Create: `infra/k8s/production/ingress.yaml`
- Modify: `infra/k8s/production/kustomization.yaml`

**Interfaces:**
- Consumes: `edu-grader-runtime` Secret and immutable GHCR image references.
- Produces: Ready API, Grader, Web, Keycloak, and PostgreSQL services, plus TLS endpoint `https://edu.getkr.com`.

- [ ] **Step 1: Write failing server-side validation**

Run: `kubectl apply --server-side --dry-run=server -k infra/k8s/production`

Expected: FAIL before workloads exist.

- [ ] **Step 2: Implement database and Keycloak manifests**

Use PostgreSQL 16 and Redis StatefulSets with `local-path` PVCs; configure Redis with `--requirepass` from `secretKeyRef`. Use a Keycloak Deployment initialized from a production-only Realm import that contains no `pilot-*` users and allows only `https://edu.getkr.com/*` callbacks. Reference all passwords only through `secretKeyRef`.

- [ ] **Step 3: Implement application Deployments**

Set API readiness to `GET /ready`, Grader readiness to `GET /ready`, resource requests/limits, and `imagePullPolicy: IfNotPresent`. API receives `APP_ENV=production`, `OIDC_ISSUER=https://edu.getkr.com/realms/edu-grader`, and only allowlisted internal processor origins.

- [ ] **Step 4: Implement Traefik/cert-manager ingress**

Use `ingressClassName: traefik`, annotations `cert-manager.io/cluster-issuer: letsencrypt-prod` and `traefik.ingress.kubernetes.io/router.entrypoints: web,websecure`, host `edu.getkr.com`, and TLS Secret `edu-getkr-com-tls`.

- [ ] **Step 5: Verify manifests**

Run: `kubectl apply --server-side --dry-run=server -k infra/k8s/production`

Expected: all resources accepted without mutation errors.

- [ ] **Step 6: Commit**

Run: `git add infra/k8s/production && git commit -m "feat: deploy edu grader on Kubernetes"`

### Task 4: Publish immutable application images

**Files:**
- Create: `.github/workflows/publish-images.yml`
- Test: `.github/workflows/publish-images.yml` through workflow YAML validation and Docker build commands

**Interfaces:**
- Consumes: protected `main`, GitHub `GITHUB_TOKEN` with `packages: write`, and Dockerfiles for API, Grader, Web, LanguageTool.
- Produces: `ghcr.io/qq550723504/edu-homework-grader-{api,grader,web,languagetool}:<commit-sha>`.

- [ ] **Step 1: Write a failing workflow content test**

Assert that the workflow grants `packages: write` and all four images are addressed by immutable `${{ github.sha }}` tags.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest apps/api/tests/test_ci_workflow.py -q`

Expected: FAIL because the publish workflow is absent.

- [ ] **Step 3: Implement GHCR publish workflow**

Trigger only after protected `main` CI success, login with `docker/login-action@v3` using `GITHUB_TOKEN`, build with `docker/build-push-action@v6`, and publish the four immutable SHA tags.

- [ ] **Step 4: Verify workflow contract**

Run: `python -m pytest apps/api/tests/test_ci_workflow.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add .github/workflows/publish-images.yml apps/api/tests/test_ci_workflow.py && git commit -m "ci: publish immutable production images"`

### Task 5: Add recovery drill and deployment acceptance

**Files:**
- Create: `scripts/k8s/recovery-drill.ps1`
- Create: `scripts/k8s/recovery-drill.tests.ps1`
- Modify: `docs/security.md`
- Modify: `docs/project-status.md`

**Interfaces:**
- Consumes: ready namespace, PostgreSQL credentials through `kubectl exec`, and a PVC-backed PostgreSQL pod.
- Produces: timestamped backup Job, restoration into a fresh pod/database, readiness result, and redacted audit output.

- [ ] **Step 1: Write a failing recovery safety test**

```powershell
It 'requires an explicit recovery confirmation' {
  { ./scripts/k8s/recovery-drill.ps1 -Namespace edu-homework-grader } |
    Should -Throw '*-ConfirmRecovery*'
}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `Invoke-Pester scripts/k8s/recovery-drill.tests.ps1`

Expected: FAIL because the drill command is absent.

- [ ] **Step 3: Implement backup and recovery**

Require `-ConfirmRecovery`, run `pg_dump` through the PostgreSQL pod, restore into a new named database, wait for API and Grader rollout completion, and verify `/ready` using an in-cluster request. Redact all connection strings and secret values.

- [ ] **Step 4: Verify safety and documentation**

Run: `Invoke-Pester scripts/k8s/recovery-drill.tests.ps1`

Expected: PASS; `docs/security.md` documents rotation and restoration commands without literal credentials.

- [ ] **Step 5: Commit**

Run: `git add scripts/k8s docs/security.md docs/project-status.md && git commit -m "docs: add Kubernetes recovery drill"`

### Task 6: Run deployment and acceptance drill

**Files:**
- Modify: `infra/k8s/production/kustomization.yaml` only to replace image placeholders with GHCR SHA tags after publication.

**Interfaces:**
- Consumes: GHCR images created by Task 4 and DNS `edu.getkr.com` pointing at `156.239.44.3`.
- Produces: deployed application, issued TLS certificate, secret-rotation record, recovery-drill record, and closure evidence for issue #19.

- [ ] **Step 1: Verify DNS and image availability**

Run: `Resolve-DnsName edu.getkr.com` and `docker manifest inspect ghcr.io/qq550723504/edu-homework-grader-api:<sha>`.

Expected: DNS resolves to the Traefik load balancer and all image manifests exist.

- [ ] **Step 2: Create production Secrets**

Run: `./scripts/k8s/create-prod-secrets.ps1 -Namespace edu-homework-grader -OidcIssuer https://edu.getkr.com/realms/edu-grader`.

Expected: only resource names are printed.

- [ ] **Step 3: Apply and wait**

Run: `kubectl apply --server-side -k infra/k8s/production` then `kubectl rollout status` for all Deployments and StatefulSets.

Expected: all workloads Ready and `kubectl get certificate -n edu-homework-grader edu-getkr-com-tls` reports Ready.

- [ ] **Step 4: Perform rotation and recovery drill**

Run rotation once, then `./scripts/k8s/recovery-drill.ps1 -Namespace edu-homework-grader -ConfirmRecovery`.

Expected: API and Grader become ready after rotation; restore completes with no secret output.

- [ ] **Step 5: Close issue after evidence**

Add the redacted command results to #19, then close it as completed only after all readiness and recovery conditions pass.
