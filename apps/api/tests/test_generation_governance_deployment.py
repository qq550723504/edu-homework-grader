from pathlib import Path

import yaml


def test_compose_passes_governance_admin_allowlist_to_api() -> None:
    repository_root = Path(__file__).parents[3]
    compose = yaml.safe_load((repository_root / "compose.yaml").read_text(encoding="utf-8"))
    api_environment = compose["services"]["api"]["environment"]

    assert "GENERATION_GOVERNANCE_ADMIN_SUBJECTS" in api_environment
    assert "CURRICULUM_ADMIN_SUBJECTS" in api_environment


def test_example_environment_documents_governance_admin_allowlist() -> None:
    repository_root = Path(__file__).parents[3]
    example = (repository_root / ".env.example").read_text(encoding="utf-8")

    assert "GENERATION_GOVERNANCE_ADMIN_SUBJECTS=" in example
