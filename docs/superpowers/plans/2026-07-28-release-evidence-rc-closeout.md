# Release Evidence RC Close-out Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate protected production deployment on the existing real-service release-evidence suite for the same immutable source SHA and image digests.

**Architecture:** The production publisher records each matrix build digest, combines them into a validated manifest, and calls the reusable evidence workflow. The reusable workflow checks out the supplied SHA, stores only the SHA/digest manifest with its existing de-identified reports, and fails the caller on evidence failure.

**Tech Stack:** GitHub Actions, Python/pytest workflow contract tests, existing Docker Compose evidence suite.

## Global Constraints

- Keep pull-request evidence observational.
- Never expose credentials, registry URLs, request payloads, or diagnostics in the evidence manifest.
- Preserve the existing 40-character source-SHA deployment and superseded-release guards.
- Do not alter the real-service evidence scenarios.

---

### Task 1: Specify the workflow contracts with failing tests

**Files:**
- Modify: `apps/api/tests/test_publish_images_workflow.py`
- Modify: `apps/api/tests/test_ci_workflow.py`

**Interfaces:**
- Produces source-level checks for the callable evidence inputs, digest hand-off, and deployment dependency.

- [ ] **Step 1: Write failing workflow-contract assertions**

```python
assert "workflow_call:" in evidence
assert "source_sha:" in evidence
assert "image_digests:" in evidence
assert "needs: [eligibility, publish, release-evidence]" in deploy
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `python -m pytest apps/api/tests/test_publish_images_workflow.py apps/api/tests/test_ci_workflow.py -q`

Expected: failure because the current workflows do not expose `workflow_call` or a release-evidence deployment dependency.

### Task 2: Add reusable evidence input and sanitized release manifest

**Files:**
- Modify: `.github/workflows/verification-release-evidence.yml`

**Interfaces:**
- Consumes: `source_sha: string` and `image_digests: string` from `workflow_call`.
- Produces: the existing evidence artifact plus `release-manifest.json` for RC executions.

- [ ] **Step 1: Add `workflow_call` and dispatch inputs**
- [ ] **Step 2: Resolve the source SHA with PR fallback and check it out explicitly**
- [ ] **Step 3: Validate and write a SHA/digest-only manifest before scenario execution**
- [ ] **Step 4: Run focused tests and confirm they pass**

### Task 3: Gate protected deployment on evidence

**Files:**
- Modify: `.github/workflows/publish-images.yml`

**Interfaces:**
- Consumes: each `docker/build-push-action` digest and `github.event.workflow_run.head_sha`.
- Produces: a four-image JSON map passed to `./.github/workflows/verification-release-evidence.yml`.

- [ ] **Step 1: Persist one short-lived digest artifact per image build**
- [ ] **Step 2: Add a manifest job that validates all four SHA-256 digests**
- [ ] **Step 3: Call reusable evidence with the exact CI source SHA**
- [ ] **Step 4: Pass the same digest map to the deploy script and render exact OCI digest references**
- [ ] **Step 5: Require `release-evidence` before the protected deploy job**
- [ ] **Step 6: Run focused tests and confirm they pass**

### Task 4: Align operational documentation and verify

**Files:**
- Modify: `docs/verification-release-evidence.md`
- Modify: `docs/production-cd.md`

- [ ] **Step 1: State the actual candidate image digest and pre-approval evidence gate**
- [ ] **Step 2: Remove the closed OIDC-browser limitation and retain the separate performance-policy limitation**
- [ ] **Step 3: Run `python -m pytest apps/api/tests/test_publish_images_workflow.py apps/api/tests/test_ci_workflow.py -q`**
- [ ] **Step 4: Run `python scripts/check_docs_status.py`**
- [ ] **Step 5: Commit the close-out PR slice**
