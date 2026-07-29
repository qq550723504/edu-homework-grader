# Release Evidence Published Images Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make release-candidate evidence run the already-published, digest-pinned Grader and LanguageTool images instead of rebuilding them from external upstream sources.

**Architecture:** The reusable evidence workflow validates four release digests, pulls the immutable Grader and LanguageTool references from GHCR, and exposes them to Compose. The evidence runner omits `--build` only in candidate-image mode; local and pull-request runs retain source builds.

**Tech Stack:** GitHub Actions reusable workflows, GHCR, Docker Compose, Python 3.13, pytest.

## Global Constraints

- Candidate evidence uses `ghcr.io/qq550723504` references pinned with SHA-256 digests.
- Candidate evidence must not trigger a source build after digest validation.
- Pull-request and local evidence retain source-build behavior.
- Production deployment remains blocked until release evidence succeeds.

---

### Task 1: Select the correct Compose startup mode

**Files:**

- Modify: `apps/api/src/edu_grader_api/services/verification_release_timeout_evidence.py`
- Test: `apps/api/tests/test_verification_release_evidence.py`

**Interfaces:**

- Produces: `_compose_start_args(use_published_images: bool) -> tuple[str, ...]`.
- Consumes: `base._compose(context, *args)`.

- [ ] **Step 1: Write the failing test**

```python
def test_candidate_image_mode_does_not_request_a_compose_build() -> None:
    assert evidence._compose_start_args(use_published_images=True) == (
        "up", "--detach", "--wait", "--wait-timeout", "240",
        "postgres", "languagetool", "language-fault-proxy", "grader",
        "language-connect-grader",
    )
```

- [ ] **Step 2: Run the red test**

Run: `python -m pytest apps/api/tests/test_verification_release_evidence.py::test_candidate_image_mode_does_not_request_a_compose_build -q`

Expected: FAIL because `_compose_start_args` does not exist.

- [ ] **Step 3: Implement the minimal helper**

```python
def _compose_start_args(*, use_published_images: bool) -> tuple[str, ...]:
    arguments = ("up", "--detach")
    if not use_published_images:
        arguments += ("--build",)
    return arguments + (
        "--wait", "--wait-timeout", "240", "postgres", "languagetool",
        "language-fault-proxy", "grader", "language-connect-grader",
    )
```

Call the helper at the existing Compose `up` boundary. Candidate mode requires both `RELEASE_EVIDENCE_GRADER_IMAGE` and `RELEASE_EVIDENCE_LANGUAGETOOL_IMAGE`.

- [ ] **Step 4: Run the green test**

Run: `python -m pytest apps/api/tests/test_verification_release_evidence.py::test_candidate_image_mode_does_not_request_a_compose_build -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add apps/api/src/edu_grader_api/services/verification_release_timeout_evidence.py apps/api/tests/test_verification_release_evidence.py && git commit -m "fix: skip source builds for candidate evidence"`

### Task 2: Allow Compose to consume pulled images

**Files:**

- Modify: `infra/release-evidence/compose.yaml`
- Test: `apps/api/tests/test_verification_release_evidence.py`

**Interfaces:**

- Consumes: `RELEASE_EVIDENCE_GRADER_IMAGE`, `RELEASE_EVIDENCE_LANGUAGETOOL_IMAGE`.
- Produces: candidate services using pre-pulled references while retaining local defaults.

- [ ] **Step 1: Write the failing test**

```python
def test_release_evidence_compose_accepts_candidate_image_overrides() -> None:
    compose = Path("infra/release-evidence/compose.yaml").read_text(encoding="utf-8")
    assert "${RELEASE_EVIDENCE_LANGUAGETOOL_IMAGE:-" in compose
    assert compose.count("${RELEASE_EVIDENCE_GRADER_IMAGE:-") == 2
```

- [ ] **Step 2: Run the red test**

Run: `python -m pytest apps/api/tests/test_verification_release_evidence.py::test_release_evidence_compose_accepts_candidate_image_overrides -q`

Expected: FAIL because the services have fixed local image names.

- [ ] **Step 3: Apply Compose substitutions**

Use `image: ${RELEASE_EVIDENCE_LANGUAGETOOL_IMAGE:-edu-homework-grader/languagetool:release-evidence}` for LanguageTool and `image: ${RELEASE_EVIDENCE_GRADER_IMAGE:-edu-homework-grader/grader:release-evidence}` for both Grader services. Keep source build blocks for local and pull-request mode.

- [ ] **Step 4: Run the green test**

Run: `python -m pytest apps/api/tests/test_verification_release_evidence.py::test_release_evidence_compose_accepts_candidate_image_overrides -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add infra/release-evidence/compose.yaml apps/api/tests/test_verification_release_evidence.py && git commit -m "fix: allow release evidence image overrides"`

### Task 3: Pull immutable images in GitHub Actions

**Files:**

- Modify: `.github/workflows/verification-release-evidence.yml`
- Test: `apps/api/tests/test_verification_release_evidence.py`

**Interfaces:**

- Consumes: required `image_digests` JSON from `workflow_call`.
- Produces: `RELEASE_EVIDENCE_GRADER_IMAGE` and `RELEASE_EVIDENCE_LANGUAGETOOL_IMAGE` in `GITHUB_ENV`.

- [ ] **Step 1: Write the failing test**

```python
def test_reusable_evidence_workflow_pulls_published_candidate_images() -> None:
    workflow = Path(".github/workflows/verification-release-evidence.yml").read_text(encoding="utf-8")
    assert "packages: read" in workflow
    assert "docker/login-action@" in workflow
    assert "docker pull \"$RELEASE_EVIDENCE_GRADER_IMAGE\"" in workflow
    assert "docker pull \"$RELEASE_EVIDENCE_LANGUAGETOOL_IMAGE\"" in workflow
```

- [ ] **Step 2: Run the red test**

Run: `python -m pytest apps/api/tests/test_verification_release_evidence.py::test_reusable_evidence_workflow_pulls_published_candidate_images -q`

Expected: FAIL because GHCR credentials and pulls are absent.

- [ ] **Step 3: Add the candidate-image preparation step**

Grant `packages: read`. After digest validation, conditionally parse non-empty JSON, derive exactly `ghcr.io/${GITHUB_REPOSITORY_OWNER}/edu-homework-grader-grader@${grader_digest}` and `ghcr.io/${GITHUB_REPOSITORY_OWNER}/edu-homework-grader-languagetool@${languagetool_digest}`, write them to `GITHUB_ENV`, authenticate with `docker/login-action`, and pull both references. Keep no-digest manual and pull-request behavior unchanged.

- [ ] **Step 4: Run the green test**

Run: `python -m pytest apps/api/tests/test_verification_release_evidence.py::test_reusable_evidence_workflow_pulls_published_candidate_images -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add .github/workflows/verification-release-evidence.yml apps/api/tests/test_verification_release_evidence.py && git commit -m "fix: verify release candidates with published images"`

### Task 4: Verify the release gate

**Files:**

- Verify only.

- [ ] **Step 1: Run targeted coverage**

Run: `python -m pytest apps/api/tests/test_verification_release_evidence.py -q`

Expected: PASS.

- [ ] **Step 2: Validate Compose**

Run: `docker compose --file infra/release-evidence/compose.yaml config --quiet`

Expected: exit code 0.

- [ ] **Step 3: Check the change boundary**

Run: `git diff --check && git status --short`

Expected: no whitespace errors and only Tasks 1-3 files staged for the final commit.

- [ ] **Step 4: Commit the verified fix**

Run: `git add .github/workflows/verification-release-evidence.yml infra/release-evidence/compose.yaml apps/api/src/edu_grader_api/services/verification_release_timeout_evidence.py apps/api/tests/test_verification_release_evidence.py && git commit -m "fix: verify release candidates with published images"`
