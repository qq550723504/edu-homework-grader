# Live Grader Build Cache Design

## Goal

Reduce repeat CI time for `live-grader-integration` when application source changes, while retaining the existing verified English-model delivery and LanguageTool version pinning.

## Root cause

The CI job imports and exports Buildx GHA caches for `grader` and `languagetool`. The cache is available, but the Grader Dockerfile copies `services/grader/src` before it installs the package and prefetches the English model. Any source edit therefore invalidates the model-download layer.

## Design

The Dockerfile will have a `model` stage that copies only `services/grader/pyproject.toml`, `packages/processor-policy`, and the model-prefetch script. It installs the CPU-only PyTorch wheel from PyTorch's official CPU index, constrains the subsequent resolver to that exact wheel, installs the manifest's runtime dependencies and processor-policy, then downloads the verified model. The runtime stage copies the installed Python environment and model directory before it copies Grader source and performs a `--no-deps` package install.

The existing `edu-homework-grader-grader` GHA cache scope remains the remote cache authority. LanguageTool remains pinned and unchanged.

## Verification

Add structural tests for Dockerfile ordering, CPU-only PyTorch installation, and the dependency-free runtime package install. Run the focused Grader tests, lint/format checks, Compose rendering, and a local two-build Docker cache replay that changes only Grader source. The second build must show the model-prefetch step cached.
