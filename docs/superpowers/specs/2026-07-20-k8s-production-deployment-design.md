# Kubernetes Production Deployment Design

## Goal

Deploy edu-homework-grader to the current Kubernetes cluster at `https://edu.getkr.com`, inject production settings through Kubernetes Secrets, and make secret rotation plus recovery operationally testable.

## Existing cluster constraints

- The active context is `default`; the control plane address is `156.239.44.3`.
- Traefik is the ingress class, `letsencrypt-prod` is Ready, and `local-path` is the default StorageClass.
- Existing workloads use native Kubernetes Secrets through `envFrom`; no External Secrets, Vault, or Secrets Store CSI CRD is installed.
- The repository is public, so production images will be published to `ghcr.io/qq550723504` rather than relying on an unconfigured Docker Hub account.

## Architecture

Create an isolated `edu-homework-grader` namespace with PostgreSQL, Redis, Keycloak, LanguageTool, Grader, Core API, and Web workloads. PostgreSQL uses a `local-path` PVC and Redis requires a generated password; all sensitive values are created by a local `kubectl create secret` command and are never placed in Git.

The public entry point is one Traefik Ingress for `edu.getkr.com`, annotated with `letsencrypt-prod`. Web serves `/`; API is exposed only within the namespace and receives the OIDC issuer, database URL, Redis URL, audit HMAC key, and permitted processor origins from `edu-grader-runtime` Secret. The Keycloak hostname uses the same TLS host so OIDC discovery and callback URLs remain HTTPS in production.

The production Keycloak import is generated from the development Realm by removing all `pilot-*` users, replacing localhost redirect URIs with `https://edu.getkr.com/*`, and setting the exact HTTPS web origin. The generated Realm is reviewed as a non-secret artifact before being mounted into Keycloak.

Images are published by a dedicated GitHub Actions workflow after a protected `main` build succeeds. The deployment manifest pins image digests or immutable commit tags; it never uses `latest`.

## Secret lifecycle

`scripts/k8s/create-prod-secrets.ps1` generates high-entropy values with the platform CSPRNG, submits them directly to the Kubernetes API, and records no secret values. The rotation command creates a replacement Secret, restarts only dependent workloads, waits for `/ready`, and deletes the old Secret only after readiness succeeds.

The recovery drill restores PostgreSQL from a named `pg_dump` backup into a fresh database, restarts API and Grader, verifies `/ready`, then checks that a consent-gated request remains blocked for a missing/withdrawn consent record. It emits only resource names, timestamps, and command exit status.

## Acceptance evidence

1. `kubectl apply --server-side --dry-run=server` accepts all manifests.
2. cert-manager issues a Ready certificate for `edu.getkr.com`.
3. Every workload becomes Ready and API `/ready` returns 200 over the cluster service endpoint.
4. A secret rotation restarts API/Keycloak without exposing values and restores readiness.
5. The backup/restore drill produces a fresh PostgreSQL pod, restores the dump, and preserves API readiness and guardian-consent fail-closed behavior.

## Explicit non-goals

- Do not introduce a second secret manager while the cluster has no corresponding operator.
- Do not commit secret values, database dumps, `.env` files, or registry credentials.
- Do not deploy until immutable GHCR images have been built and their references are recorded in the deployment manifest.
