# Issue 19 Production Security and Consent Fail-Closed Design

## Goal

Make production configuration fail before the API accepts traffic, keep processor destinations within the reviewed internal boundary, and deny student processing when guardian-consent state is missing or not explicitly allowed.

## Boundaries

The Core API validates only configuration it consumes: its audit key, database URL, OIDC issuer, and processor allowlist. Keycloak bootstrap credentials remain deployment concerns because the API never receives them. Kubernetes produces those credentials with a CSPRNG and keeps them in a runtime Secret; the production Realm remains free of development `pilot-*` accounts.

## Configuration and readiness

`Settings` remains the startup gate. In production it rejects the development audit key, short audit keys, development database credentials, local or non-HTTPS OIDC issuers, empty/wildcard processor host lists, and any processor host outside the reviewed internal set. No secret is emitted in validation errors or startup logging.

`/ready` continues to represent the API's traffic-readiness: configuration has already passed because the process started, and the endpoint verifies the database. Its response exposes component status only, never configuration values or credentials.

## Processor boundary

The currently deployed processors are the in-cluster `grader` and `languagetool` services. Production configuration may list only those names. A future external processor requires an explicit source change to the reviewed set and an entry in the data inventory before its hostname can be configured. Development may retain localhost for local integration tests.

## Guardian-consent behavior

Only explicit `NOT_REQUIRED` and `GRANTED` records permit student processing. Missing, pending, withdrawn, rejected, and contradictory legacy records return the stable `403 guardian consent required` response before assignment, submission, appeal, or grader work begins. A missing record additionally writes a structured warning with the event classification only; it never includes a student UUID, school identifier, answer, or credential.

Roster import and teacher creation create consent records atomically. The existing integrity report/repair command remains the migration and historical-data mechanism: it reports gaps, and its explicit repair mode creates only `PENDING` records plus audit evidence.

## Deployment controls

The production Secret generator must use random values, validate its HTTPS OIDC issuer before Kubernetes mutation, and avoid outputting secret-bearing data. Tests assert that the generator and rendered deployment configuration contain no development password, no emitted secret values, and no production Realm development accounts.

## Test strategy

Add focused tests before each behavior change:

- production settings reject unreviewed external processor hosts while development keeps local integration support;
- `/ready` reports configuration readiness without secrets;
- missing guardian consent blocks the route and creates a non-identifying warning;
- secret-generation and production realm checks reject development configuration.

Run focused API and deployment-script tests first, then all Python tests, formatting/lint, Compose rendering, and migration upgrade/downgrade verification where the required local services are available.
