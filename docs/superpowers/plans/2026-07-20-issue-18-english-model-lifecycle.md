# Issue 18 English Model Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining lifecycle, image-delivery, and documentation evidence gaps for the fixed English embedding model.

**Architecture:** Keep the existing image-layer model delivery and lifespan-owned similarity instance. Add failure-path tests around the current `UnavailableSimilarity` degraded mode, structural evidence for the Docker prefetch boundary, and a single digest test that includes README.

**Tech Stack:** Python 3.13, FastAPI, pytest, Docker Compose, sentence-transformers.

## Global Constraints

- The model remains `sentence-transformers/all-MiniLM-L6-v2` at revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` with digest `sha256:84714cdabb16d132cbe6e1a4cbd21167abd09eccbdaf69dd053136ae68cc7c17`.
- Runtime loading uses only local model files; do not introduce a network download fallback.
- Model failure returns `503 {"status": "degraded", "english_embedding_model": "unavailable"}`; E4 stays `needs_review`.
- E1-E3 must not become dependent on the embedding model.
- Do not alter E4's teacher-review policy or model delivery topology.

---

### Task 1: Regression-test degraded model lifecycle

**Files:**
- Modify: `services/grader/tests/test_english_lifecycle.py`

**Interfaces:**
- Consumes `main.SentenceTransformerSimilarity`, `EnglishDependencyError`, and FastAPI lifespan.
- Verifies existing `UnavailableSimilarity` behavior without changing production code.

- [ ] **Step 1: Write the failing lifecycle test**

Add `EnglishDependencyError` to the imports and define:

```python
class FailingSimilarity:
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise EnglishDependencyError("model directory is unavailable")
```

Then add:

```python
def test_missing_embedding_model_is_degraded_and_e4_stays_review_safe(monkeypatch) -> None:
    monkeypatch.setattr(main, "SentenceTransformerSimilarity", FailingSimilarity)
    with TestClient(main.app) as client:
        assert client.get("/ready").status_code == 503
        assert client.get("/ready").json() == {
            "status": "degraded",
            "english_embedding_model": "unavailable",
        }
        response = client.post(
            "/v1/grade/english",
            json={
                "question_type": "E4",
                "policy_version": "2",
                "rule": {
                    "scoring_points": [{"id": "point", "evidence_phrases": ["evidence"], "score": 1}],
                    "max_score": 1,
                },
                "answer": {"answer": "student answer"},
            },
        )
    assert response.status_code == 200
    assert response.json()["decision"] == "needs_review"
    assert response.json()["requires_review"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$env:PYTHONPATH = ((Resolve-Path 'packages/processor-policy/src').Path + ';' + (Resolve-Path 'services/grader/src').Path); python -m pytest services/grader/tests/test_english_lifecycle.py -q`

Expected: FAIL because `EnglishDependencyError` is not imported by the test module.

- [ ] **Step 3: Make the test use the existing implementation**

Import `EnglishDependencyError` from `edu_grader.english_dependencies`; do not edit `main.py` or dependency production code. The existing `_load_semantic_similarity()` catch converts the raised error into `UnavailableSimilarity`.

- [ ] **Step 4: Run test to verify it passes**

Run: `$env:PYTHONPATH = ((Resolve-Path 'packages/processor-policy/src').Path + ';' + (Resolve-Path 'services/grader/src').Path); python -m pytest services/grader/tests/test_english_lifecycle.py services/grader/tests/test_english_orchestrator.py -q`

Expected: lifecycle and E4 review-safety tests pass.

- [ ] **Step 5: Commit**

```powershell
git add services/grader/tests/test_english_lifecycle.py
git commit -m "test: cover degraded english model lifecycle"
```

### Task 2: Lock image delivery evidence and documentation to the verified digest

**Files:**
- Modify: `services/grader/tests/test_deployment.py`
- Modify: `services/grader/tests/test_prefetch_english_model.py`
- Modify: `README.md`

**Interfaces:**
- `test_configured_english_model_digest_matches_the_verified_snapshot()` becomes the single cross-file digest consistency test.
- `test_grader_dockerfile_prefetches_the_fixed_english_model()` verifies the build-time prefetch contract.

- [ ] **Step 1: Write the failing consistency test**

Extend the existing digest test's path tuple with `repository_root / "README.md"`, then run:

```python
$env:PYTHONPATH = ((Resolve-Path 'packages/processor-policy/src').Path + ';' + (Resolve-Path 'services/grader/src').Path)
python -m pytest services/grader/tests/test_prefetch_english_model.py -q
```

Expected: FAIL because README currently documents a different digest.

- [ ] **Step 2: Write the Docker delivery regression test**

Add this to `services/grader/tests/test_deployment.py`:

```python
def test_grader_dockerfile_prefetches_the_fixed_english_model() -> None:
    dockerfile = Path("services/grader/Dockerfile").read_text(encoding="utf-8")

    assert "RUN python scripts/prefetch_english_model.py" in dockerfile
    assert '--model-id "$ENGLISH_EMBEDDING_MODEL_ID"' in dockerfile
    assert '--revision "$ENGLISH_EMBEDDING_MODEL_REVISION"' in dockerfile
    assert '--expected-digest "$ENGLISH_EMBEDDING_MODEL_DIGEST"' in dockerfile
    assert '--output "$ENGLISH_EMBEDDING_MODEL_DIRECTORY"' in dockerfile
    assert "CMD [\"uvicorn\"" in dockerfile
```

- [ ] **Step 3: Apply the minimal documentation fix**

Replace README's English E4 tree digest with:

```text
sha256:84714cdabb16d132cbe6e1a4cbd21167abd09eccbdaf69dd053136ae68cc7c17
```

Do not change the model ID, revision, license statement, or runtime `local_files_only=True` documentation.

- [ ] **Step 4: Run focused tests and quality checks**

Run: `$env:PYTHONPATH = ((Resolve-Path 'packages/processor-policy/src').Path + ';' + (Resolve-Path 'services/grader/src').Path); python -m pytest services/grader/tests/test_deployment.py services/grader/tests/test_prefetch_english_model.py -q; python -m ruff format --check services/grader/tests/test_deployment.py services/grader/tests/test_prefetch_english_model.py; python -m ruff check services/grader/tests/test_deployment.py services/grader/tests/test_prefetch_english_model.py`

Expected: all focused tests and Ruff checks pass.

- [ ] **Step 5: Commit**

```powershell
git add services/grader/tests/test_deployment.py services/grader/tests/test_prefetch_english_model.py README.md
git commit -m "docs: align english model digest"
```

### Task 3: Full verification and GitHub closure

**Files:**
- Verify only.

- [ ] **Step 1: Run full Grader and Python validation**

Run: `$env:PYTHONPATH = ((Resolve-Path 'packages/processor-policy/src').Path + ';' + (Resolve-Path 'apps/api/src').Path + ';' + (Resolve-Path 'services/grader/src').Path); python -m ruff format --check packages/processor-policy apps/api services/grader; python -m ruff check packages/processor-policy apps/api services/grader; python -m pytest packages/processor-policy/tests apps/api/tests services/grader/tests -q`

Expected: all format/lint checks pass and the full suite passes.

- [ ] **Step 2: Verify Compose and image construction**

Set the same non-secret CI placeholder environment values used by the repository CI, then run:

```powershell
docker compose config --quiet
docker compose build grader
```

Expected: Compose renders and the Grader image build prefetches the verified snapshot during the Docker build.

- [ ] **Step 3: Push and close #18**

Run: `git status --short; git log --oneline main..HEAD`

Expected: only the Issue 18 design, plan, lifecycle test, deployment/digest tests, and README correction are present. Push the branch, open a draft PR with `Closes #18`, then close GitHub issue #18 after all verification evidence is recorded.

