from collections.abc import Iterable
from datetime import UTC, datetime

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from ..db import SessionLocal
from ..services.operational_evaluation_kubernetes import terminal_failure_code
from ..services.operational_evaluation_retention import (
    purge_expired_evaluations,
    reconcile_terminal_evaluations,
)


def delete_callback_secret(core: client.CoreV1Api, *, name: str, namespace: str) -> None:
    try:
        core.delete_namespaced_secret(name=name, namespace=namespace)
    except ApiException as error:
        if error.status != 404:
            raise


def delete_reconciled_callback_secrets(
    core: client.CoreV1Api, *, run_ids: Iterable[str], namespace: str
) -> None:
    for run_id in run_ids:
        delete_callback_secret(
            core, name=f"operational-evaluation-callback-{run_id}", namespace=namespace
        )


def main() -> int:
    config.load_incluster_config()
    core = client.CoreV1Api()
    batch = client.BatchV1Api()
    with SessionLocal() as session:
        now = datetime.now(UTC)
        reconciled_run_ids = reconcile_terminal_evaluations(
            session,
            now=now,
            terminal_failure_code=lambda run_id: terminal_failure_code(
                batch_api=batch, namespace="edu-homework-grader", run_id=str(run_id)
            ),
        )
        delete_reconciled_callback_secrets(
            core,
            run_ids=(str(run_id) for run_id in reconciled_run_ids),
            namespace="edu-homework-grader",
        )
        purge_expired_evaluations(
            session,
            now=now,
            delete_secret=lambda name: delete_callback_secret(
                core, name=name, namespace="edu-homework-grader"
            ),
        )
        session.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
