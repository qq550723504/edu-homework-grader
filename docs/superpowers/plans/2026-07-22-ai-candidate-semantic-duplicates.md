# AI Candidate Semantic Duplicate Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Block an AI candidate whose prompt is an exact, normalized, or semantic near duplicate of a published tenant question or another candidate in the same generation job.

**Architecture:** Core API creates compatible versioned prompt hashes for drafts and question versions, applies indexed hash checks, then requests bounded local-Grader batch similarity. An unavailable or incomplete semantic scan always blocks.

**Tech Stack:** Python 3.14, FastAPI, Pydantic, SQLAlchemy/Alembic, PostgreSQL/SQLite, httpx, sentence-transformers.

## Global Constraints

- Compare only `prompt`, never answers, rules, explanations, reading material, titles, student data, or IDs.
- Compare only published versions in the same tenant and other drafts in the current `GenerationJob`.
- Use `question-fingerprint-v1`, SHA-256 raw hashes, and NFKC/trim/collapsed-whitespace/case-fold normalized hashes.
- Reuse Grader's local model; no Core API embedding dependency or external-model credential.
- Grader accepts only bounded de-identified strings without tenant/source IDs.
- Exact, normalized, semantic-threshold, timeout, malformed, unavailable, and incomplete outcomes are sanitized `blocked` findings.
- Chunk semantic requests completely; a partial comparator set cannot pass.
- Do not add a public route or teacher acceptance/publishing flow.

---

### Task 1: Versioned prompt fingerprints and indexed persistence

**Files:**
- Create: `apps/api/src/edu_grader_api/services/question_fingerprints.py`
- Modify: `apps/api/src/edu_grader_api/models.py`
- Create: `apps/api/alembic/versions/0017_question_prompt_fingerprints.py`
- Create: `apps/api/tests/test_question_fingerprints.py`
- Modify: `apps/api/tests/test_generation_models.py`
- Modify: `apps/api/tests/test_question_models.py`

**Interfaces:** `PromptFingerprints(version: str, exact_hash: str, normalized_hash: str)`; `normalize_prompt(prompt: str) -> str`; `fingerprint_prompt(prompt: str) -> PromptFingerprints`; non-null `fingerprint_version`, `exact_prompt_hash`, `normalized_prompt_hash` on `GeneratedQuestionDraft` and `QuestionVersion`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_fingerprint_prompt_distinguishes_raw_and_normalized_surfaces() -> None:
    first = fingerprint_prompt("  CAFÉ\u3000Question  ")
    second = fingerprint_prompt("café question")
    assert first.version == "question-fingerprint-v1"
    assert first.exact_hash != second.exact_hash
    assert first.normalized_hash == second.normalized_hash

def test_prompt_assignment_refreshes_version_fingerprints(session: Session) -> None:
    version = make_question_version(session, prompt="First prompt")
    version.prompt = "Changed prompt"
    session.flush()
    assert version.exact_prompt_hash == fingerprint_prompt("Changed prompt").exact_hash
```

- [ ] **Step 2: Verify the tests fail.** Run `python -m pytest apps/api/tests/test_question_fingerprints.py apps/api/tests/test_generation_models.py apps/api/tests/test_question_models.py -q`. Expected: failure because the module and fields are absent.

- [ ] **Step 3: Implement the module and model field population.**

```python
FINGERPRINT_VERSION = "question-fingerprint-v1"
_WHITESPACE = re.compile(r"\s+")

def normalize_prompt(prompt: str) -> str:
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", prompt).strip()).casefold()

def fingerprint_prompt(prompt: str) -> PromptFingerprints:
    return PromptFingerprints(
        version=FINGERPRINT_VERSION,
        exact_hash=hashlib.sha256(prompt.encode()).hexdigest(),
        normalized_hash=hashlib.sha256(normalize_prompt(prompt).encode()).hexdigest(),
    )
```

Use SQLAlchemy validators on `QuestionVersion.prompt` and `GeneratedQuestionDraft.candidate_json` to set all three fields only when a prompt is a string. Preserve malformed draft records so the current verifier, rather than persistence, blocks them.

- [ ] **Step 4: Add migration `0017_question_prompt_fingerprints`.** Set `revision = "0017_question_prompt_fingerprints"` and `down_revision = "0016_ai_question_validation_runs"`. Add nullable fields, stream `QuestionVersion.prompt` and `GeneratedQuestionDraft.candidate_json["prompt"]`, compute equivalent migration-local v1 hashes, then make every field non-null. Use empty prompt only for malformed legacy JSON. Add draft indexes `(job_id, fingerprint_version, exact_prompt_hash)` and `(job_id, fingerprint_version, normalized_prompt_hash)`, version fingerprint indexes, and a `questions.tenant_id` index for tenant lookup. Downgrade removes indexes before fields.

- [ ] **Step 5: Verify the persistence slice.** Run `python -m pytest apps/api/tests/test_question_fingerprints.py apps/api/tests/test_generation_models.py apps/api/tests/test_question_models.py apps/api/tests/test_curriculum_models.py -q`. Expected: PASS and the Alembic-head test expects `0017_question_prompt_fingerprints`.

- [ ] **Step 6: Commit.** Run `git add apps/api/src/edu_grader_api/services/question_fingerprints.py apps/api/src/edu_grader_api/models.py apps/api/alembic/versions/0017_question_prompt_fingerprints.py apps/api/tests/test_question_fingerprints.py apps/api/tests/test_generation_models.py apps/api/tests/test_question_models.py`, then `git commit -m "feat: fingerprint generated question prompts"`.

### Task 2: Bounded local batch similarity endpoint in Grader

**Files:**
- Modify: `services/grader/src/edu_grader/english_dependencies.py`
- Modify: `services/grader/src/edu_grader/main.py`
- Modify: `services/grader/tests/test_english_dependencies.py`
- Modify: `services/grader/tests/test_english_lifecycle.py`

**Interfaces:** `SemanticSimilarity.score_many(query: str, comparisons: list[str]) -> list[float]`; `POST /v1/semantic-similarity` accepts a query and 1..128 comparison strings, all 1..10,000 characters; response is `{"scores": list[float], "embedding": dict[str, str]}` in comparison order.

- [ ] **Step 1: Write failing Grader tests.**

```python
def test_static_similarity_scores_every_comparison() -> None:
    assert StaticSimilarity(0.8).score_many("query", ["one", "two"]) == [0.8, 0.8]

def test_similarity_endpoint_returns_ordered_scores(monkeypatch) -> None:
    monkeypatch.setattr(main, "SentenceTransformerSimilarity", FakeSimilarity)
    with TestClient(main.app) as client:
        response = client.post("/v1/semantic-similarity", json={"query": "What is two plus two?", "comparisons": ["Compute 2 + 2.", "Name a color."]})
    assert response.status_code == 200
    assert response.json()["scores"] == [0.9, 0.1]
```

- [ ] **Step 2: Verify failure.** Run `python -m pytest services/grader/tests/test_english_dependencies.py services/grader/tests/test_english_lifecycle.py -q`. Expected: failure because the batch method and endpoint are absent.

- [ ] **Step 3: Implement batch scoring and the private endpoint.**

```python
def score_many(self, query: str, comparisons: list[str]) -> list[float]:
    vectors = self._model.encode([query, *comparisons], normalize_embeddings=True)
    query_vector = vectors[0]
    return [_valid_similarity(sum(float(a) * float(b) for a, b in zip(query_vector, vector, strict=True))) for vector in vectors[1:]]
```

Extend `SemanticSimilarity`, `StaticSimilarity`, and `UnavailableSimilarity`. Add Pydantic request/response models in `main.py`; validate `request.model_dump()` with `assert_deidentified_payload`. Return HTTP 503 for unavailable models, scoring errors, non-finite values, or a score-count mismatch. Return embedding metadata but never request text.

- [ ] **Step 4: Verify.** Run `python -m pytest services/grader/tests/test_english_dependencies.py services/grader/tests/test_english_lifecycle.py services/grader/tests/test_english_orchestrator.py -q`. Expected: PASS, including E4 behaviour.

- [ ] **Step 5: Commit.** Run `git add services/grader/src/edu_grader/english_dependencies.py services/grader/src/edu_grader/main.py services/grader/tests/test_english_dependencies.py services/grader/tests/test_english_lifecycle.py`, then `git commit -m "feat: add internal semantic similarity endpoint"`.

### Task 3: Core API adapter and duplicate verification gate

**Files:**
- Modify: `apps/api/src/edu_grader_api/services/grader.py`
- Modify: `apps/api/src/edu_grader_api/services/question_verification.py`
- Modify: `apps/api/src/edu_grader_api/settings.py`
- Modify: `apps/api/tests/test_english_grader_client.py`
- Modify: `apps/api/tests/test_question_verification.py`
- Modify: `apps/api/tests/test_settings.py`

**Interfaces:** `HttpGraderClient.semantic_similarity(query: str, comparisons: list[str]) -> list[float]`; the same method on `VerificationGraderClient`; `_duplicate_findings(session, draft, tenant_id, prompt, grader_client) -> list[VerificationFinding]`; codes `duplicate_exact_prompt`, `duplicate_normalized_prompt`, `duplicate_semantic_near_match`, `duplicate_semantic_check_unavailable`.

- [ ] **Step 1: Write failing adapter and verifier tests.**

```python
def test_http_grader_client_posts_semantic_batch(monkeypatch) -> None:
    monkeypatch.setattr("edu_grader_api.services.grader.httpx.post", fake_post_returning({"scores": [0.94, 0.03]}))
    assert HttpGraderClient("http://grader").semantic_similarity("query", ["first", "second"]) == [0.94, 0.03]

def test_exact_batch_duplicate_is_blocked_without_source_text(session: Session) -> None:
    _, duplicate = two_drafts_same_job(session, prompts=["What is 2 + 2?", "What is 2 + 2?"])
    finding = finding_by_code(run_candidate_verification(session, draft=duplicate, grader_client=SemanticGrader([])), "duplicate_exact_prompt")
    assert finding.evidence_json == {"comparison": "batch_candidate", "method": "exact_hash"}

def test_semantic_published_question_is_blocked_without_raw_comparator(session: Session) -> None:
    draft = generation_draft(session, candidate_json=valid_m1_candidate(prompt="Calculate two plus two."))
    add_published_question(session, tenant=draft.job.tenant, prompt="What is 2 + 2?")
    finding = finding_by_code(run_candidate_verification(session, draft=draft, grader_client=SemanticGrader([0.96])), "duplicate_semantic_near_match")
    assert finding.evidence_json == {"comparison": "published_question", "method": "semantic", "threshold_band": "at_or_above"}
```

- [ ] **Step 2: Verify failure.** Run `python -m pytest apps/api/tests/test_english_grader_client.py apps/api/tests/test_question_verification.py -q`. Expected: failure because the adapter, protocol method, and codes are absent.

- [ ] **Step 3: Implement request validation and complete comparator coverage.**

```python
def semantic_similarity(self, query: str, comparisons: list[str]) -> list[float]:
    payload = {"query": query, "comparisons": comparisons}
    self._validate_request(payload)
    response = httpx.post(f"{self.base_url}/v1/semantic-similarity", json=payload, timeout=10)
    response.raise_for_status()
    scores = response.json().get("scores")
    if not isinstance(scores, list) or len(scores) != len(comparisons):
        raise ValueError("semantic similarity response is invalid")
    if any(isinstance(score, bool) or not isinstance(score, int | float) or not math.isfinite(score) for score in scores):
        raise ValueError("semantic similarity response is invalid")
    return [float(score) for score in scores]
```

Add `ai_duplicate_similarity_threshold: float = Field(default=0.92, ge=0, le=1)` to Core API settings and its `AI_DUPLICATE_SIMILARITY_THRESHOLD` environment alias, with settings tests for default, override, and invalid values. Replace `_has_normalized_duplicate` with `_duplicate_findings`. Query matching fingerprints first. Retrieve remaining published prompts by `Question.tenant_id` plus `QuestionVersion.status == PUBLISHED`, and current-job draft prompts excluding the candidate. De-duplicate comparator strings by normalized hash; mark each `published_question` or `batch_candidate`; score every item in chunks of 128. Use the validated settings threshold, require every score in `[0, 1]`, and store threshold and comparison counts in feature summary without text or IDs. Exact/normalized matches block before Grader calls. Any exception, malformed response, invalid score, or missed chunk returns `duplicate_semantic_check_unavailable` with `{"category": "similarity_unavailable"}`. Duplicate remediation is `"Revise the prompt to make the candidate meaningfully distinct."`.

- [ ] **Step 4: Verify.** Run `python -m pytest apps/api/tests/test_english_grader_client.py apps/api/tests/test_question_verification.py apps/api/tests/test_ai_question_generation_api.py -q`. Expected: PASS with extended fake Grader clients.

- [ ] **Step 5: Commit.** Run `git add apps/api/src/edu_grader_api/services/grader.py apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_english_grader_client.py apps/api/tests/test_question_verification.py`, then `git commit -m "feat: block duplicate AI question candidates"`.

### Task 4: Full verification and PR-first delivery

**Files:**
- Modify: `docs/superpowers/plans/2026-07-22-ai-candidate-semantic-duplicates.md` (completed boxes only)
- Modify: GitHub Issue #40 body after merge only

- [ ] **Step 1: Run all verification.** Run `python -m ruff format --check apps/api services/grader`; run `python -m ruff check apps/api services/grader`; run `python -m pytest packages/processor-policy/tests services/generator/tests apps/api/tests services/grader/tests -q`; run `git diff --check`. Expected: exit 0; the known Alembic `path_separator` deprecation warning may remain.

- [ ] **Step 2: Commit completed plan boxes.** Run `git add docs/superpowers/plans/2026-07-22-ai-candidate-semantic-duplicates.md`, then `git commit -m "docs: record duplicate detection verification"`. Confirm with `git log --oneline origin/main..HEAD` that no generated artifact is included.

- [ ] **Step 3: Push and create a ready PR before merge.** Run `git push -u origin codex/ai-semantic-duplicates`, then `gh pr create --base main --head codex/ai-semantic-duplicates --title "feat: block duplicate AI question candidates"`, then `gh pr checks --watch`. Expected: green required checks.

- [ ] **Step 4: Resolve review, merge, and update the issue precisely.** Run `gh pr view --json reviewDecision,reviews,comments,statusCheckRollup`, resolve findings, then `gh pr merge --admin --squash --delete-branch`. Confirm with `gh issue view 40 --json body,state`; only mark the duplicate-detection checklist item complete. Issue #40 remains open.

## Plan Self-Review

**Spec coverage:** Task 1 supplies compatible fingerprints, indexes, and migration backfill. Task 2 reuses the local pinned model through a private bounded endpoint. Task 3 enforces tenant/same-batch scope, sanitized evidence, complete chunk coverage, and fail-closed results. Task 4 preserves PR-first protected-branch delivery.

**Placeholder scan:** Every task lists files, interfaces, a failing-test action, exact commands, expected outcomes, and commit boundary. The migration identifies source surfaces, transformation, index path, nullability transition, and downgrade order.

**Type consistency:** Task 1 defines fingerprint names, Task 2 defines `score_many` and ordered scores, Task 3 consumes them and defines the Core protocol and four codes, and Task 4 consumes those completed contracts.
