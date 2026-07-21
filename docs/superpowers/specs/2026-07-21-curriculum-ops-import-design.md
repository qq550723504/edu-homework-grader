# Curriculum Ops Import Design

**Issue:** #38  
**Date:** 2026-07-21  
**Scope:** Backend curriculum import, governance, review, export, and operational documentation. The teacher workbench UI is explicitly out of scope for this slice.

## Purpose

#37 established a governed curriculum catalogue. This slice turns that foundation into an operational workflow for authorized, manually curated curriculum data. It must accept copyright-safe metadata and objective summaries, make proposed changes reviewable, and preserve active material while a replacement is evaluated.

The workflow uses separation of duties: the administrator who imports a batch cannot review or activate that batch. Existing teacher-facing catalogue reads remain limited to active material.

## Chosen Approach

JSON and CSV are decoded into one `ImportDocument` domain model. JSON is the canonical nested representation. CSV is a deliberately narrow flat representation for objectives, with profile/source metadata supplied once and prerequisite objective codes represented as a delimiter-separated field. Both formats pass through the same parser, validation, diffing, and write orchestration.

This reuses FastAPI/Pydantic for request parsing and JSON Schema publication, Python's standard `csv` module for RFC-style CSV handling, and the existing SQLAlchemy transaction/audit infrastructure. No additional import framework is introduced.

## State Model

The persisted status spelling remains `draft`, `in_review`, `active`, and `retired`, matching #37. API documentation calls `in_review` "under review" where useful, but does not introduce a second persisted spelling.

An import follows this sequence:

```text
CSV or JSON
  -> normalized ImportDocument
  -> validation and deterministic diff
  -> dry-run report (no curriculum data write)
  -> transactional formal import (draft candidate)
  -> different administrator submits/reviews
  -> atomic activation or retirement
```

Dry-run returns a `catalogue_fingerprint` derived from the relevant current catalogue state. A formal import supplies that fingerprint. The service locks the affected profile, recomputes the fingerprint, and rejects a changed baseline with `409`; it never silently applies a result different from the approved dry-run. A formal import runs in one database transaction; any error rolls back every course-data change.

Formal import creates a durable import-batch record and draft candidates. The report is idempotent by normalized content digest: submitting identical active content returns the prior result without duplicating objectives or revisions. A changed objective body or its generation constraints creates the next immutable objective revision and leaves the active revision available until the new revision is activated.

## Data Model

The existing `CurriculumSourceRecord`, `CurriculumProfile`, `CurriculumGradeMapping`, `CurriculumObjective`, `CurriculumObjectiveRevision`, and `CurriculumPrerequisite` stay the course-data authority. The migration adds only operational and governance data needed by this workflow:

- source metadata: `license`, `document_number`, and `curated_at`;
- revision provenance: `created_by_user_id` and `change_summary`;
- `CurriculumImportBatch`: normalized-document digest, baseline fingerprint, input format, lifecycle status, submitted/reviewed/activated actors and timestamps, and summary counts;
- `CurriculumImportIssue`: batch, source location (JSON pointer or CSV row/column), stable error code, category, and human-readable message.

No textbook pages, long copied source content, answers, student data, or credentials are stored in import reports or audit metadata. Objectives remain concise curated summaries with a source locator.

The import document contains:

- one profile (`code`, name, jurisdiction, version label);
- source metadata (issuer, title, canonical URL, document number, license, curation date, optional dates/notes);
- grade mappings (`internal_level`, external label, position, note);
- objectives (`code`, grade level, subject, domain, optional unit/knowledge point, text, source locator, allowed question types, difficulty range, activity type, change summary);
- prerequisite edges expressed by objective codes.

Prerequisites are resolved only after all objective rows have been normalized. They always link to the candidate revisions created by the batch, avoiding UUIDs in files and preventing a changed objective from mutating historical prerequisite records.

## Validation and Diffing

The shared validator reports all detectable issues, not merely the first. It checks schema/length limits, required source and license fields, known internal levels, duplicate codes, duplicate edges, missing objective references, self references, cycles, question-type policy compatibility, activity type, difficulty range, and current administrator authority.

The diff classifies each source item as `add`, `update`, `unchanged`, `conflict`, or `missing_reference`. A profile cannot be activated when any blocking issue exists. Activation reruns the integrity checks under the same transaction so an otherwise valid draft cannot become invalid while waiting for review.

For an empty catalogue, a valid minimal import produces a draft profile, mappings, objectives, revisions, and prerequisites. Its importer submits it for review; a different administrator reviews and activates the batch, which atomically exposes the profile/objectives/revisions. For an existing active profile, only proposed new objective revisions are activated; prior active revisions are retired by the existing revision-activation invariant.

## API Contract

All operational endpoints are under `/v1/admin/curriculum` and retain `require_curriculum_admin()` authorization.

| Endpoint | Purpose |
| --- | --- |
| `POST /imports/dry-run` | Parse, validate, diff, and return counts/issues/fingerprint without course-data writes. |
| `POST /imports` | Apply the same validated document transactionally with a supplied fingerprint; returns import batch. |
| `GET /imports/{batch_id}` | Return batch lifecycle, summary, and row-level issues. |
| `POST /imports/{batch_id}/submit-review` | Move an error-free draft batch to `in_review`. |
| `POST /imports/{batch_id}/review` | Record the independent reviewer and decision. |
| `POST /imports/{batch_id}/activate` | Atomically activate a reviewed batch; reviewer must differ from importer. |
| `POST /profiles/{profile_id}/retire` | Retire the profile after an impact check. |
| `GET /profiles/{profile_id}/retirement-impact` | Return known downstream references and a completeness marker. |
| `GET /profiles/{profile_code}/export` | Export the active profile as canonical re-importable JSON. |
| `GET /import-schema` | Publish the JSON Schema and CSV column contract. |

The current repository has no objective foreign key from prompt templates or generation tasks. Therefore the retirement-impact endpoint initially returns an empty reference list with `coverage: "curriculum_only"`; this is explicit rather than implying no future impact. #39 or its generation-domain work can add reference collectors without changing the endpoint shape.

## Audit, Authorization, and Error Handling

Each accepted operation appends to the existing tamper-evident audit chain: dry-run requested, import created, review submitted, review decided, activation, export, and retirement. Audit metadata contains IDs, digests, counts, lifecycle status, and error-code summaries only.

The configured global curriculum-administrator allowlist remains the sole write permission. Non-admins and administrators outside that allowlist receive the existing non-disclosing authorization response. Teachers retain readonly access to active curriculum only. Cross-tenant principals cannot write or read operational batch details.

Validation errors use stable machine-readable codes and include either a JSON pointer or a CSV line/column. Conflicting baseline fingerprints and invalid lifecycle transitions return `409`; malformed documents and rule violations return `422`; missing resources return `404` under the existing non-disclosing policy.

## Documentation and Examples

The repository will include a minimal copyright-safe JSON file, a matching CSV file, and a protocol guide. Examples contain invented concise learning objectives and source metadata; they do not reproduce textbook content. The guide documents required columns, the status lifecycle, fingerprint handling, CSV escaping, error locations, and the two-person review rule.

## Verification

Automated API/service/migration tests cover:

1. empty-database minimal JSON and CSV import through independent review and activation;
2. repeat import idempotency;
3. changed objective creation of a new revision while the prior active revision remains stable until activation;
4. circular dependency, unknown grade, invalid question type, and incomplete source/license rejection;
5. dry-run versus formal-import consistency and stale-fingerprint conflict handling;
6. transaction rollback, row location reporting, cross-tenant/unauthorized access rejection, and audit-chain events;
7. export re-importability and retirement-impact contract.

The targeted API suite and project quality gates are run before the implementation branch is proposed for merge.
