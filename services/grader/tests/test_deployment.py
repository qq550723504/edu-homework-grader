Exit code: 0
Wall time: 1.9 seconds
Output:
from pathlib import Path


def test_compose_keeps_languagetool_private_and_configures_private_url() -> None:
    compose = Path("compose.yaml").read_text(encoding="utf-8")

    service = compose.split("  languagetool:\n", maxsplit=1)[1].split("\n  grader:\n", maxsplit=1)[
        0
    ]

    assert "ports:" not in service
    assert "LANGUAGETOOL_BASE_URL: ${LANGUAGETOOL_BASE_URL:-http://languagetool:8010/v2}" in compose


def test_compose_allocates_memory_for_the_preloaded_english_embedding_model() -> None:
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    grader = compose.split("  grader:\n", maxsplit=1)[1].split("\n  api:\n", maxsplit=1)[0]

    assert "mem_limit: ${GRADER_MEMORY_LIMIT:-1536m}" in grader


def test_deployments_allocate_math_worker_address_space_for_sympy() -> None:
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    grader = compose.split("  grader:\n", maxsplit=1)[1].split("\n  api:\n", maxsplit=1)[0]
    production = Path("infra/k8s/production/application.yaml").read_text(encoding="utf-8")

    assert "GRADER_MATH_MEMORY_BYTES: ${GRADER_MATH_MEMORY_BYTES:-536870912}" in grader
    assert 'name: GRADER_MATH_MEMORY_BYTES\n              value: "536870912"' in production

