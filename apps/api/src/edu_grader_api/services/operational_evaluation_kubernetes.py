from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from kubernetes.client.exceptions import ApiException

from ..settings import Settings

_DIGEST_PREFIX = "@sha256:"


def terminal_failure_code(*, batch_api: Any, namespace: str, run_id: str) -> str | None:
    try:
        job = batch_api.read_namespaced_job_status(
            name=f"operational-evaluation-{run_id}", namespace=namespace
        )
    except ApiException as error:
        if error.status == 404:
            return "evaluation_job_missing"
        raise

    status = job.status
    for condition in status.conditions or []:
        if condition.type == "Failed" and condition.status == "True":
            return (
                "evaluation_job_deadline_exceeded"
                if condition.reason == "DeadlineExceeded"
                else "evaluation_job_failed"
            )
    if status.succeeded:
        return "evaluation_job_completed_without_callback"
    if status.failed:
        return "evaluation_job_failed"
    return None


@dataclass
class KubernetesOperationalEvaluationJobLauncher:
    namespace: str
    image: str
    runtime_secret_name: str
    callback_base_url: str
    batch_api: Any
    core_api: Any

    @classmethod
    def from_settings(cls, settings: Settings) -> KubernetesOperationalEvaluationJobLauncher:
        if _DIGEST_PREFIX not in settings.operational_evaluation_executor_image:
            raise ValueError("OPERATIONAL_EVALUATION_EXECUTOR_IMAGE must be digest pinned")
        try:
            from kubernetes import client, config
        except ImportError as error:
            raise RuntimeError("Kubernetes client dependency is unavailable") from error
        config.load_incluster_config()
        return cls(
            namespace=settings.operational_evaluation_namespace,
            image=settings.operational_evaluation_executor_image,
            runtime_secret_name="operational-evaluation-runtime",
            callback_base_url=settings.operational_evaluation_callback_base_url,
            batch_api=client.BatchV1Api(),
            core_api=client.CoreV1Api(),
        )

    def launch(self, *, run_id: str, spec_json: dict[str, object], callback_token: str) -> None:
        callback_secret_name = f"operational-evaluation-callback-{run_id}"
        self.core_api.create_namespaced_secret(
            namespace=self.namespace,
            body={
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": callback_secret_name, "labels": self._labels(run_id)},
                "stringData": {"callback-token": callback_token},
            },
        )
        try:
            self.batch_api.create_namespaced_job(
                namespace=self.namespace,
                body=self.manifest_for(
                    run_id=run_id,
                    spec_json=spec_json,
                    callback_secret_name=callback_secret_name,
                ),
            )
        except Exception:
            self.delete_callback_secret(run_id=run_id)
            raise

    def delete_callback_secret(self, *, run_id: str) -> None:
        try:
            self.core_api.delete_namespaced_secret(
                name=f"operational-evaluation-callback-{run_id}", namespace=self.namespace
            )
        except ApiException as error:
            if error.status != 404:
                raise

    def terminal_failure_code(self, *, run_id: str) -> str | None:
        return terminal_failure_code(
            batch_api=self.batch_api, namespace=self.namespace, run_id=run_id
        )

    def manifest_for(
        self, *, run_id: str, spec_json: dict[str, object], callback_secret_name: str
    ) -> dict[str, object]:
        return {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {
                "name": f"operational-evaluation-{run_id}",
                "labels": self._labels(run_id),
            },
            "spec": {
                "backoffLimit": 0,
                "activeDeadlineSeconds": 900,
                "ttlSecondsAfterFinished": 3600,
                "template": {
                    "metadata": {"labels": self._labels(run_id)},
                    "spec": {
                        "restartPolicy": "Never",
                        "serviceAccountName": "operational-evaluation-executor",
                        "containers": [
                            {
                                "name": "evaluate",
                                "image": self.image,
                                "imagePullPolicy": "IfNotPresent",
                                "command": [
                                    "python",
                                    "-m",
                                    "edu_grader_api.services.operational_evaluation_executor",
                                ],
                                "env": [
                                    {"name": "OPERATIONAL_EVALUATION_RUN_ID", "value": run_id},
                                    {
                                        "name": "OPERATIONAL_EVALUATION_SPEC_JSON",
                                        "value": json.dumps(spec_json, separators=(",", ":")),
                                    },
                                    {
                                        "name": "OPERATIONAL_EVALUATION_CALLBACK_URL",
                                        "value": f"{self.callback_base_url.rstrip('/')}/v1/internal/operational-evaluations/{run_id}/completion",
                                    },
                                    self._secret_env(
                                        "DATABASE_URL", self.runtime_secret_name, "DATABASE_URL"
                                    ),
                                    self._secret_env(
                                        "EVALUATION_EVIDENCE_HMAC_KEY",
                                        self.runtime_secret_name,
                                        "EVALUATION_EVIDENCE_HMAC_KEY",
                                    ),
                                    self._secret_env(
                                        "OPERATIONAL_EVALUATION_CALLBACK_TOKEN",
                                        callback_secret_name,
                                        "callback-token",
                                    ),
                                ],
                                "resources": {
                                    "requests": {"cpu": "100m", "memory": "256Mi"},
                                    "limits": {"cpu": "500m", "memory": "512Mi"},
                                },
                            }
                        ],
                    },
                },
            },
        }

    @staticmethod
    def _secret_env(name: str, secret_name: str, key: str) -> dict[str, object]:
        return {
            "name": name,
            "valueFrom": {"secretKeyRef": {"name": secret_name, "key": key}},
        }

    @staticmethod
    def _labels(run_id: str) -> dict[str, str]:
        return {
            "app.kubernetes.io/component": "operational-evaluation",
            "edu.getkr.com/run-id": run_id,
        }
