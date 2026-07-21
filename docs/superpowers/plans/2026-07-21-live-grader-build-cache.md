# Live Grader Build Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the verified English-model Docker layer cached when only Grader application source changes.

**Architecture:** A stable `model` stage installs dependencies and the verified model without Grader source. The runtime stage copies that environment and model, then installs the source package without resolving dependencies.

**Tech Stack:** Docker Buildx, GitHub Actions cache, Python 3.13, pytest, setuptools.

## Global Constraints

- Keep model revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` and digest `sha256:84714cdabb16d132cbe6e1a4cbd21167abd09eccbdaf69dd053136ae68cc7c17`.
- Do not introduce runtime model downloads, a registry base image, or LanguageTool changes.
- Install `torch==2.13.0+cpu` from `https://download.pytorch.org/whl/cpu`; the Grader has no GPU allocation.
- Preserve the `edu-homework-grader-grader` cache scope.

---

### Task 1: Add cache-boundary regression tests

**Files:**
- Create: `services/grader/tests/test_container_build.py`
- Modify: `services/grader/Dockerfile`

**Interfaces:**
- Consumes: the Dockerfile as UTF-8 text.
- Produces: `test_grader_dockerfile_prefetches_model_before_copying_application_source` and `test_grader_dockerfile_installs_runtime_package_without_dependencies`.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path


DOCKERFILE_PATH = Path(__file__).parents[1] / "Dockerfile"


def test_grader_dockerfile_prefetches_model_before_copying_application_source() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert dockerfile.index("RUN python scripts/prefetch_english_model.py") < dockerfile.index(
        "COPY services/grader/src ./src"
    )


def test_grader_dockerfile_installs_runtime_package_without_dependencies() -> None:
    assert "RUN python -m pip install --no-deps ." in DOCKERFILE_PATH.read_text(encoding="utf-8")


def test_grader_dockerfile_installs_cpu_only_pytorch() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert "--index-url https://download.pytorch.org/whl/cpu torch==2.13.0+cpu" in dockerfile
```

- [ ] **Step 2: Run the test red**

Run: `python -m pytest services/grader/tests/test_container_build.py -q`

Expected: FAIL because source currently precedes prefetch and no dependency-free runtime install exists.

### Task 2: Split stable and volatile image stages

**Files:**
- Modify: `services/grader/Dockerfile`
- Test: `services/grader/tests/test_container_build.py`

**Interfaces:**
- Consumes: Grader project dependencies from `services/grader/pyproject.toml`, processor-policy, and the model-prefetch script.
- Produces: a runtime image with `/opt/english-model`, resolved runtime dependencies, and an installed `edu_grader` package.

- [ ] **Step 1: Create a stable model stage**

```dockerfile
FROM python:3.13-slim AS model
WORKDIR /app
COPY packages/processor-policy /tmp/processor-policy
COPY services/grader/pyproject.toml .
COPY services/grader/scripts ./scripts
RUN python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.13.0+cpu
RUN printf 'torch==2.13.0+cpu\n' > /tmp/torch-constraints.txt && PIP_CONSTRAINT=/tmp/torch-constraints.txt python -c "import subprocess, sys, tomllib; dependencies = tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', '/tmp/processor-policy', *dependencies])"
```

Keep the existing model arguments, model environment variables, and prefetch command in this stage.

- [ ] **Step 2: Build the final runtime stage**

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY --from=model /usr/local /usr/local
COPY --from=model /opt/english-model /opt/english-model
COPY services/grader/pyproject.toml .
COPY services/grader/src ./src
RUN python -m pip install --no-deps .
```

Repeat the current runtime environment variables, `EXPOSE`, and `CMD` in the final stage.

- [ ] **Step 3: Run tests and local cache replay**

Run: `python -m pytest services/grader/tests/test_container_build.py -q`; `docker buildx build --load --tag edu-homework-grader/grader:cache-check --file services/grader/Dockerfile .`; then run the same command once more after changing only a temporary source comment in an isolated throwaway copy.

Expected: tests pass and the second build marks dependency installation and model prefetch as cached.

- [ ] **Step 4: Run focused verification**

Run: `python -m pytest services/grader/tests -q`; `python -m ruff format --check services/grader`; `python -m ruff check services/grader`; `docker compose config --quiet`.

Expected: every command exits zero.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-07-21-live-grader-build-cache-design.md docs/superpowers/plans/2026-07-21-live-grader-build-cache.md services/grader/Dockerfile services/grader/tests/test_container_build.py
git commit -m "ci: reuse cached English model layer"
```

### Task 3: Confirm GHA cache behavior

**Files:**
- No source changes required.

- [ ] **Step 1: Push and inspect `live-grader-integration`**

Run: `git push -u origin codex/ci-grader-cache`.

Expected: the CI build succeeds. A follow-up application-source-only commit restores the stable model-stage layers from the existing GHA cache scope.
