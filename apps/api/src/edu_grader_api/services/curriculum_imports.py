from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    CurriculumActivityType,
    CurriculumGradeMapping,
    CurriculumImportBatch,
    CurriculumImportStatus,
    CurriculumObjective,
    CurriculumObjectiveRevision,
    CurriculumProfile,
    CurriculumProfileStatus,
    CurriculumPrerequisite,
    CurriculumRevisionStatus,
    CurriculumSourceRecord,
    User,
    utc_now,
)
from .curriculum import (
    CurriculumValidationError,
    activate_objective_revision,
    create_objective_revision,
    create_prerequisite,
    validate_revision_payload,
)


class ImportProfile(BaseModel):
    code: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=200)
    jurisdiction: str = Field(min_length=1, max_length=100)
    version_label: str = Field(min_length=1, max_length=100)


class ImportSource(BaseModel):
    issuer: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    canonical_url: str = Field(min_length=1, max_length=2_000)
    document_number: str = Field(min_length=1, max_length=100)
    license: str = Field(min_length=1, max_length=200)
    curated_at: date


class ImportGradeMapping(BaseModel):
    internal_level: str = Field(min_length=1, max_length=10)
    external_label: str = Field(min_length=1, max_length=200)
    position: int = Field(ge=0)


class ImportObjective(BaseModel):
    code: str = Field(min_length=1, max_length=150)
    grade_level: str = Field(min_length=1, max_length=10)
    subject: str = Field(min_length=1, max_length=100)
    domain: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=2_000)
    source_locator: str = Field(min_length=1, max_length=500)
    allowed_question_types: list[str] = Field(min_length=1)
    difficulty_min: float = Field(ge=0, le=1)
    difficulty_max: float = Field(ge=0, le=1)
    activity_type: CurriculumActivityType
    change_summary: str = Field(min_length=1, max_length=1_000)


class ImportPrerequisite(BaseModel):
    objective_code: str = Field(min_length=1, max_length=150)
    prerequisite_code: str = Field(min_length=1, max_length=150)


class ImportDocument(BaseModel):
    profile: ImportProfile
    source: ImportSource
    grade_mappings: list[ImportGradeMapping] = Field(min_length=1)
    objectives: list[ImportObjective] = Field(min_length=1)
    prerequisites: list[ImportPrerequisite]


class ImportProblem(BaseModel):
    code: str
    category: str
    message: str
    path: str | None = None
    row: int | None = None
    column: str | None = None


class ImportAnalysis(BaseModel):
    normalized_digest: str
    catalogue_fingerprint: str
    additions: list[str]
    updates: list[str]
    unchanged: list[str]
    conflicts: list[ImportProblem]
    problems: list[ImportProblem]

    @property
    def can_apply(self) -> bool:
        return not self.conflicts and not self.problems


class ImportValidationError(ValueError):
    """Raised when an invalid import document is submitted for formal application."""


class StaleImportBaselineError(ValueError):
    """Raised when the catalogue changed after a dry-run was generated."""


class ImportLifecycleError(ValueError):
    """Raised when a governed import lifecycle transition is invalid."""


def parse_csv_document(
    csv_text: str,
    *,
    profile: ImportProfile,
    source: ImportSource,
    grade_mappings: list[ImportGradeMapping],
) -> ImportDocument:
    rows = csv.DictReader(io.StringIO(csv_text))
    objectives = []
    for row in rows:
        objectives.append(
            {
                **row,
                "allowed_question_types": _parse_question_types(row["allowed_question_types"]),
                "difficulty_min": float(row["difficulty_min"]),
                "difficulty_max": float(row["difficulty_max"]),
            }
        )
    return ImportDocument(
        profile=profile,
        source=source,
        grade_mappings=grade_mappings,
        objectives=objectives,
        prerequisites=[],
    )


def analyse_import(session: Session, document: ImportDocument) -> ImportAnalysis:
    problems = _validate_document(document)
    return ImportAnalysis(
        normalized_digest=_document_digest(document),
        catalogue_fingerprint=catalogue_fingerprint(session, document.profile.code),
        additions=[objective.code for objective in document.objectives],
        updates=[],
        unchanged=[],
        conflicts=[],
        problems=problems,
    )


def catalogue_fingerprint(session: Session, profile_code: str) -> str:
    profile = session.scalar(
        select(CurriculumProfile).where(CurriculumProfile.code == profile_code)
    )
    if profile is None:
        return _hash_payload({"profile_code": profile_code, "catalogue": None})

    mappings = session.scalars(
        select(CurriculumGradeMapping)
        .where(CurriculumGradeMapping.profile_id == profile.id)
        .order_by(CurriculumGradeMapping.position, CurriculumGradeMapping.internal_level)
    )
    objectives = session.scalars(
        select(CurriculumObjective)
        .where(CurriculumObjective.profile_id == profile.id)
        .order_by(CurriculumObjective.code)
    )
    return _hash_payload(
        {
            "profile": {
                "code": profile.code,
                "status": profile.status.value,
                "version_label": profile.version_label,
            },
            "grade_mappings": [
                {
                    "internal_level": mapping.internal_level,
                    "external_label": mapping.external_label,
                    "position": mapping.position,
                }
                for mapping in mappings
            ],
            "objectives": [
                {
                    "code": objective.code,
                    "status": objective.status.value,
                    "subject": objective.subject,
                    "domain": objective.domain,
                }
                for objective in objectives
            ],
        }
    )


def apply_import(
    session: Session,
    *,
    document: ImportDocument,
    analysis: ImportAnalysis,
    actor: User,
    input_format: str = "json",
) -> CurriculumImportBatch:
    if not analysis.can_apply:
        raise ImportValidationError("cannot apply an import with validation problems")
    if analysis.normalized_digest != _document_digest(document):
        raise ImportValidationError("import document does not match its analysis")

    profile = session.scalar(
        select(CurriculumProfile)
        .where(CurriculumProfile.code == document.profile.code)
        .with_for_update()
    )
    if catalogue_fingerprint(session, document.profile.code) != analysis.catalogue_fingerprint:
        raise StaleImportBaselineError("catalogue changed after dry-run")
    if profile is not None:
        duplicate = session.scalar(
            select(CurriculumImportBatch).where(
                CurriculumImportBatch.profile_id == profile.id,
                CurriculumImportBatch.content_digest == analysis.normalized_digest,
            )
        )
        if duplicate is not None:
            return duplicate
        return _apply_profile_update(
            session,
            profile=profile,
            document=document,
            analysis=analysis,
            actor=actor,
            input_format=input_format,
        )

    source = CurriculumSourceRecord(
        issuer=document.source.issuer,
        title=document.source.title,
        canonical_url=document.source.canonical_url,
        version_label=document.profile.version_label,
        license=document.source.license,
        document_number=document.source.document_number,
        curated_at=document.source.curated_at,
    )
    profile = CurriculumProfile(
        code=document.profile.code,
        name=document.profile.name,
        jurisdiction=document.profile.jurisdiction,
        version_label=document.profile.version_label,
        status=CurriculumProfileStatus.DRAFT,
        source_record=source,
    )
    session.add(profile)
    session.flush()

    mappings = {
        item.internal_level: CurriculumGradeMapping(
            profile=profile,
            internal_level=item.internal_level,
            external_label=item.external_label,
            position=item.position,
        )
        for item in document.grade_mappings
    }
    session.add_all(mappings.values())
    session.flush()

    batch = CurriculumImportBatch(
        profile=profile,
        input_format=input_format,
        content_digest=analysis.normalized_digest,
        baseline_fingerprint=analysis.catalogue_fingerprint,
        status=CurriculumImportStatus.DRAFT,
        submitted_by_user_id=actor.id,
        change_summary=_batch_change_summary(document),
        summary_json={"additions": len(document.objectives), "updates": 0, "unchanged": 0},
    )
    session.add(batch)
    session.flush()

    revisions: dict[str, CurriculumObjectiveRevision] = {}
    for objective_data in document.objectives:
        objective = CurriculumObjective(
            profile=profile,
            grade_mapping=mappings[objective_data.grade_level],
            code=objective_data.code,
            subject=objective_data.subject,
            domain=objective_data.domain,
            status=CurriculumProfileStatus.DRAFT,
        )
        session.add(objective)
        session.flush()
        revision = create_objective_revision(
            session,
            objective=objective,
            revision_number=1,
            text=objective_data.text,
            source_locator=objective_data.source_locator,
            allowed_question_types=objective_data.allowed_question_types,
            difficulty_min=objective_data.difficulty_min,
            difficulty_max=objective_data.difficulty_max,
            activity_type=objective_data.activity_type,
        )
        revision.created_by_user_id = actor.id
        revision.import_batch = batch
        revision.change_summary = objective_data.change_summary
        revisions[objective_data.code] = revision
    session.flush()

    for prerequisite in document.prerequisites:
        create_prerequisite(
            session,
            objective_revision=revisions[prerequisite.objective_code],
            prerequisite_revision=revisions[prerequisite.prerequisite_code],
        )

    return batch


def _apply_profile_update(
    session: Session,
    *,
    profile: CurriculumProfile,
    document: ImportDocument,
    analysis: ImportAnalysis,
    actor: User,
    input_format: str,
) -> CurriculumImportBatch:
    mappings = {
        mapping.internal_level: mapping
        for mapping in session.scalars(
            select(CurriculumGradeMapping).where(CurriculumGradeMapping.profile_id == profile.id)
        )
    }
    for mapping_data in document.grade_mappings:
        mapping = mappings.get(mapping_data.internal_level)
        if mapping is None:
            mapping = CurriculumGradeMapping(
                profile=profile,
                internal_level=mapping_data.internal_level,
                external_label=mapping_data.external_label,
                position=mapping_data.position,
            )
            session.add(mapping)
            mappings[mapping_data.internal_level] = mapping
    session.flush()

    objectives = {
        objective.code: objective
        for objective in session.scalars(
            select(CurriculumObjective).where(CurriculumObjective.profile_id == profile.id)
        )
    }
    additions = 0
    updates = 0
    batch = CurriculumImportBatch(
        profile=profile,
        input_format=input_format,
        content_digest=analysis.normalized_digest,
        baseline_fingerprint=analysis.catalogue_fingerprint,
        status=CurriculumImportStatus.DRAFT,
        submitted_by_user_id=actor.id,
        change_summary=_batch_change_summary(document),
        summary_json={},
    )
    session.add(batch)
    session.flush()

    revisions: dict[str, CurriculumObjectiveRevision] = {}
    for objective_data in document.objectives:
        objective = objectives.get(objective_data.code)
        if objective is None:
            objective = CurriculumObjective(
                profile=profile,
                grade_mapping=mappings[objective_data.grade_level],
                code=objective_data.code,
                subject=objective_data.subject,
                domain=objective_data.domain,
                status=CurriculumProfileStatus.DRAFT,
            )
            session.add(objective)
            session.flush()
            additions += 1
        active_revision = session.scalar(
            select(CurriculumObjectiveRevision)
            .where(
                CurriculumObjectiveRevision.objective_id == objective.id,
                CurriculumObjectiveRevision.status == CurriculumRevisionStatus.ACTIVE,
            )
            .order_by(CurriculumObjectiveRevision.revision_number.desc())
        )
        if active_revision is not None and _revision_matches(active_revision, objective_data):
            revisions[objective_data.code] = active_revision
            continue
        revision_number = (
            session.scalar(
                select(func.max(CurriculumObjectiveRevision.revision_number)).where(
                    CurriculumObjectiveRevision.objective_id == objective.id
                )
            )
            or 0
        ) + 1
        revision = create_objective_revision(
            session,
            objective=objective,
            revision_number=revision_number,
            text=objective_data.text,
            source_locator=objective_data.source_locator,
            allowed_question_types=objective_data.allowed_question_types,
            difficulty_min=objective_data.difficulty_min,
            difficulty_max=objective_data.difficulty_max,
            activity_type=objective_data.activity_type,
        )
        revision.created_by_user_id = actor.id
        revision.import_batch = batch
        revision.change_summary = objective_data.change_summary
        revisions[objective_data.code] = revision
        updates += 1
    session.flush()

    for prerequisite in document.prerequisites:
        objective_revision = revisions[prerequisite.objective_code]
        prerequisite_revision = revisions[prerequisite.prerequisite_code]
        if objective_revision.id != prerequisite_revision.id:
            create_prerequisite(
                session,
                objective_revision=objective_revision,
                prerequisite_revision=prerequisite_revision,
            )
    batch.summary_json = {
        "additions": additions,
        "updates": updates,
        "unchanged": len(document.objectives) - additions - updates,
    }
    session.flush()
    return batch


def submit_import_for_review(
    session: Session, *, batch: CurriculumImportBatch
) -> CurriculumImportBatch:
    if batch.status is not CurriculumImportStatus.DRAFT:
        raise ImportLifecycleError("only draft imports can be submitted for review")
    if batch.issues:
        raise ImportLifecycleError("imports with validation issues cannot be submitted for review")
    batch.status = CurriculumImportStatus.IN_REVIEW
    if batch.profile.status is CurriculumProfileStatus.DRAFT:
        batch.profile.status = CurriculumProfileStatus.IN_REVIEW
    for revision in batch.objective_revisions:
        if revision.objective.status is CurriculumProfileStatus.DRAFT:
            revision.objective.status = CurriculumProfileStatus.IN_REVIEW
        if revision.status is CurriculumRevisionStatus.DRAFT:
            revision.status = CurriculumRevisionStatus.IN_REVIEW
    session.flush()
    return batch


def review_import(
    session: Session,
    *,
    batch: CurriculumImportBatch,
    reviewer: User,
    approve: bool,
) -> CurriculumImportBatch:
    if batch.status is not CurriculumImportStatus.IN_REVIEW:
        raise ImportLifecycleError("only in-review imports can be reviewed")
    if reviewer.id == batch.submitted_by_user_id:
        raise ImportLifecycleError("importer cannot review their own import")
    batch.reviewed_by_user_id = reviewer.id
    batch.reviewed_at = utc_now()
    if not approve:
        batch.status = CurriculumImportStatus.RETIRED
        if batch.profile.status is CurriculumProfileStatus.IN_REVIEW:
            batch.profile.status = CurriculumProfileStatus.RETIRED
        for revision in batch.objective_revisions:
            revision.status = CurriculumRevisionStatus.RETIRED
            if revision.objective.status is CurriculumProfileStatus.IN_REVIEW:
                revision.objective.status = CurriculumProfileStatus.RETIRED
    session.flush()
    return batch


def activate_import(
    session: Session,
    *,
    batch: CurriculumImportBatch,
    actor: User,
) -> CurriculumImportBatch:
    if batch.status is not CurriculumImportStatus.IN_REVIEW:
        raise ImportLifecycleError("only in-review imports can be activated")
    if batch.reviewed_by_user_id != actor.id or actor.id == batch.submitted_by_user_id:
        raise ImportLifecycleError("a different approving reviewer must activate the import")
    if batch.profile.status is CurriculumProfileStatus.IN_REVIEW:
        batch.profile.status = CurriculumProfileStatus.ACTIVE
    for revision in batch.objective_revisions:
        if revision.objective.status is CurriculumProfileStatus.IN_REVIEW:
            revision.objective.status = CurriculumProfileStatus.ACTIVE
    session.flush()
    for revision in batch.objective_revisions:
        activate_objective_revision(session, revision=revision, reviewer_user_id=actor.id)
    batch.status = CurriculumImportStatus.ACTIVE
    batch.activated_by_user_id = actor.id
    batch.activated_at = utc_now()
    session.flush()
    return batch


def export_active_profile(session: Session, *, profile_code: str) -> ImportDocument | None:
    profile = session.scalar(
        select(CurriculumProfile).where(
            CurriculumProfile.code == profile_code,
            CurriculumProfile.status == CurriculumProfileStatus.ACTIVE,
        )
    )
    if profile is None:
        return None
    mappings = list(
        session.scalars(
            select(CurriculumGradeMapping)
            .where(CurriculumGradeMapping.profile_id == profile.id)
            .order_by(CurriculumGradeMapping.position, CurriculumGradeMapping.internal_level)
        )
    )
    rows = list(
        session.execute(
            select(CurriculumObjective, CurriculumObjectiveRevision)
            .join(CurriculumObjectiveRevision)
            .where(
                CurriculumObjective.profile_id == profile.id,
                CurriculumObjective.status == CurriculumProfileStatus.ACTIVE,
                CurriculumObjectiveRevision.status == CurriculumRevisionStatus.ACTIVE,
            )
            .order_by(CurriculumObjective.code)
        )
    )
    revisions = {revision.id: objective.code for objective, revision in rows}
    prerequisites = session.scalars(
        select(CurriculumPrerequisite).where(
            CurriculumPrerequisite.objective_revision_id.in_(revisions),
            CurriculumPrerequisite.prerequisite_revision_id.in_(revisions),
        )
    )
    source = profile.source_record
    return ImportDocument(
        profile=ImportProfile(
            code=profile.code,
            name=profile.name,
            jurisdiction=profile.jurisdiction,
            version_label=profile.version_label,
        ),
        source=ImportSource(
            issuer=source.issuer,
            title=source.title,
            canonical_url=source.canonical_url,
            document_number=source.document_number or "legacy-source",
            license=source.license or "unspecified",
            curated_at=source.curated_at or source.created_at.date(),
        ),
        grade_mappings=[
            ImportGradeMapping(
                internal_level=mapping.internal_level,
                external_label=mapping.external_label,
                position=mapping.position,
            )
            for mapping in mappings
        ],
        objectives=[
            ImportObjective(
                code=objective.code,
                grade_level=objective.grade_mapping.internal_level,
                subject=objective.subject,
                domain=objective.domain,
                text=revision.text,
                source_locator=revision.source_locator,
                allowed_question_types=revision.allowed_question_types,
                difficulty_min=revision.difficulty_min,
                difficulty_max=revision.difficulty_max,
                activity_type=revision.activity_type,
                change_summary=revision.change_summary or "Legacy curated revision",
            )
            for objective, revision in rows
        ],
        prerequisites=[
            ImportPrerequisite(
                objective_code=revisions[prerequisite.objective_revision_id],
                prerequisite_code=revisions[prerequisite.prerequisite_revision_id],
            )
            for prerequisite in prerequisites
        ],
    )


def retirement_impact(profile: CurriculumProfile) -> dict[str, object]:
    return {"profile_id": str(profile.id), "coverage": "curriculum_only", "references": []}


def retire_profile(session: Session, *, profile: CurriculumProfile) -> CurriculumProfile:
    profile.status = CurriculumProfileStatus.RETIRED
    for objective in profile.objectives:
        objective.status = CurriculumProfileStatus.RETIRED
        for revision in objective.revisions:
            if revision.status is not CurriculumRevisionStatus.RETIRED:
                revision.status = CurriculumRevisionStatus.RETIRED
    session.flush()
    return profile


def _parse_question_types(value: str) -> list[str]:
    return [item.strip() for item in value.split("|") if item.strip()]


def _document_digest(document: ImportDocument) -> str:
    return _hash_payload(document.model_dump(mode="json"))


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _batch_change_summary(document: ImportDocument) -> str:
    summaries = sorted({objective.change_summary for objective in document.objectives})
    return "; ".join(summaries)


def _revision_matches(revision: CurriculumObjectiveRevision, objective: ImportObjective) -> bool:
    return (
        revision.text == objective.text
        and revision.source_locator == objective.source_locator
        and revision.allowed_question_types == objective.allowed_question_types
        and revision.difficulty_min == objective.difficulty_min
        and revision.difficulty_max == objective.difficulty_max
        and revision.activity_type is objective.activity_type
    )


def _validate_document(document: ImportDocument) -> list[ImportProblem]:
    problems: list[ImportProblem] = []
    mapped_levels = {mapping.internal_level for mapping in document.grade_mappings}
    for index, objective in enumerate(document.objectives):
        if objective.grade_level not in mapped_levels:
            problems.append(
                ImportProblem(
                    code="unknown_grade",
                    category="validation",
                    message="objective grade level is not mapped by this profile",
                    path=f"/objectives/{index}/grade_level",
                )
            )
        try:
            validate_revision_payload(
                subject=objective.subject,
                internal_level=objective.grade_level,
                allowed_question_types=objective.allowed_question_types,
                difficulty_min=objective.difficulty_min,
                difficulty_max=objective.difficulty_max,
                activity_type=objective.activity_type,
            )
        except CurriculumValidationError as error:
            problems.append(
                ImportProblem(
                    code="invalid_question_type",
                    category="validation",
                    message=str(error),
                    path=f"/objectives/{index}/allowed_question_types/0",
                )
            )
    objective_codes = {objective.code for objective in document.objectives}
    for index, prerequisite in enumerate(document.prerequisites):
        path = f"/prerequisites/{index}"
        if prerequisite.objective_code not in objective_codes:
            problems.append(
                ImportProblem(
                    code="missing_objective_reference",
                    category="validation",
                    message="objective prerequisite reference does not exist",
                    path=path,
                )
            )
        if prerequisite.prerequisite_code not in objective_codes:
            problems.append(
                ImportProblem(
                    code="missing_prerequisite_reference",
                    category="validation",
                    message="prerequisite reference does not exist",
                    path=path,
                )
            )

    for index in _cycle_indexes(document.prerequisites):
        problems.append(
            ImportProblem(
                code="prerequisite_cycle",
                category="validation",
                message="prerequisite cycle detected",
                path=f"/prerequisites/{index}",
            )
        )
    return problems


def _cycle_indexes(prerequisites: list[ImportPrerequisite]) -> set[int]:
    adjacency: dict[str, list[tuple[str, int]]] = {}
    for index, prerequisite in enumerate(prerequisites):
        adjacency.setdefault(prerequisite.objective_code, []).append(
            (prerequisite.prerequisite_code, index)
        )

    visiting: set[str] = set()
    visited: set[str] = set()
    cycle_indexes: set[int] = set()

    def visit(code: str) -> None:
        visiting.add(code)
        for next_code, index in adjacency.get(code, []):
            if next_code in visiting:
                cycle_indexes.add(index)
            elif next_code not in visited:
                visit(next_code)
        visiting.remove(code)
        visited.add(code)

    for code in adjacency:
        if code not in visited:
            visit(code)
    return cycle_indexes
