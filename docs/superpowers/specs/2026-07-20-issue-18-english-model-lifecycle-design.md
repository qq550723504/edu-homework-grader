# Issue 18 English Model Delivery and Lifecycle Design

## Goal

Complete the remaining verification and documentation gaps for the fixed English embedding model without replacing the existing image-layer delivery or FastAPI lifecycle architecture.

## Existing production path

The Grader image installs `sentence-transformers`, downloads `sentence-transformers/all-MiniLM-L6-v2` at a fixed revision during image construction, computes a deterministic tree digest, and writes `metadata.json`. At runtime `SentenceTransformerSimilarity` validates that metadata against configured ID, revision, and digest, then uses `local_files_only=True`.

FastAPI lifespan constructs the similarity adapter once and stores it on application state. Requests reuse that instance. Startup failure creates `UnavailableSimilarity`; `/ready` reports a degraded 503 while E1-E3 remain independent of it and E4 produces the existing teacher-review result.

## Scope

This slice retains the current Docker image-layer delivery method. It adds regression evidence that the Dockerfile invokes the verified prefetch path, the model failure is visible through readiness while the service remains safe, and model version documentation exactly matches the verified deployment configuration.

It does not change the model ID, automatic English-scoring policy, E4's teacher-review requirement, the model download client, or introduce a network fallback at runtime.

## Failure behavior

Missing model files, invalid metadata, and mismatched ID/revision/digest are deployment faults. The process starts in an explicit degraded state so health checks can distinguish process liveness from English-model traffic readiness. E4 receives `UnavailableSimilarity` and becomes `needs_review`; E1-E3 do not require the embedding model and remain functional.

## Version evidence

One verified revision/digest pair is the authority. Docker build arguments, Compose defaults, `.env.example`, and README must match it. Each English grading response continues to expose the embedding ID/revision/digest and the `sentence-transformers` runtime package version in dependency versions.

## Test strategy

- extend lifecycle tests to assert model-load failure yields degraded readiness and a safe E4 review result;
- extend deployment tests to assert Dockerfile executes prefetch with model ID, revision, digest, and output directory, and contains no runtime model-download command;
- keep the digest fixture test as the cross-file configuration authority, adding README to it;
- run focused Grader tests, then the complete Python suite, format/lint, Compose rendering, and a Grader image build when Docker is available.
