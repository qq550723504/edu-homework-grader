# AI Candidate Question Verification — M1 Foundation Design

**Issue:** #40  
**Status:** Approved design  
**Scope:** First implementation slice only

## Goal

Add an explainable, persistent verification pipeline for AI-generated candidate questions. The pipeline
reads `GeneratedQuestionDraft` rows and records immutable results; it never creates, edits, publishes, or
otherwise transitions a `QuestionVersion`.

The first slice establishes the common persistence and API contract for every supported question type, and
implements deterministic gates for M1 and E1. It deliberately leaves M2, E2–E4, LanguageTool, semantic
duplicate detection, and golden-set calibration to later slices.

## Boundaries

- Core API owns authorization, persistence, audit, and read/trigger endpoints.
- A verification service owns deterministic checks and stable findings. It may use platform policy schemas and
  the existing deterministic Grader interface, but it cannot call a generative model.
- A run reads one candidate draft at a time. It stores only sanitized evidence and bounded excerpts; it never
  logs a full model request or response.
- A `blocked` result prevents later acceptance/import into the question bank. A `warning` must be explicitly
  acknowledged by the future teacher-review flow. This slice records the state; #41 enforces the UI workflow.
- Any validator exception creates a stable `validator_unavailable` blocked finding. Failure never defaults to pass.

## Data Model

`generation_validation_runs` contains one immutable execution for a draft:

- draft ID, generation job ID, validator version, ruleset version, status (`passed`, `warning`, `blocked`),
  started/finished times, and an aggregate feature summary;
- an ordinal unique per draft so re-runs append history rather than overwrite it.

`validation_findings` contains zero or more ordered findings for a run:

- stable `code`, `severity` (`warning` or `blocked`), machine-safe `evidence_json`, and a bounded teacher-facing
  remediation string;
- uniqueness per `(run_id, code, subject_ref)` to make repeated checks stable without discarding distinct evidence.

Neither table has a foreign key to `QuestionVersion`. Draft validation results remain candidate-only data.

## Verification Flow

1. Load the candidate draft and its generation job. Verify the referenced curriculum revision remains active and
   the candidate type is still allowed by that revision.
2. Validate the candidate's platform policy JSON with `validate_policy`.
3. Apply generic deterministic checks:
   - non-empty, bounded prompt and explanation;
   - normalized content hash duplicate comparison against prior candidate drafts in the same tenant;
   - a small, versioned prohibited-topic lexicon for explicit adult, self-harm, and violence terms;
   - requested type, curriculum revision, and difficulty range consistency.
4. Apply type-specific checks:
   - **M1:** finite numeric `expected`, non-negative finite tolerance, and a deterministic Grader probe using the
     expected answer. A mismatch or unavailable Grader blocks the candidate.
   - **E1:** non-empty, distinct accepted answers after whitespace/case normalization, plus prompt and answer length
     limits appropriate to the selected curriculum grade.
5. Persist all findings and derive the run status: any blocked finding → `blocked`; otherwise any warning →
   `warning`; otherwise `passed`.

The normalizer is intentionally exact/format based in this slice. Semantic similarity needs a separately calibrated
model and does not belong in the safety-critical first release.

## API Contract

Teacher or admin users can:

- `POST /v1/ai-generated-questions/{draft_id}/validation-runs` — execute a new immutable run;
- `GET /v1/ai-generated-questions/{draft_id}/validation-runs` — page through historical runs;
- `GET /v1/ai-question-validation-runs/{run_id}` — retrieve a run and its ordered findings.

All reads are tenant-scoped. Responses contain status, versions, stable finding codes, severity, sanitized evidence,
and remediation; they contain no provider credential, raw provider response, or learner identity.

## Stable First-Slice Findings

| Code | Severity | Meaning |
| --- | --- | --- |
| `curriculum_revision_inactive` | blocked | Referenced objective/profile/revision is no longer active. |
| `question_type_not_allowed` | blocked | Candidate type is outside the objective's allowed type list. |
| `policy_schema_invalid` | blocked | `rule_json` fails the platform-owned policy schema. |
| `prompt_or_explanation_invalid` | blocked | Required text is empty or exceeds the platform bound. |
| `duplicate_candidate_content` | warning | Exact normalized content matches a prior tenant candidate. |
| `unsafe_minor_content` | blocked | Versioned deterministic safety lexicon matched. |
| `m1_answer_invalid` | blocked | Expected number or tolerance is non-finite/invalid. |
| `m1_grader_probe_failed` | blocked | Existing deterministic Grader does not accept the expected answer. |
| `e1_answers_invalid` | blocked | Accepted answers are empty or normalize to duplicates. |
| `grade_text_complexity_warning` | warning | M1/E1 deterministic length or numeric range exceeds grade profile bounds. |
| `validator_unavailable` | blocked | A dependency or validator failed unexpectedly. |

## Testing and Delivery

The implementation begins test-first. It will cover blocked M1 errors, malformed E1 answer sets, duplicate
candidate warnings, forbidden-content blocks, inactive curriculum blocks, Grader failures, and a thrown validator.
Tests also assert that a failed run does not create a `QuestionVersion` and that a re-run appends rather than mutates
history. The API tests will cover tenant isolation and stable response codes.

## Deferred Work

M2 AST/normalizer probes, E2–E4 and LanguageTool checks, semantic duplicate detection, profile-configured advanced
grade thresholds, generated golden cases, acceptance enforcement, batch validation, and evaluation metrics stay in
later #40/#41/#42 slices. This avoids presenting heuristics or uncalibrated model output as a safety gate.
