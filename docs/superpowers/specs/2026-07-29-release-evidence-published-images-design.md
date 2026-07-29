# Release evidence published-image design

## Problem

The production release workflow publishes immutable images, then the release-evidence
job rebuilds the Grader and LanguageTool images from source with `docker compose up
--build`. That duplicates the release build and makes a release depend on external
upstream repositories after the candidate images already exist. On 2026-07-29, the
LanguageTool Maven repository returned HTTP 409 while resolving an OpenTelemetry BOM,
so evidence failed before Kubernetes deployment.

## Design

When the reusable release-evidence workflow receives the required candidate image
digests, it will authenticate to GHCR, pull the immutable Grader and LanguageTool
images by digest, and pass their full image references to the evidence Compose
definition. The evidence runner will omit `--build` in this mode. The Compose services
will use the supplied image references; no upstream source build will occur.

Pull-request and manual evidence runs without candidate digests retain the existing
source-build path. The candidate mode is enabled only when both required image
references are present, so a partially configured run fails early rather than falling
back silently.

## Validation

Regression tests will prove that candidate-image mode omits `--build` and that the
workflow derives only digest-pinned GHCR references. The workflow configuration will
be validated, targeted tests will run, and a new production publish workflow will be
started only after the corrected change is merged.
