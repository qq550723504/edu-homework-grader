from pathlib import Path


WORKFLOW_PATH = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "publish-images.yml"
EVIDENCE_WORKFLOW_PATH = (
    Path(__file__).resolve().parents[3]
    / ".github"
    / "workflows"
    / "verification-release-evidence.yml"
)


def test_publish_images_workflow_uses_immutable_ghcr_tags() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "packages: write" in workflow
    assert "- name: api" in workflow
    assert "- name: grader" in workflow
    assert "- name: web" in workflow
    assert "- name: languagetool" in workflow
    immutable_tag = (
        "ghcr.io/${{ github.repository_owner }}/edu-homework-grader-"
        "${{ matrix.name }}:${{ github.event.workflow_run.head_sha }}"
    )
    obsolete_workflow_sha_tag = (
        "ghcr.io/${{ github.repository_owner }}/edu-homework-grader-"
        "${{ matrix.name }}:${{ github.sha }}"
    )

    assert immutable_tag in workflow
    assert obsolete_workflow_sha_tag not in workflow


def test_publish_images_gates_protected_deploy_on_reusable_release_evidence() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "id: build" in workflow
    assert "image-digest-${{ matrix.name }}" in workflow
    assert "release-manifest:" in workflow
    assert "release-evidence:" in workflow
    assert "uses: ./.github/workflows/verification-release-evidence.yml" in workflow
    assert "source_sha: ${{ github.event.workflow_run.head_sha }}" in workflow
    assert "image_digests: ${{ needs.release-manifest.outputs.image_digests }}" in workflow
    assert "needs: [eligibility, publish, release-manifest, release-evidence]" in workflow


def test_release_evidence_workflow_accepts_immutable_rc_inputs() -> None:
    workflow = EVIDENCE_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "workflow_call:" in workflow
    assert "source_sha:" in workflow
    assert "image_digests:" in workflow
    assert (
        "ref: ${{ inputs.source_sha || github.event.pull_request.head.sha || github.sha }}"
        in workflow
    )
    assert "release-manifest.json" in workflow
