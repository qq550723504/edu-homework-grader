from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "prefetch_english_model.py"
SPEC = importlib.util.spec_from_file_location("prefetch_english_model", SCRIPT_PATH)
assert SPEC and SPEC.loader
prefetch_english_model = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prefetch_english_model)


def test_tree_digest_ignores_huggingface_download_cache(tmp_path: Path) -> None:
    model_directory = tmp_path / "model"
    model_directory.mkdir()
    (model_directory / "config.json").write_text('{"hidden_size": 384}', encoding="utf-8")
    download_cache = model_directory / ".cache" / "huggingface" / "download"
    download_cache.mkdir(parents=True)
    metadata = download_cache / "config.json.metadata"
    metadata.write_text("first transport response", encoding="utf-8")

    first_digest = prefetch_english_model._tree_digest(model_directory)
    metadata.write_text("later transport response", encoding="utf-8")

    assert prefetch_english_model._tree_digest(model_directory) == first_digest


def test_configured_english_model_digest_matches_the_verified_snapshot() -> None:
    verified_digest = "sha256:84714cdabb16d132cbe6e1a4cbd21167abd09eccbdaf69dd053136ae68cc7c17"
    repository_root = Path(__file__).parents[3]

    for path in (
        repository_root / ".env.example",
        repository_root / "compose.yaml",
        repository_root / "services" / "grader" / "Dockerfile",
    ):
        assert verified_digest in path.read_text(encoding="utf-8")
