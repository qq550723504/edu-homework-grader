from __future__ import annotations

from pathlib import Path

import yaml


def test_e2e_jobs_install_the_python_api_runtime() -> None:
    workflow_path = Path(__file__).parents[3] / ".github" / "workflows" / "ci.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    for job_name in ("web", "browser-e2e"):
        steps = workflow["jobs"][job_name]["steps"]
        assert any(step.get("uses") == "actions/setup-python@v5" for step in steps)
        assert any(step.get("run") == "make install-python" for step in steps)
