import argparse

from .db import SessionLocal
from .services.guardian_consent_integrity import (
    inspect_guardian_consent_integrity,
    repair_missing_guardian_consents,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report or repair missing guardian-consent records."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="create pending records for students whose consent record is missing",
    )
    args = parser.parse_args()

    with SessionLocal.begin() as session:
        report = inspect_guardian_consent_integrity(session)
        if args.execute:
            repaired = repair_missing_guardian_consents(session)
            print(f"created_pending={_format_ids(repaired.created_student_ids)}")
        print(f"missing={_format_ids(report.missing_student_ids)}")
        print(f"contradictory={_format_ids(report.contradictory_student_ids)}")
    return 0


def _format_ids(ids: tuple[object, ...]) -> str:
    return ",".join(str(item) for item in ids)


if __name__ == "__main__":
    raise SystemExit(main())
