#!/usr/bin/env python3
"""Fail when authoritative project-status documentation drifts from repository facts."""

from __future__ import annotations

import ast
from datetime import date
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / "docs/status-evidence.json"
AUTHORITATIVE_MARKDOWN = (
    ROOT / "README.md",
    ROOT / "docs/README.md",
    ROOT / "docs/project-status.md",
    ROOT / "docs/pilot-checklist.md",
    ROOT / "docs/roadmap.md",
    ROOT / "docs/operations/ai-evaluation-operational.md",
)
EXPECTED_CI_JOBS = {
    "changes",
    "python",
    "migrations",
    "compose",
    "live-grader-integration",
    "web",
    "browser-e2e",
}
BANNED_STALE_CLAIMS = (
    "本切片尚未实现批量接受",
    "仍需在可访问 Docker Hub 的环境完成镜像构建",
    "镜像构建与真实模型校准待外部网络恢复后验收",
    "生产已就绪",
)
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
MARKDOWN_LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def main() -> int:
    errors: list[str] = []
    evidence = _load_json(EVIDENCE_PATH, errors)
    if evidence is None:
        return _finish(errors)

    _check_evidence_schema(evidence, errors)
    _check_internal_links(errors)
    _check_ci_jobs(evidence, errors)
    _check_generation_versions(evidence, errors)
    _check_policy_versions(evidence, errors)
    _check_english_model(evidence, errors)
    _check_authoritative_copy(evidence, errors)
    return _finish(errors)


def _load_json(path: Path, errors: list[str]) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"unable to load {path.relative_to(ROOT)}: {error}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{path.relative_to(ROOT)} must contain a JSON object")
        return None
    return value


def _check_evidence_schema(evidence: dict[str, object], errors: list[str]) -> None:
    if evidence.get("schema_version") != 1:
        errors.append("docs/status-evidence.json schema_version must be 1")
    status_as_of = evidence.get("status_as_of")
    try:
        date.fromisoformat(str(status_as_of))
    except ValueError:
        errors.append("status_as_of must be an ISO date")
    for field in ("evidence_base_commit",):
        value = evidence.get(field)
        if not isinstance(value, str) or not SHA_PATTERN.fullmatch(value):
            errors.append(f"{field} must be a full lowercase Git commit SHA")
    ci = _dict_field(evidence, "latest_full_ci", errors)
    if ci is not None:
        tested_head = ci.get("tested_head")
        if not isinstance(tested_head, str) or not SHA_PATTERN.fullmatch(tested_head):
            errors.append("latest_full_ci.tested_head must be a full lowercase Git SHA")
        if ci.get("conclusion") != "success":
            errors.append("latest_full_ci must reference a successful run")
    evaluation = _dict_field(evidence, "ai_evaluation", errors)
    if evaluation is not None and evaluation.get("conclusion") != "success":
        errors.append("ai_evaluation must reference a successful run")
    provider = _dict_field(evidence, "live_generator_provider_acceptance", errors)
    if provider is not None:
        if provider.get("conclusion") != "success":
            errors.append("live generator Provider acceptance must be successful")
        if provider.get("question_types") != ["M1", "M2", "E1", "E4"]:
            errors.append("live Provider acceptance coverage must remain M1/M2/E1/E4")
    release = _dict_field(evidence, "release_state", errors)
    if release is not None:
        expected_keys = {
            "code_implemented",
            "repository_ci_verified",
            "release_environment_full_stack_verified",
            "school_pilot_environment_deployed",
            "backup_restore_drill_verified",
            "production_live",
        }
        if set(release) != expected_keys:
            errors.append("release_state keys changed; update the checker and status semantics")
        if any(not isinstance(value, bool) for value in release.values()):
            errors.append("release_state values must be booleans")
        if release.get("production_live") and not all(release.values()):
            errors.append("production_live cannot be true while an earlier release gate is false")


def _check_internal_links(errors: list[str]) -> None:
    for document in AUTHORITATIVE_MARKDOWN:
        if not document.is_file():
            errors.append(f"authoritative document is missing: {document.relative_to(ROOT)}")
            continue
        text = document.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK_PATTERN.findall(text):
            target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            path_text = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if not path_text:
                continue
            resolved = (document.parent / path_text).resolve()
            try:
                resolved.relative_to(ROOT)
            except ValueError:
                errors.append(
                    f"link escapes the repository: {document.relative_to(ROOT)} -> {target}"
                )
                continue
            if not resolved.exists():
                errors.append(
                    f"broken internal link: {document.relative_to(ROOT)} -> {target}"
                )


def _check_ci_jobs(evidence: dict[str, object], errors: list[str]) -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    jobs = _top_level_yaml_keys(workflow, section="jobs")
    if jobs != EXPECTED_CI_JOBS:
        errors.append(
            "CI jobs changed: expected "
            f"{sorted(EXPECTED_CI_JOBS)}, observed {sorted(jobs)}"
        )
    ci = _dict_field(evidence, "latest_full_ci", errors)
    if ci is None:
        return
    documented = ci.get("required_jobs")
    if not isinstance(documented, list) or set(documented) != jobs:
        errors.append("latest_full_ci.required_jobs must match .github/workflows/ci.yml")
    if ci.get("workflow") != "CI":
        errors.append("latest_full_ci.workflow must be CI")


def _check_generation_versions(evidence: dict[str, object], errors: list[str]) -> None:
    contract = _dict_field(evidence, "generation_contract", errors)
    evaluation = _dict_field(evidence, "ai_evaluation", errors)
    if contract is None or evaluation is None:
        return
    generation_source = (
        ROOT / "apps/api/src/edu_grader_api/services/generation.py"
    ).read_text(encoding="utf-8")
    prompt_match = re.search(
        r'^GENERATION_PROMPT_VERSION\s*=\s*"([^"]+)"', generation_source, re.MULTILINE
    )
    if prompt_match is None or prompt_match.group(1) != contract.get("prompt_version"):
        errors.append("documented generation prompt version does not match generation.py")
    prompt_catalog = (
        ROOT / "services/generator/src/edu_generator/prompt_templates.py"
    ).read_text(encoding="utf-8")
    prompt_version = contract.get("prompt_version")
    if not isinstance(prompt_version, str) or f'version="{prompt_version}"' not in prompt_catalog:
        errors.append("documented prompt version is not present in the prompt catalogue")
    verification_source = (
        ROOT / "apps/api/src/edu_grader_api/services/question_verification.py"
    ).read_text(encoding="utf-8")
    expected_constants = {
        "VALIDATOR_VERSION": contract.get("validator_version"),
        "RULESET_VERSION": contract.get("ruleset_version"),
    }
    for name, expected in expected_constants.items():
        match = re.search(rf'^{name}\s*=\s*"([^"]+)"', verification_source, re.MULTILINE)
        if match is None or match.group(1) != expected:
            errors.append(f"documented {name} does not match question_verification.py")
    operational_source = (
        ROOT / "apps/api/src/edu_grader_api/services/ai_evaluation_operational.py"
    ).read_text(encoding="utf-8")
    match = re.search(
        r'^EXPORTER_VERSION\s*=\s*"([^"]+)"', operational_source, re.MULTILINE
    )
    if match is None or match.group(1) != evaluation.get("operational_exporter_version"):
        errors.append("documented operational exporter version does not match code")


def _check_policy_versions(evidence: dict[str, object], errors: list[str]) -> None:
    source = (ROOT / "apps/api/src/edu_grader_api/policies.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    observed: set[str] | None = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "DEFAULT_POLICY_KEYS" for target in node.targets):
            continue
        if (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "frozenset"
            and len(node.value.args) == 1
        ):
            pairs = ast.literal_eval(node.value.args[0])
            observed = {f"{question_type}@{version}" for question_type, version in pairs}
        break
    documented = evidence.get("default_question_policies")
    if observed is None:
        errors.append("unable to parse DEFAULT_POLICY_KEYS from policies.py")
    elif not isinstance(documented, list) or set(documented) != observed:
        errors.append(
            f"default question policies drifted: documented={documented}, observed={sorted(observed)}"
        )


def _check_english_model(evidence: dict[str, object], errors: list[str]) -> None:
    model = _dict_field(evidence, "english_embedding_model", errors)
    if model is None:
        return
    model_id = model.get("model_id")
    revision = model.get("revision")
    digest = model.get("tree_digest")
    if not isinstance(revision, str) or not SHA_PATTERN.fullmatch(revision):
        errors.append("English model revision must be a full Git SHA")
    if not isinstance(digest, str) or not DIGEST_PATTERN.fullmatch(digest):
        errors.append("English model tree_digest must be sha256:<64 lowercase hex>")
    dockerfile = (ROOT / "services/grader/Dockerfile").read_text(encoding="utf-8")
    expected = {
        "ENGLISH_EMBEDDING_MODEL_ID": model_id,
        "ENGLISH_EMBEDDING_MODEL_REVISION": revision,
        "ENGLISH_EMBEDDING_MODEL_DIGEST": digest,
    }
    for name, value in expected.items():
        if not isinstance(value, str) or dockerfile.count(f"ARG {name}={value}") != 2:
            errors.append(f"{name} must match both Grader Dockerfile stages")
    if model.get("container_build_verified") is not True:
        errors.append("status evidence must reflect the verified Grader image build")
    if model.get("live_grader_http_verified") is not True:
        errors.append("status evidence must reflect the verified live Grader HTTP test")


def _check_authoritative_copy(evidence: dict[str, object], errors: list[str]) -> None:
    texts = {
        path: path.read_text(encoding="utf-8")
        for path in AUTHORITATIVE_MARKDOWN
        if path.is_file()
    }
    combined = "\n".join(texts.values())
    for claim in BANNED_STALE_CLAIMS:
        if claim in combined:
            errors.append(f"stale or unsupported status claim remains: {claim}")
    project_status = texts.get(ROOT / "docs/project-status.md", "")
    for required_phrase in ("代码已实现", "CI 已验证", "发布环境已验收", "生产已上线"):
        if required_phrase not in project_status:
            errors.append(f"project status must define the state: {required_phrase}")
    base_commit = evidence.get("evidence_base_commit")
    if isinstance(base_commit, str) and base_commit not in project_status:
        errors.append("project status must cite evidence_base_commit")
    status_date = evidence.get("status_as_of")
    if isinstance(status_date, str) and status_date not in project_status:
        errors.append("project status must cite status_as_of")
    model = evidence.get("english_embedding_model")
    if isinstance(model, dict):
        for key in ("model_id", "revision", "tree_digest"):
            value = model.get(key)
            if isinstance(value, str) and value not in project_status:
                errors.append(f"project status must cite English model {key}")
    root_readme = texts.get(ROOT / "README.md", "")
    if "docs/status-evidence.json" not in root_readme:
        errors.append("README must link to docs/status-evidence.json")
    docs_index = texts.get(ROOT / "docs/README.md", "")
    for target in ("status-evidence.json", "operations/ai-evaluation-operational.md"):
        if target not in docs_index:
            errors.append(f"docs index must link to {target}")


def _dict_field(
    value: dict[str, object], key: str, errors: list[str]
) -> dict[str, object] | None:
    field = value.get(key)
    if not isinstance(field, dict):
        errors.append(f"{key} must be an object")
        return None
    return field


def _top_level_yaml_keys(text: str, *, section: str) -> set[str]:
    in_section = False
    keys: set[str] = set()
    for line in text.splitlines():
        if line == f"{section}:":
            in_section = True
            continue
        if not in_section:
            continue
        if line and not line.startswith(" "):
            break
        match = re.fullmatch(r"  ([A-Za-z0-9_-]+):", line)
        if match:
            keys.add(match.group(1))
    return keys


def _finish(errors: list[str]) -> int:
    if errors:
        print("Documentation/status integrity check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Documentation/status integrity check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
