from edu_grader_api.models import AppealStatus, Base, CorrectionAttempt, ReviewAppeal


def test_appeal_and_correction_tables_are_registered() -> None:
    assert AppealStatus.OPEN.value == "open"
    assert ReviewAppeal.__tablename__ in Base.metadata.tables
    assert CorrectionAttempt.__tablename__ in Base.metadata.tables
