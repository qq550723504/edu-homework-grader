from __future__ import annotations

from pathlib import Path

import yaml


def test_ci_reuses_cached_images_and_installs_python_for_e2e_jobs() -> None:
    workflow_path = Path(__file__).parents[3] / ".github" / "workflows" / "ci.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    web_steps = workflow["jobs"]["web"]["steps"]
    browser_steps = workflow["jobs"]["browser-e2e"]["steps"]
    assert any(step.get("uses") == "actions/setup-python@v5" for step in web_steps)
    assert any(step.get("run") == "make install-python" for step in web_steps)
    assert any(step.get("uses") == "actions/setup-python@v5" for step in browser_steps)
    assert any(step.get("run") == "make install-python" for step in browser_steps)

    for job_name in ("compose", "live-grader-integration"):
        steps = workflow["jobs"][job_name]["steps"]
        assert any(step.get("uses") == "docker/setup-buildx-action@v4" for step in steps)
        bake_step = next(step for step in steps if step.get("uses") == "docker/bake-action@v7")
        assert bake_step["with"]["source"] == "."
        assert bake_step["with"]["load"] is True
        assert "compose.yaml" in bake_step["with"]["files"]
        assert "docker-bake.ci.hcl" in bake_step["with"]["files"]

    compose_steps = workflow["jobs"]["compose"]["steps"]
    assert not any(
        step.get("run") == "docker compose build api grader web languagetool"
        for step in compose_steps
    )
    compose_bake_step = next(
        step for step in compose_steps if step.get("uses") == "docker/bake-action@v7"
    )
    assert compose_bake_step["with"]["targets"] == "api,web"

    live_steps = workflow["jobs"]["live-grader-integration"]["steps"]
    live_bake_step = next(
        step for step in live_steps if step.get("uses") == "docker/bake-action@v7"
    )
    assert live_bake_step["with"]["targets"] == "grader,languagetool"
    assert any(
        step.get("run") == "docker compose up --detach --wait --no-build languagetool grader"
        for step in live_steps
    )
