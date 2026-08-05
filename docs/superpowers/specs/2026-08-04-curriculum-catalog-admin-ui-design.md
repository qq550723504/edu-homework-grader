# Curriculum Catalog Administration UI Design

**Date:** 2026-08-04  
**Scope:** Web administration for the existing governed curriculum catalogue.  
**Related design:** `2026-07-21-curriculum-ops-import-design.md`

## Purpose

The API already supports governed curriculum imports, independent review, activation,
export, and retirement, but the web application has no curriculum administration
surface. This slice gives authorized curriculum administrators a complete browser
workflow without allowing teachers to write catalogue data or bypass the existing
state machine.

## Chosen Approach

Build an import-first admin console that reuses the existing curriculum API and data
model. The first release will not provide unrestricted inline editing of active
objectives. JSON and CSV remain the canonical authoring formats, because they support
bulk changes, deterministic dry-runs, reproducible review, and export/re-import.

The console has three areas:

1. **Catalogue overview:** active and non-active profiles, version, source metadata,
   objective counts, and lifecycle status.
2. **Import workspace:** upload or paste JSON/CSV, select the format, run dry-run,
   review additions/updates/problems, then create a draft import.
3. **Import review:** inspect the batch summary and row-level issues, submit for
   review, approve or retire, activate approved batches, export active profiles, and
   view an explicit retirement-impact result.

## API and Data Flow

The browser uses same-origin BFF routes under `/api/core/v1/admin/curriculum`.
The API remains the source of truth and owns validation, fingerprints, transactions,
authorization, lifecycle transitions, and audit events.

The UI requires read endpoints for administrator-visible data that the current API
does not expose yet:

- list profiles with any lifecycle status;
- list import batches with filters and pagination;
- read one import batch with summary and issues.

Existing write endpoints remain authoritative:

```text
JSON/CSV -> dry-run -> create draft -> submit review -> independent review -> activate
```

The UI must display the returned catalogue fingerprint and send that exact fingerprint
when creating the draft. A stale fingerprint or invalid lifecycle transition is shown
as a recoverable conflict requiring refresh, never silently retried with changed data.

## Authorization and Safety

The page is visible only to configured curriculum administrators. The backend remains
the final authorization boundary. Teachers can continue reading active catalogues but
cannot see draft batches or invoke administration actions.

The UI must:

- disable actions that do not match the current lifecycle state;
- show importer and reviewer identities where returned by the API;
- prevent the importer from approving or activating their own batch;
- distinguish validation errors, stale-catalogue conflicts, authorization failures,
  and transient network errors;
- require an explicit confirmation before activation or profile retirement;
- never expose source documents, credentials, student data, or copied curriculum text
  beyond the existing API payloads.

## UX and Routing

Add an admin curriculum entry point beneath the existing admin area:

- `/admin/curriculum` — catalogue overview and import history;
- `/admin/curriculum/import` — import and dry-run workspace;
- `/admin/curriculum/imports/:batchId` — batch detail and lifecycle actions;
- `/admin/curriculum/profiles/:profileCode` — active profile detail and export.

The import workspace is intentionally step-based: source document, dry-run result,
draft creation, and handoff to review. A dry-run result must remain visible after
creation so the administrator can compare what was analyzed with what was submitted.
Large issue lists use pagination or collapsible groups; the page must not render the
entire catalogue into one unbounded form.

## Testing and Acceptance

Frontend tests cover route protection, format selection, dry-run rendering, stale
fingerprint recovery, lifecycle action availability, and error mapping. API tests
cover the new administrator read endpoints, filtering/pagination, tenant isolation,
and authorization. Browser E2E covers:

1. an administrator imports a valid JSON document and sees the dry-run diff;
2. the importer cannot review or activate their own batch;
3. a second administrator reviews and activates the batch;
4. a teacher can see the newly active objective in AI generation but cannot access
   the admin console;
5. a stale dry-run is rejected and refreshes without applying data.

Inline objective editing, spreadsheet-style bulk editing, curriculum-source crawling,
and downstream generation-task impact analysis remain out of scope for this release.
