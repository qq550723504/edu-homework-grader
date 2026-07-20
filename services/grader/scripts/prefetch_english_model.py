from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--expected-digest", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if not arguments.expected_digest.startswith("sha256:"):
        raise SystemExit("--expected-digest must start with sha256:")

    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=arguments.model_id,
        revision=arguments.revision,
        local_dir=arguments.output,
        local_dir_use_symlinks=False,
    )
    digest = f"sha256:{_tree_digest(arguments.output)}"
    if digest != arguments.expected_digest:
        raise SystemExit(
            f"model digest mismatch: expected {arguments.expected_digest}, got {digest}"
        )
    (arguments.output / "metadata.json").write_text(
        json.dumps(
            {
                "model_id": arguments.model_id,
                "revision": arguments.revision,
                "digest": digest,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return 0


def _tree_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(
        file
        for file in directory.rglob("*")
        if file.is_file() and ".cache" not in file.relative_to(directory).parts
    ):
        if path.name == "metadata.json":
            continue
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
