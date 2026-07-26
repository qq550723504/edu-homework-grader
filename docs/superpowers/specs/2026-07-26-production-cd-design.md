# Production CD design

## Goal

Make production releases routine and auditable: after a pull request is merged to
`main`, the repository should build immutable images, require one explicit
production approval, deploy the approved revision to Kubernetes, verify the
release, and restore the previous revision if the release cannot become healthy.

This is a deliberately small CD layer built from GitHub Actions, GitHub
Environments, Kubernetes and Kustomize. It does not introduce Argo CD or another
in-cluster control plane in this iteration.

## Current gap

`publish-images.yml` already publishes SHA-tagged API, Grader, Web and
LanguageTool images after a `main` push. The production manifests use placeholder
image tags and there is no workflow that supplies the published SHA to Kubernetes,
waits for workload readiness, records the result, or gives an operator a safe
rollback command. Release therefore depends on manual image selection and
`kubectl` work.

## Release flow

```text
PR checks pass and PR merges to main
  -> CI runs against the merged main revision
  -> release workflow builds and publishes four immutable SHA images
  -> GitHub production Environment waits for one approver
  -> deploy script renders the production Kustomize base with that exact SHA
  -> Kubernetes apply, rollout checks, API readiness and public HTTPS check
  -> release summary and GitHub Environment history record the outcome
  -> on failure, reapply the captured previous workload images and verify rollback
```

The release workflow must only deploy the exact SHA that completed the successful
`main` CI run. It checks out that SHA explicitly; it must not use the runner's
default checkout or a mutable image tag.

For consecutive merges, production deployments are serialized. Before applying,
the workflow checks whether the target SHA is still the current `main` tip. A
superseded queued release exits without modifying the cluster, so an older
approval cannot deploy stale code after a newer merge.

## Components

### CI and image publication

`ci.yml` runs its full validation suite for pull requests and pushes to `main`.
The release workflow starts only after that `main` CI run succeeds. It publishes
the existing four GHCR images using the successful CI run's head SHA. A
documentation-only merge may finish CI but skips image publication and deployment;
infra, application, workflow and manifest changes remain release candidates.

### Production approval and credentials

The deploy job uses a GitHub Environment named `production`. That environment has
required reviewers and stores the Kubernetes credential as an environment secret,
not a repository secret. Approval is therefore the only routine human release
action.

The credential belongs to a `github-production-deployer` Kubernetes ServiceAccount
bound to a namespace-scoped Role in `edu-homework-grader`. Its permissions are
limited to the release resources it reads or applies (Deployments, StatefulSets,
CronJobs, ConfigMaps, Services, Ingresses and API Service endpoints) and exclude
Secrets, Pods, Pod exec/attach/port-forward, cluster-scoped resources and other
namespaces. A one-time bootstrap command can write the credential only to the
fixed repository `qq550723504/edu-homework-grader` and pipes its kubeconfig
directly into that repository's GitHub Environment secret without writing the
credential to disk or console output. Before upload it validates that the
TokenRequest lifetime meets the documented minimum; a shorter cluster-issued token
fails closed instead of creating a deployment credential that will unexpectedly
expire.

### Declarative deployment and verification

`scripts/k8s/deploy-production.ps1` accepts a validated, 40-character Git SHA.
On the ephemeral GitHub runner it creates a temporary Kustomize release overlay
that excludes the cluster-scoped namespace bootstrap and pins the API, Grader, Web,
LanguageTool and API CronJob images to the corresponding GHCR SHA tags. It then
server-side applies the rendered namespace-scoped production manifests. The
repository checkout is never committed with a deployment-specific image tag.

Before applying, the script captures the currently running images for every
release-managed workload. It waits for each Deployment rollout, verifies that the
API Service has ready endpoints (whose Deployment readiness probe calls `/ready`),
and checks `https://edu.getkr.com/` from the runner. It writes a redacted GitHub step summary containing the target SHA,
previous images, timestamps and only pass/fail health results.

If apply, rollout or either health check fails, the script reapplies a temporary
overlay built from the captured images and verifies the rollback rollouts. A
rollback failure is reported as a separate, high-severity workflow failure; it is
never hidden by the original deployment failure.

### Manual rollback

`rollback-production.yml` is a `workflow_dispatch` workflow with one required
`image_sha` input. It validates the SHA, uses the same `production` Environment
approval and calls the same deployment script. It first verifies that all four
GHCR images for that SHA exist. This makes rollback a reviewed, auditable action
instead of a manual cluster edit.

## Failure handling and safety

- A failed CI run cannot publish or deploy images.
- A failed image build cannot reach the production approval job.
- A malformed, missing or superseded SHA exits before any Kubernetes mutation.
- The deploy credential cannot read or change application Secrets.
- Only immutable SHA image references are accepted; `latest`, tags and branch
  names are rejected.
- Deployment jobs do not run concurrently, preventing interleaved rollout and
  rollback operations.
- The old images are captured before the first apply and are used for automatic
  rollback; no inference from a mutable registry tag is allowed.

## Verification

The implementation adds contract tests for workflow triggers, CI-success gating,
production Environment protection, SHA-only image construction, serialized
deployment, redacted summaries and rollback input validation. The deployment
script has command-boundary tests with a fake `kubectl` that prove: target images
are applied, rollout and health failures select the captured previous images, and
Secrets are neither queried nor printed.

CI continues to run the existing test, build, Compose and browser acceptance
suites. A manual staging-like dry run renders the Kustomize overlay and validates
the namespace-scoped RBAC. The first production release is monitored through the
workflow summary and the Kubernetes rollout history before treating the manual
process as retired.

## Out of scope

- Argo CD, Flux or another continuously running GitOps controller.
- Automatic database backup, restore or Secret rotation changes.
- Canary or blue/green traffic splitting.
- Automatic rollback based on post-release business metrics rather than rollout
  and health-check failures.

Those can be added later without changing the release SHA contract or the
GitHub-Environment approval boundary defined here.
