from datetime import UTC, datetime

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from ..db import SessionLocal
from ..services.operational_evaluation_retention import purge_expired_evaluations


def delete_callback_secret(core: client.CoreV1Api, *, name: str, namespace: str) -> None:
    try:
        core.delete_namespaced_secret(name=name, namespace=namespace)
    except ApiException as error:
        if error.status != 404:
            raise


def main() -> int:
    config.load_incluster_config()
    core = client.CoreV1Api()
    with SessionLocal() as session:
        purge_expired_evaluations(
            session,
            now=datetime.now(UTC),
            delete_secret=lambda name: delete_callback_secret(
                core, name=name, namespace="edu-homework-grader"
            ),
        )
        session.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
