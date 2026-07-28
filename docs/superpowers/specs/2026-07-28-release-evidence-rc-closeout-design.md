# Release evidence RC close-out design

## Goal

Make the existing real-service release-evidence suite a mandatory pre-deployment
gate for every eligible production candidate, without changing its scenario
implementation or turning pull-request evidence into a required check.

## Design

`verification-release-evidence.yml` remains manually runnable and continues to
run observationally for relevant pull requests.  It also accepts
`workflow_call` inputs for the immutable source SHA and a JSON map of the four
published image digests.  The called workflow checks out that SHA, writes a
sanitized release manifest into the uploaded evidence directory, runs the
existing two-pass real PostgreSQL/Grader/LanguageTool suite, and fails its
caller if the suite fails.

`publish-images.yml` remains responsible for release eligibility and immutable
image publication.  Each matrix build saves its build-push digest as a
short-lived internal artifact.  A manifest job validates and combines all four
digests, then calls the release-evidence workflow.  `deploy` depends on that
call as well as the successful image publication, so the existing protected
production Environment approval is unreachable when evidence fails. The deploy
script receives the same digest map and renders the API (including migration
init container and expiry CronJob), Grader, Web and LanguageTool as exact
`repository@sha256:...` references rather than SHA tags.

## Safety and scope

- The release SHA is still the successful CI `workflow_run.head_sha`.
- The deployment's superseded-revision guards and production credentials do not
  change.
- The evidence manifest contains only the source SHA and SHA-256 image
  digests; it contains no registry credentials, URLs, payloads, or diagnostics.
- Pull-request runs have no published candidate images, so they remain
  observational and omit the candidate-image manifest.
- Update the verification and production-CD documentation to describe this
  actual gate and remove the stale OIDC-browser limitation because Issue #31 is
  closed.

## Verification

Source-level workflow tests prove the callable interface, SHA/digest hand-off,
and that deployment requires evidence.  The focused workflow tests and docs
integrity check run locally.  After merge, trigger the protected main release
path and retain the successful evidence artifact/run URL before closing #122.
