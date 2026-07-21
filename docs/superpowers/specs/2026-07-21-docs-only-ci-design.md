# Docs-Only CI Design

## Goal

Avoid running the expensive CI jobs for pull requests that change documentation only, without
leaving required GitHub checks pending.

## Decision

Keep the existing `CI` workflow trigger unchanged. Add a lightweight `changes` job that uses the
maintained `dorny/paths-filter@v4` action to publish whether a pull request contains a non-document
file. The workflow grants that job `pull-requests: read`, which the action needs to list changed
files. Its `non_docs` filter uses `predicate-quantifier: every` so a changed file must match `**`
and must not match either documentation exclusion. Each existing expensive job depends on `changes`
and runs when either:

- the event is not a pull request; or
- the pull request includes at least one file outside `docs/**` and outside `**/*.md`.

For a docs-only pull request, the expensive jobs are skipped at the job level. GitHub records
skipped jobs as successful, so required checks remain satisfiable. The `changes` job remains the
only job that executes.

## Scope

- Documentation files: all files under `docs/**` and Markdown files anywhere in the repository.
- Non-documentation files: every other path, including `.github/**`, dependency manifests, Docker
  files, application code, tests, and configuration.
- `push` to `main` and `workflow_dispatch`: always run the full workflow, regardless of paths.

## Alternatives Considered

1. Workflow-level `paths-ignore`: rejected because a skipped workflow can leave its required
   checks pending and block a pull request.
2. Separate documentation workflow: rejected because it duplicates check naming and branch
   protection maintenance.
3. A job-level filter in the existing workflow: selected because it preserves the current workflow
   and check names while avoiding heavy work for documentation-only changes.

## Verification

Add a focused pytest test that reads `.github/workflows/ci.yml` and asserts that the `changes` job,
the non-documentation filter, and each heavy job's dependency and conditional execution rule are
present. Run that test first, then run the full API suite and Python CI-equivalent formatting and
lint checks after implementation.
