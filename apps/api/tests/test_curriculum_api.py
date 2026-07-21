from dataclasses import dataclass
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from edu_grader_api.auth import VerifiedIdentity, get_token_verifier
from edu_grader_api.db import Base, get_session
from edu_grader_api.main import app
from edu_grader_api.models import (
    AuditLog,
    CurriculumActivityType,
    CurriculumGradeMapping,
    CurriculumObjective,
    CurriculumObjectiveRevision,
    CurriculumProfile,
    CurriculumProfileStatus,
    CurriculumRevisionStatus,
    CurriculumSourceRecord,
    Role,
    Tenant,
    User,
)
from edu_grader_api.settings import settings


ISSUER = "http://localhost:8080/realms/edu-grader"


@dataclass
class StaticVerifier:
    identities: dict[str, VerifiedIdentity]

    def verify(self, token: str) -> VerifiedIdentity:
        return self.identities[token]


@dataclass
class CurriculumContext:
    client: TestClient
    objective_id: UUID
    active_revision_id: UUID


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


@pytest.fixture
def curriculum_context(session: Session, monkeypatch: pytest.MonkeyPatch) -> CurriculumContext:
    tenant = Tenant(slug="pilot", name="Pilot")
    users = [
        User(
            tenant=tenant,
            role=Role.ADMIN,
            oidc_issuer=ISSUER,
            oidc_subject="admin-subject",
            display_name="Admin",
            work_email="admin@example.test",
        ),
        User(
            tenant=tenant,
            role=Role.TEACHER,
            oidc_issuer=ISSUER,
            oidc_subject="teacher-subject",
            display_name="Teacher",
            work_email="teacher@example.test",
        ),
        User(
            tenant=tenant,
            role=Role.STUDENT,
            oidc_issuer=ISSUER,
            oidc_subject="student-subject",
            school_id="S-001",
            display_name="Student",
        ),
    ]
    source = CurriculumSourceRecord(
        issuer="Ministry of Education",
        title="Curriculum standard",
        canonical_url="https://example.test/curriculum",
        version_label="2022",
    )
    profile = CurriculumProfile(
        code="cn-compulsory-2022",
        name="Compulsory education",
        jurisdiction="CN",
        version_label="2022",
        status=CurriculumProfileStatus.ACTIVE,
        source_record=source,
    )
    mapping = CurriculumGradeMapping(
        profile=profile,
        internal_level="G1",
        external_label="一年级",
        position=1,
    )
    objective = CurriculumObjective(
        profile=profile,
        grade_mapping=mapping,
        code="MATH-G1-NUM-001",
        subject="mathematics",
        domain="number",
        knowledge_point="whole_numbers",
        status=CurriculumProfileStatus.ACTIVE,
    )
    active_revision = CurriculumObjectiveRevision(
        objective=objective,
        revision_number=1,
        text="Use whole numbers in simple situations.",
        source_locator="section 1",
        allowed_question_types=["M1"],
        difficulty_min=0,
        difficulty_max=0.4,
        activity_type=CurriculumActivityType.SCORED_QUESTION,
        status=CurriculumRevisionStatus.ACTIVE,
        reviewed_by_user_id=users[0].id,
    )
    session.add_all([tenant, *users, source, profile, mapping, objective, active_revision])
    session.commit()

    monkeypatch.setattr(settings, "oidc_issuer", ISSUER)
    monkeypatch.setattr(settings, "oidc_tenant_slug", "pilot")
    monkeypatch.setattr(settings, "curriculum_admin_subjects", "admin-subject")
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_token_verifier] = lambda: StaticVerifier(
        {
            "admin-token": VerifiedIdentity(issuer=ISSUER, subject="admin-subject", school_id=None),
            "teacher-token": VerifiedIdentity(
                issuer=ISSUER, subject="teacher-subject", school_id=None
            ),
            "student-token": VerifiedIdentity(
                issuer=ISSUER, subject="student-subject", school_id="S-001"
            ),
        }
    )
    with TestClient(app) as client:
        yield CurriculumContext(
            client=client,
            objective_id=objective.id,
            active_revision_id=active_revision.id,
        )
    app.dependency_overrides.clear()


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_openapi_exposes_curriculum_routes(curriculum_context: CurriculumContext) -> None:
    paths = curriculum_context.client.get("/openapi.json").json()["paths"]

    assert "/v1/curriculum-profiles" in paths
    assert "/v1/curriculum-profiles/{profile_code}/objectives" in paths
    assert "/v1/admin/curriculum/objectives/{objective_id}/revisions" in paths


def test_teacher_reads_active_profiles_and_filtered_objectives(
    curriculum_context: CurriculumContext,
) -> None:
    profiles = curriculum_context.client.get(
        "/v1/curriculum-profiles", headers=headers("teacher-token")
    )
    objectives = curriculum_context.client.get(
        "/v1/curriculum-profiles/cn-compulsory-2022/objectives",
        params={
            "grade_level": "G1",
            "subject": "mathematics",
            "domain": "number",
            "question_type": "M1",
        },
        headers=headers("teacher-token"),
    )

    assert profiles.status_code == 200
    assert profiles.json()["items"] == [
        {
            "code": "cn-compulsory-2022",
            "id": profiles.json()["items"][0]["id"],
            "jurisdiction": "CN",
            "name": "Compulsory education",
            "version_label": "2022",
        }
    ]
    assert objectives.status_code == 200
    assert objectives.json()["items"][0]["revision"]["allowed_question_types"] == ["M1"]


def test_student_cannot_read_curriculum_catalogue(curriculum_context: CurriculumContext) -> None:
    response = curriculum_context.client.get(
        "/v1/curriculum-profiles", headers=headers("student-token")
    )

    assert response.status_code == 404


def test_second_tenant_teacher_reads_the_same_global_catalogue(
    curriculum_context: CurriculumContext, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    second_tenant = Tenant(slug="pilot-2", name="Pilot 2")
    second_teacher = User(
        tenant=second_tenant,
        role=Role.TEACHER,
        oidc_issuer=ISSUER,
        oidc_subject="second-teacher-subject",
        display_name="Second teacher",
        work_email="teacher-2@example.test",
    )
    session.add_all([second_tenant, second_teacher])
    session.commit()
    monkeypatch.setattr(settings, "oidc_tenant_slug", "pilot-2")
    app.dependency_overrides[get_token_verifier] = lambda: StaticVerifier(
        {
            "second-teacher-token": VerifiedIdentity(
                issuer=ISSUER, subject="second-teacher-subject", school_id=None
            )
        }
    )

    response = curriculum_context.client.get(
        "/v1/curriculum-profiles", headers=headers("second-teacher-token")
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["code"] == "cn-compulsory-2022"


def test_second_tenant_admin_cannot_write_the_global_catalogue(
    curriculum_context: CurriculumContext, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    second_tenant = Tenant(slug="pilot-2", name="Pilot 2")
    second_admin = User(
        tenant=second_tenant,
        role=Role.ADMIN,
        oidc_issuer=ISSUER,
        oidc_subject="second-admin-subject",
        display_name="Second admin",
        work_email="admin-2@example.test",
    )
    session.add_all([second_tenant, second_admin])
    session.commit()
    monkeypatch.setattr(settings, "oidc_tenant_slug", "pilot-2")
    app.dependency_overrides[get_token_verifier] = lambda: StaticVerifier(
        {
            "second-admin-token": VerifiedIdentity(
                issuer=ISSUER, subject="second-admin-subject", school_id=None
            )
        }
    )

    response = curriculum_context.client.post(
        "/v1/admin/curriculum/profiles",
        json={
            "code": "unauthorized-profile",
            "name": "Unauthorized",
            "jurisdiction": "district-2",
            "version_label": "2026",
            "source": {
                "issuer": "District 2",
                "title": "Curriculum",
                "canonical_url": "https://example.test/unauthorized",
                "version_label": "2026",
            },
        },
        headers=headers("second-admin-token"),
    )

    assert response.status_code == 404


def test_admin_creates_a_profile_grade_mapping_and_objective(
    curriculum_context: CurriculumContext,
) -> None:
    profile = curriculum_context.client.post(
        "/v1/admin/curriculum/profiles",
        json={
            "code": "district-math-2026",
            "name": "District mathematics 2026",
            "jurisdiction": "district-1",
            "version_label": "2026",
            "source": {
                "issuer": "District 1",
                "title": "Mathematics curriculum",
                "canonical_url": "https://example.test/district-math-2026",
                "version_label": "2026",
            },
        },
        headers=headers("admin-token"),
    )

    assert profile.status_code == 201
    assert profile.json()["status"] == "draft"
    profile_id = profile.json()["id"]
    reviewed_profile = curriculum_context.client.post(
        f"/v1/admin/curriculum/profiles/{profile_id}/transitions",
        json={"status": "in_review"},
        headers=headers("admin-token"),
    )
    activated_profile = curriculum_context.client.post(
        f"/v1/admin/curriculum/profiles/{profile_id}/transitions",
        json={"status": "active"},
        headers=headers("admin-token"),
    )
    assert reviewed_profile.json()["status"] == "in_review"
    assert activated_profile.json()["status"] == "active"
    mapping = curriculum_context.client.post(
        f"/v1/admin/curriculum/profiles/{profile_id}/grade-mappings",
        json={"internal_level": "G2", "external_label": "二年级", "position": 1},
        headers=headers("admin-token"),
    )
    assert mapping.status_code == 201

    objective = curriculum_context.client.post(
        f"/v1/admin/curriculum/profiles/{profile_id}/objectives",
        json={
            "grade_mapping_id": mapping.json()["id"],
            "code": "MATH-G2-NUM-001",
            "subject": "mathematics",
            "domain": "number",
            "knowledge_point": "place_value",
        },
        headers=headers("admin-token"),
    )
    assert objective.status_code == 201
    assert objective.json()["status"] == "draft"
    reviewed_objective = curriculum_context.client.post(
        f"/v1/admin/curriculum/objectives/{objective.json()['id']}/transitions",
        json={"status": "in_review"},
        headers=headers("admin-token"),
    )
    activated_objective = curriculum_context.client.post(
        f"/v1/admin/curriculum/objectives/{objective.json()['id']}/transitions",
        json={"status": "active"},
        headers=headers("admin-token"),
    )
    assert reviewed_objective.json()["status"] == "in_review"
    assert activated_objective.json()["status"] == "active"


def test_admin_creates_and_activates_an_append_only_revision(
    curriculum_context: CurriculumContext, session: Session
) -> None:
    created = curriculum_context.client.post(
        f"/v1/admin/curriculum/objectives/{curriculum_context.objective_id}/revisions",
        json={
            "revision_number": 2,
            "text": "Use whole numbers in practical situations.",
            "source_locator": "section 1.1",
            "allowed_question_types": ["M1"],
            "difficulty_min": 0.1,
            "difficulty_max": 0.5,
            "activity_type": "scored_question",
        },
        headers=headers("admin-token"),
    )

    assert created.status_code == 201
    revision_id = UUID(created.json()["id"])
    reviewed = curriculum_context.client.post(
        f"/v1/admin/curriculum/objective-revisions/{revision_id}/transitions",
        json={"status": "in_review"},
        headers=headers("admin-token"),
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "in_review"
    activated = curriculum_context.client.post(
        f"/v1/admin/curriculum/objective-revisions/{revision_id}/activate",
        headers=headers("admin-token"),
    )

    assert activated.status_code == 200
    assert activated.json()["status"] == "active"
    assert session.get(
        CurriculumObjectiveRevision, curriculum_context.active_revision_id
    ).status is (CurriculumRevisionStatus.RETIRED)
    assert (
        session.get(CurriculumObjectiveRevision, revision_id).status
        is CurriculumRevisionStatus.ACTIVE
    )
    assert (
        session.scalar(
            select(AuditLog).where(AuditLog.event_type == "curriculum.objective_revision_activated")
        )
        is not None
    )


def test_admin_gets_422_for_an_internal_level_not_supported_by_profile(
    curriculum_context: CurriculumContext,
) -> None:
    profile_id = curriculum_context.client.get(
        "/v1/curriculum-profiles", headers=headers("admin-token")
    ).json()["items"][0]["id"]

    response = curriculum_context.client.post(
        f"/v1/admin/curriculum/profiles/{profile_id}/grade-mappings",
        json={"internal_level": "G13", "external_label": "十三年级", "position": 20},
        headers=headers("admin-token"),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "internal level is not supported by this profile"


def test_admin_gets_422_for_scored_question_revision_on_kindergarten_objective(
    curriculum_context: CurriculumContext, session: Session
) -> None:
    profile = session.scalar(
        select(CurriculumProfile).where(CurriculumProfile.code == "cn-compulsory-2022")
    )
    assert profile is not None
    mapping = CurriculumGradeMapping(
        profile=profile,
        internal_level="K3_4",
        external_label="3–4 岁",
        position=2,
    )
    objective = CurriculumObjective(
        profile=profile,
        grade_mapping=mapping,
        code="K-NUMBER-001",
        subject="early_learning",
        domain="number_sense",
        status=CurriculumProfileStatus.ACTIVE,
    )
    session.add_all([mapping, objective])
    session.commit()

    response = curriculum_context.client.post(
        f"/v1/admin/curriculum/objectives/{objective.id}/revisions",
        json={
            "revision_number": 1,
            "text": "Count three objects.",
            "source_locator": "number sense",
            "allowed_question_types": ["M1"],
            "difficulty_min": 0,
            "difficulty_max": 0.2,
            "activity_type": "scored_question",
        },
        headers=headers("admin-token"),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "K levels only allow learning_activity-v1"


def test_admin_gets_422_for_question_type_from_another_subject(
    curriculum_context: CurriculumContext,
) -> None:
    response = curriculum_context.client.post(
        f"/v1/admin/curriculum/objectives/{curriculum_context.objective_id}/revisions",
        json={
            "revision_number": 2,
            "text": "Use whole numbers in practical situations.",
            "source_locator": "section 1.1",
            "allowed_question_types": ["E1"],
            "difficulty_min": 0.1,
            "difficulty_max": 0.5,
            "activity_type": "scored_question",
        },
        headers=headers("admin-token"),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "question types do not match objective subject"


def test_admin_creates_requires_prerequisite_and_rejects_a_cycle(
    curriculum_context: CurriculumContext, session: Session
) -> None:
    profile = session.scalar(
        select(CurriculumProfile).where(CurriculumProfile.code == "cn-compulsory-2022")
    )
    assert profile is not None
    mapping = session.scalar(
        select(CurriculumGradeMapping).where(CurriculumGradeMapping.profile_id == profile.id)
    )
    assert mapping is not None
    objective = CurriculumObjective(
        profile=profile,
        grade_mapping=mapping,
        code="MATH-G1-NUM-002",
        subject="mathematics",
        domain="number",
        status=CurriculumProfileStatus.ACTIVE,
    )
    revision = CurriculumObjectiveRevision(
        objective=objective,
        revision_number=1,
        text="Compare whole numbers.",
        source_locator="section 2",
        allowed_question_types=["M1"],
        difficulty_min=0,
        difficulty_max=0.4,
        activity_type=CurriculumActivityType.SCORED_QUESTION,
        status=CurriculumRevisionStatus.ACTIVE,
    )
    session.add_all([objective, revision])
    session.commit()

    created = curriculum_context.client.post(
        f"/v1/admin/curriculum/objective-revisions/{curriculum_context.active_revision_id}/prerequisites",
        json={"prerequisite_revision_id": str(revision.id)},
        headers=headers("admin-token"),
    )
    cycle = curriculum_context.client.post(
        f"/v1/admin/curriculum/objective-revisions/{revision.id}/prerequisites",
        json={"prerequisite_revision_id": str(curriculum_context.active_revision_id)},
        headers=headers("admin-token"),
    )

    assert created.status_code == 201
    assert created.json()["relation_type"] == "requires"
    assert cycle.status_code == 422
    assert cycle.json()["detail"] == "prerequisite cycle detected"
