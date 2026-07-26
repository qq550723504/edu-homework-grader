# E2E generator Python-path repair

## Scope

Repair the E2E API launch environment only. No web UI, API route, or generator contract behavior was changed.

## Root cause

`apps/web/e2e/start-e2e-api.mjs` constructed `PYTHONPATH` from the API, grader, and processor-policy source directories, but omitted `services/generator/src`. The E2E API router imports `edu_generator.contracts.GeneratedCandidate`; consequently Python could resolve an installed, stale `edu_generator` package instead of this checkout's source.

The source contract declares `verification_assertions`, while the running E2E API's OpenAPI schema did not. That directly explained the observed `422 extra_forbidden` revision-request symptom.

## TDD evidence

1. Added a runtime assertion to `apps/web/e2e/e2e-api-supervisor.test.mjs`. It starts the real launcher and API, reads `/openapi.json`, and requires `GeneratedCandidate.properties.verification_assertions` to exist. This exercises the launcher-to-supervisor-to-Python environment propagation rather than only inspecting launcher source text.
2. Red run, before the production change:

   ```text
   node --test e2e/e2e-api-supervisor.test.mjs
   ✖ polluted parent identity environment cannot change the real E2E identity
   AssertionError: false !== true
   ```

   The assertion saw that the spawned E2E API OpenAPI schema lacked the field.
3. Minimal production change: inserted `resolve(repositoryRoot, 'services/generator/src')` into the launcher's `pythonPath` list.
4. Green run, after the change:

   ```text
   node --test e2e/e2e-api-supervisor.test.mjs
   3 passed, 0 failed
   ```

## End-to-end verification

```text
npx playwright test e2e/teacher-ai-review.spec.ts --project=chromium
2 passed (26.3s)
```

Both focused browser workflows passed:

- G7 M1 revision plus atomic M1/M2 acceptance; this verifies the original revision request now accepts the current source contract.
- G8 E4 regeneration; this also passed, confirming the prior 409 no longer reproduces under the corrected E2E runtime. The common stale-generator import was therefore sufficient for both observed browser failures; no additional speculative change was made.

## Self-review

- `git diff --check` produced no whitespace errors.
- Diff is restricted to the E2E launcher, its runtime supervisor test, and this report.
- The new path uses the existing `resolve(...)/delimiter` pattern and preserves all inherited-environment filtering and identity controls.
