import argparse
import json
from pathlib import Path

from ..db import SessionLocal
from ..services.customer_provisioning import provision_customer
from ..services.roster import parse_roster
from ..settings import settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Provision one customer tenant and roster")
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument("--tenant-name", required=True)
    parser.add_argument("--teacher-subject", required=True)
    parser.add_argument("--teacher-name", required=True)
    parser.add_argument("--teacher-email", required=True)
    parser.add_argument("--roster-csv", type=Path, required=True)
    parser.add_argument("--oidc-issuer", default=settings.oidc_issuer)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    rows = parse_roster(args.roster_csv.read_bytes())
    with SessionLocal() as session:
        result = provision_customer(
            session,
            tenant_slug=args.tenant_slug,
            tenant_name=args.tenant_name,
            oidc_issuer=args.oidc_issuer,
            teacher_subject=args.teacher_subject,
            teacher_display_name=args.teacher_name,
            teacher_email=args.teacher_email,
            rows=rows,
        )
    print(
        json.dumps(
            {
                "tenant_id": str(result.tenant_id),
                "teacher_id": str(result.teacher_id),
                "class_ids": [str(class_id) for class_id in result.class_ids],
                "imported_students": result.imported_students,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
