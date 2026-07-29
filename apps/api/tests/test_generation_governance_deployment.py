from pathlib import Path

import yaml


def test_compose_passes_governance_admin_allowlist_to_api() -> None:
    repository_root = Path(__file__).parents[3]
    compose = yaml.safe_load((repository_root / "compose.yaml").read_text(encoding="utf-8"))
    api_environment = compose["services"]["api"]["environment"]

    assert "GENERATION_GOVERNANCE_ADMIN_SUBJECTS" in api_environment
    assert "CURRICULUM_ADMIN_SUBJECTS" in api_environment
    assert "EVALUATION_EVIDENCE_HMAC_KEY" in api_environment


def test_example_environment_documents_governance_admin_allowlist() -> None:
    repository_root = Path(__file__).parents[3]
    example = (repository_root / ".env.example").read_text(encoding="utf-8")

    assert "GENERATION_GOVERNANCE_ADMIN_SUBJECTS=" in example
    assert "EVALUATION_EVIDENCE_HMAC_KEY=" in example


def test_production_passes_governance_admin_allowlist_to_api() -> None:
    repository_root = Path(__file__).parents[3]
    production = yaml.safe_load_all(
        (repository_root / "infra/k8s/production/application.yaml").read_text(encoding="utf-8")
    )
    api = next(document for document in production if document["metadata"]["name"] == "api")
    environment = api["spec"]["template"]["spec"]["containers"][0]["env"]

    assert any(item["name"] == "GENERATION_GOVERNANCE_ADMIN_SUBJECTS" for item in environment)
    assert any(
        item["name"] == "EVALUATION_EVIDENCE_HMAC_KEY"
        and item["valueFrom"]["secretKeyRef"]
        == {
            "name": "edu-grader-runtime",
            "key": "EVALUATION_EVIDENCE_HMAC_KEY",
        }
        for item in environment
    )
    assert any(
        item["name"] == "OPENAI_API_KEY"
        and item["valueFrom"]["secretKeyRef"]
        == {
            "name": "edu-grader-runtime",
            "key": "OPENAI_API_KEY",
        }
        for item in environment
    )


def test_production_secret_bootstrap_requires_and_provisions_generation_controls() -> None:
    repository_root = Path(__file__).parents[3]
    bootstrap = (repository_root / "scripts/k8s/create-prod-secrets.ps1").read_text(
        encoding="utf-8"
    )

    assert "[string[]]$GenerationGovernanceAdminSubjects" in bootstrap
    assert "[string]$OpenAiApiKey" in bootstrap
    assert "[string]$EvaluationEvidenceHmacKey" in bootstrap
    assert "GENERATION_GOVERNANCE_ADMIN_SUBJECTS" in bootstrap
    assert "OPENAI_API_KEY" in bootstrap
    assert "EVALUATION_EVIDENCE_HMAC_KEY" in bootstrap
