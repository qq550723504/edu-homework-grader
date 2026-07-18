# English E1-E4 Grading Design

## Goal

Implement Issue #6: provide explainable English grading for deterministic E1-E3 questions, grammar feedback from a self-hosted LanguageTool service, and review-only E4 reading-answer signals with calibration reporting.

## Scope

This slice adds versioned English policies, deterministic normalization and word-form grading, a LanguageTool adapter, local semantic-similarity signals, immutable grading evidence, and a calibration-data format with aggregate metrics.

It does not add automated E4 publication, an LLM judge, a public grammar API, or an external embedding API. E4 always remains `needs_review`; semantic similarity never independently awards credit.

## Selected approach

The Grader remains the only service that interprets de-identified English rules and answers. It owns an English orchestrator with deterministic rule evaluators plus small adapters for LanguageTool and local sentence embeddings. The API sends rules and answers to the Grader, persists its complete result, and exposes teacher-review data; it does not make language judgments.

LanguageTool is deployed beside the existing services with a repository-owned Dockerfile built from a pinned upstream LanguageTool release. The Grader calls its `/v2/check` endpoint through a timeout-bounded client. A LanguageTool failure produces a visible non-decisive signal and `needs_review` when the question requires grammar feedback; it must never turn an answer into `auto_rejected`.

E4 similarity is computed locally with the pinned Apache-2.0 `sentence-transformers/all-MiniLM-L6-v2` model and cosine similarity. The model revision and artifact digest are configuration values recorded with each run. The similarity adapter is an interface so a later, calibrated model can replace it without changing scoring rules or persisted evidence.

## Versioned policies

Existing E1@1 questions keep their exact-answer behavior. New E1@2 and new E2@1, E3@1, and E4@2 policies make grading decisions reproducible for published versions.

### E1@2: accepted answers

An E1@2 rule contains explicit normalization settings and the teacher-maintained accepted forms:

```json
{
  "accepted_answers": ["I am", "I'm"],
  "normalization": {
    "unicode_form": "NFKC",
    "collapse_whitespace": true,
    "ignore_case": true,
    "ignore_terminal_punctuation": true
  },
  "max_score": 1
}
```

`accepted_answers` includes alternate spellings, abbreviations, and teacher-approved synonymous wording. The evaluator performs no generated synonym expansion. It records the normalized student answer, the matched normalized accepted answer when present, and the normalization policy version.

### E2@1: word and phrase forms

An E2@1 rule evaluates a finite set of expected forms rather than attempting open-ended grammatical inference:

```json
{
  "lemma": "go",
  "accepted_forms": ["went"],
  "constraints": {
    "part_of_speech": "verb",
    "tense": "past",
    "number": null,
    "determiner": null
  },
  "max_score": 1
}
```

The rule can set `number`, `tense`, and `determiner` when those constraints apply. The deterministic evaluator normalizes input, checks the configured accepted form set, and returns a criterion for every violated configured constraint. It does not infer unconfigured morphology from a third-party grammar service.

### E3@1: grammar-assisted response

An E3@1 rule defines the answer text limit, maximum score, and whether grammar feedback is required. Its decision remains deterministic: E3 can use E1/E2-like expected-answer rules when configured, but LanguageTool matches only add feedback. Each match stores the original offset and length, rule ID, category, issue type, message, and replacement values.

### E4@2: reading short answer

An E4@2 rule defines independently scoreable points:

```json
{
  "scoring_points": [
    {
      "id": "cause",
      "evidence_phrases": ["because the bridge was closed"],
      "score": 1
    },
    {
      "id": "outcome",
      "evidence_phrases": ["they arrived late"],
      "score": 1
    }
  ],
  "similarity_threshold": 0.78,
  "max_score": 2
}
```

The Grader records a normalized/literal evidence match per scoring point and the highest similarity score against its teacher-authored evidence phrases. A matching point may yield a provisional score, but the final E4 decision is always `needs_review`, `requires_review: true`, and not publishable automatically. If no point has evidence, a high similarity score is retained as a review signal only and the provisional score remains zero.

## Submission, evidence, and review

Submitting an assignment invokes the Grader for every answer after the attempt has been made immutable. The API creates an immutable `grading_runs` record per answer and child `grading_signals` records. A run stores:

- attempt answer and assignment item IDs;
- the question-version ID, grading-policy ID and policy version;
- decision, score, maximum score, confidence, and `requires_review`;
- Grader version, LanguageTool release, embedding model ID/revision/digest, and all configured thresholds;
- raw structured criteria, feedback, evidence, and dependency-error details.

The stored rule snapshot and answer snapshot are sufficient to reproduce a decision after a teacher changes later versions. Grader timeouts, unavailable dependencies, malformed response data, unsupported rules, and any E4 answer enter review; they are never silently scored as incorrect.

The student-facing submission response contains only submission state and allowed feedback. The teacher review projection contains score signals, evidence, version IDs, and dependency status. Expected answers, rubric internals, and model implementation details are never exposed in student assignment-detail responses.

## Local services and configuration

Compose adds a private `languagetool` service with no host port. The API remains dependent only on the Grader. The Grader receives these configuration values:

- `LANGUAGETOOL_BASE_URL`, defaulting to the private Compose service;
- `LANGUAGETOOL_TIMEOUT_SECONDS`, with a bounded default;
- `ENGLISH_EMBEDDING_MODEL_ID`, revision, and local artifact directory;
- `ENGLISH_SIMILARITY_THRESHOLD` only as a policy-default; every E4 rule persists its selected threshold.

Model weights are fetched during image build or mounted from an explicitly versioned local artifact. Runtime grading does not download models or send student text to an external service.

## Calibration dataset and metrics

The repository defines a validated JSONL format, one de-identified response per line:

```json
{
  "id": "e4-0001",
  "question_type": "E4",
  "rule": {"scoring_points": []},
  "student_answer": "...",
  "human_decision": "needs_review",
  "human_score": 1,
  "human_scoring_point_ids": ["cause"],
  "expected_feedback_codes": []
}
```

It includes at least 100 questions and 1,000 answers across E1-E4, correct, incorrect, blank, boundary, morphology, grammar-feedback, and adversarial examples. A reporting command groups records by question type and computes:

- **error release rate**: automatically accepted answers whose final human decision or score disagrees;
- **revision rate**: reviewed answers whose teacher final score differs from the provisional score;
- **automatic coverage**: answers that receive an automatic decision divided by all evaluated answers.

E4 remains excluded from automatic coverage unless a later policy explicitly changes its review-only rule.

## Testing

Tests are written before implementation and cover:

- E1 policy validation, Unicode/case/whitespace/punctuation normalization, alternatives, abbreviations, and teacher-approved synonyms;
- E2 required forms and each configured tense, number, determiner, and part-of-speech mismatch with stable criterion evidence;
- LanguageTool request mapping, match offsets/categories/suggestions, disabled grammar feedback, timeout, and unavailable-service handling;
- E4 per-point evidence, persisted similarity/model/threshold signals, and the invariant that high similarity without a point match cannot auto-accept or earn provisional credit;
- API grading orchestration, immutable version evidence, no student leakage of expected answers, and dependency errors becoming review items;
- policy-version isolation and mandatory pre-publication test categories for E1-E4;
- JSONL calibration schema validation, the 100-question/1,000-answer fixture cardinality, and per-type metric calculations.

## Acceptance mapping

Explicit E1 normalization and accepted forms satisfy configurable comparison and teacher synonyms. E2 deterministic constraints cover word and phrase morphology. The private LanguageTool adapter provides grammar intervals, classifications, and suggestions without affecting correctness. E4 persists scoring-point and similarity signals while requiring review. Immutable runs retain rules, thresholds, versions, and feedback evidence. The validated calibration corpus and report produce the required risk and coverage metrics.
