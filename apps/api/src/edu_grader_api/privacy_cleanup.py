import argparse
from uuid import UUID

from .db import SessionLocal
from .models import utc_now
from .services.privacy_cleanup import complete_privacy_request, eligible_privacy_requests


def main() -> int:
    parser = argparse.ArgumentParser(description="Review or execute one eligible privacy cleanup.")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--request-id")
    parser.add_argument("--actor-user-id")
    args = parser.parse_args()
    if args.execute and (args.request_id is None or args.actor_user_id is None):
        parser.error("--execute requires --request-id and --actor-user-id")
    if not args.execute and (args.request_id is not None or args.actor_user_id is not None):
        parser.error("--request-id and --actor-user-id require --execute")

    with SessionLocal.begin() as session:
        if not args.execute:
            for request in eligible_privacy_requests(session, now=utc_now()):
                print(f"{request.id} {request.eligible_for_deletion_at.isoformat()}")
            return 0
        result = complete_privacy_request(
            session,
            request_id=UUID(args.request_id),
            actor_user_id=UUID(args.actor_user_id),
            now=utc_now(),
        )
    print(f"{result.request_id} {result.status.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
