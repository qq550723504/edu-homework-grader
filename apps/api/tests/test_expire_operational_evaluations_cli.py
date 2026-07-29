from kubernetes.client.exceptions import ApiException

from edu_grader_api.cli.expire_operational_evaluations import (
    delete_callback_secret,
    delete_reconciled_callback_secrets,
)


class MissingSecretCoreApi:
    def delete_namespaced_secret(self, **_kwargs: object) -> None:
        raise ApiException(status=404)


class FailingSecretCoreApi:
    def delete_namespaced_secret(self, **_kwargs: object) -> None:
        raise ApiException(status=500)


class RecordingSecretCoreApi:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_namespaced_secret(self, *, name: str, **_kwargs: object) -> None:
        self.deleted.append(name)


def test_delete_callback_secret_ignores_only_not_found() -> None:
    delete_callback_secret(
        MissingSecretCoreApi(), name="operational-evaluation-callback-run", namespace="test"
    )


def test_delete_callback_secret_propagates_unexpected_kubernetes_errors() -> None:
    try:
        delete_callback_secret(
            FailingSecretCoreApi(), name="operational-evaluation-callback-run", namespace="test"
        )
    except ApiException as error:
        assert error.status == 500
    else:
        raise AssertionError("unexpected Kubernetes errors must stop retention")


def test_reconciled_runs_delete_their_callback_secrets_immediately() -> None:
    core = RecordingSecretCoreApi()

    delete_reconciled_callback_secrets(core, run_ids=["run-a", "run-b"], namespace="test")

    assert core.deleted == [
        "operational-evaluation-callback-run-a",
        "operational-evaluation-callback-run-b",
    ]
