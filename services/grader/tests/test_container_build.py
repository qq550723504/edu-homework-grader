from pathlib import Path


DOCKERFILE_PATH = Path(__file__).parents[1] / "Dockerfile"


def test_grader_dockerfile_prefetches_model_before_copying_application_source() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert dockerfile.index("RUN python scripts/prefetch_english_model.py") < dockerfile.index(
        "COPY services/grader/src ./src"
    )


def test_grader_dockerfile_installs_runtime_package_without_dependencies() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "RUN python -m pip install --no-deps ." in dockerfile


def test_grader_dockerfile_installs_cpu_only_pytorch() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "--index-url https://download.pytorch.org/whl/cpu torch==2.13.0+cpu" in dockerfile
    assert "PIP_CONSTRAINT=/tmp/torch-constraints.txt" in dockerfile
