# AI Candidate Duplicate Detection Design

**Issue:** #40
**Date:** 2026-07-22

## Scope

Add a deterministic duplicate gate to AI candidate verification.  For one tenant, it compares a generated candidate with (1) the other candidates in the same generation job and (2) every published `QuestionVersion` in that tenant.  It detects byte-for-byte prompt copies, Unicode/whitespace/case-normalized copies, and semantic near duplicates.

This slice does not create a teacher acceptance flow, publish a `QuestionVersion`, tune thresholds from production outcomes, or use a hosted embedding API.  Those responsibilities remain with #41, #42, and #43 respectively.

## Existing Foundations and Root Cause

`GeneratedQuestionDraft.content_hash` is a SHA-256 of the complete provider response.  It is useful for response integrity, but is not comparable with `QuestionVersion`, whose only common question surface is `prompt`.  `question_verification._has_normalized_duplicate` currently scans prompts of all tenant drafts, returns only a warning, and never queries the question bank.  Therefore it cannot satisfy the issue's exact, normalized, or semantic checks across the required comparison sets.

The Grader already owns a locally packaged, revision-pinned `sentence-transformers/all-MiniLM-L6-v2` model through `SentenceTransformerSimilarity`.  Reusing that service keeps embeddings out of Core API, does not call an external provider, and keeps the model lifecycle/readiness contract in one place.

## Comparison Contract

The stable comparison surface is a candidate or version's `prompt` only.  It is the only author-facing question field shared by generated drafts and formal question versions.  `reading_material`, answers, explanations, rules, titles, student data, and internal IDs are excluded: including them would make the two source types incomparable and could turn answer keys into a false duplicate signal.

`question-fingerprint-v1` creates two SHA-256 values from that surface:

- `exact_prompt_hash`: UTF-8 prompt exactly as stored.
- `normalized_prompt_hash`: NFKC normalization, trimmed and collapsed whitespace, then case-folded; this matches the existing verifier normalization semantics.

The comparison scope is tenant-local.  It includes published `QuestionVersion` rows and the current `GenerationJob`'s other drafts, never another tenant's data.  It intentionally excludes unrelated pending generation jobs: those have not entered the formal bank and are not "同批候选题".

## Data and Migration

Add `fingerprint_version`, `exact_prompt_hash`, and `normalized_prompt_hash` to both `GeneratedQuestionDraft` and `QuestionVersion`.  The migration backfills existing rows from their persisted prompt surfaces before making the fields non-null, then creates indexes appropriate to their lookup path:

- drafts: `(job_id, fingerprint_version, exact_prompt_hash)` and `(job_id, fingerprint_version, normalized_prompt_hash)`;
- versions: tenant lookup requires a `Question` join, so index version fingerprints and keep the existing `questions.tenant_id` path indexed.

Generation persistence computes draft fingerprints at the same point it computes the existing response `content_hash`.  Question creation and draft edits compute version fingerprints before persistence.  The old response `content_hash` remains unchanged; it is not repurposed as a question fingerprint.

Fingerprint construction is a small pure module shared by persistence and verification.  Its unit tests fix Unicode, whitespace, case, empty-input, and versioned-algorithm behaviour.  A future fingerprint algorithm creates a new version rather than silently changing existing hash meanings.

## Grader Boundary

Add a private Grader endpoint, `POST /v1/semantic-similarity`, with a bounded request:

```json
{
  "query": "candidate prompt",
  "comparisons": ["bank prompt", "batch prompt"]
}
```

The endpoint accepts de-identified strings only, enforces per-string and per-request count limits, and returns scores in the same order.  It neither stores text nor accepts tenant IDs or source IDs.  Core API maps positions back to source categories locally.

Extend the existing `SemanticSimilarity` abstraction with a batch operation.  `SentenceTransformerSimilarity` encodes the query and comparison texts in one local batch with normalized embeddings; test doubles retain deterministic scores.  The Grader returns a service failure when its model is unavailable or returns a malformed/non-finite score.  Core API's `HttpGraderClient` validates the internal allowlisted URL and de-identification policy before making the request, as it already does for grading.

The Core API chunks the complete, tenant-local comparator set at the endpoint limit.  It never silently truncates it.  If a configured operational ceiling is reached, or any chunk cannot be scored, verification returns a stable blocked finding instead of claiming that the candidate passed a partial semantic scan.

## Verification Flow and Outcomes

After structural and safety validation establishes a usable prompt, verification proceeds in this order:

```text
candidate prompt
  -> exact hash lookup: same batch + published tenant bank
  -> normalized hash lookup: same scope, excluding exact match result
  -> retrieve remaining same-scope prompt texts
  -> internal Grader semantic-similarity batches
  -> immutable GenerationValidationRun + ValidationFinding records
```

An exact or normalized match produces a `blocked` finding (`duplicate_exact_prompt` or `duplicate_normalized_prompt`).  A semantic result at or above `AI_DUPLICATE_SIMILARITY_THRESHOLD` produces `duplicate_semantic_near_match` with `blocked` severity.  The initial default is deliberately conservative and is recorded in the run feature summary together with fingerprint and embedding dependency versions.  #42 supplies the labelled calibration evidence needed to change the default; #43 can move the setting to a curriculum-profile policy without changing the event contract.

No raw compared prompt, database ID, exact score, tenant ID, answer, or explanation appears in a finding.  Evidence contains only a stable source category (`published_question` or `batch_candidate`), comparison method, and a threshold-band indicator.  The remediation tells the teacher to author a materially distinct prompt.  This makes blocked results displayable without disclosing another teacher's content.

Failure to form the comparison set, call the Grader, validate its response, or cover every chunk produces `duplicate_semantic_check_unavailable` with `blocked` severity and sanitized evidence.  It does not fall through to `passed` or `warning`.

## API, Compatibility, and Observability

No new public teacher route is added.  Existing candidate-validation responses expose the immutable run and its stable codes; #41 can render those findings.  Bump verifier/ruleset version when the new gate ships so historical results remain interpretable.  The feature summary records counts by source category, the selected threshold, fingerprint version, and embedding dependency version, but no source text or identifiers.

The endpoint is internal-only at deployment routing.  Its request and response are covered by processor-policy de-identification tests, URL allowlist tests, request size tests, malformed response tests, and Grader readiness tests.

## Acceptance Tests

- The same raw prompt in another draft of the job blocks with the exact-hash code.
- Case, NFKC, or whitespace-only prompt variation blocks with the normalized-hash code.
- A candidate semantically close to a published `QuestionVersion` blocks; the finding reveals only `published_question` and a threshold band.
- A close candidate in the same batch blocks; another tenant's question is never queried or disclosed.
- A safe, distinct candidate passes this gate and retains the other verifier results.
- Grader unavailability, timeout, malformed/misaligned score count, non-finite score, and incomplete chunk coverage all block with the stable unavailable code.
- Migration backfill fingerprints existing drafts and versions, and normal generation/question edits keep them current.
- The Grader uses its local pinned model; the Core API gains no embedding library or external-model credential.

## Deferred Work

Threshold calibration and false-positive/false-negative evaluation belong to #42.  Per-profile threshold governance and batch-acceptance policy belong to #43.  Teacher-side acknowledgement and candidate-to-question conversion belong to #41.  A database vector index is intentionally not introduced before measured comparator volume demonstrates that complete, chunked local scoring exceeds the synchronous verifier budget; any later index must preserve the same complete-scan-or-block semantics.
