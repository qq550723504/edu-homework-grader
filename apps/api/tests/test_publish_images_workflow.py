from pathlib import Path


WORKFLOW_PATH = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "publish-images.yml"


def test_publish_images_workflow_uses_immutable_ghcr_tags() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "packages: write" in workflow
    assert "- name: api" in workflow
    assert "- name: grader" in workflow
    assert "- name: web" in workflow
    assert "- name: languagetool" in workflow
    assert (
        "ghcr.io/${{ github.repository_owner }}/edu-homework-grader-${{ matrix.name }}:${{ github.sha }}"
        in workflow
    )
