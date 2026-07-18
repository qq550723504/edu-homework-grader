from pathlib import Path


def test_compose_keeps_languagetool_private_and_configures_private_url() -> None:
    compose = Path("compose.yaml").read_text(encoding="utf-8")

    service = compose.split("  languagetool:\n", maxsplit=1)[1].split("\n  grader:\n", maxsplit=1)[
        0
    ]

    assert "ports:" not in service
    assert "LANGUAGETOOL_BASE_URL: ${LANGUAGETOOL_BASE_URL:-http://languagetool:8010/v2}" in compose
