from fastapi.testclient import TestClient

import edu_grader.main as main


class FakeSimilarity:
    instances = 0

    def __init__(self, *args: object, **kwargs: object) -> None:
        type(self).instances += 1

    def score(self, left: str, right: str) -> float:
        return 1.0


class FakeGrammarChecker:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def check(self, text: str) -> list[object]:
        return []


def test_english_similarity_is_loaded_once_and_reported_ready(monkeypatch) -> None:
    FakeSimilarity.instances = 0
    monkeypatch.setattr(main, "SentenceTransformerSimilarity", FakeSimilarity)
    monkeypatch.setattr(main, "LanguageToolClient", FakeGrammarChecker)
    monkeypatch.setattr(
        main,
        "_runtime_dependency_versions",
        lambda: {"sentence-transformers": "test-version"},
        raising=False,
    )
    monkeypatch.setenv("ENGLISH_EMBEDDING_MODEL_ID", "test-model")
    monkeypatch.setenv("ENGLISH_EMBEDDING_MODEL_REVISION", "test-revision")
    monkeypatch.setenv("ENGLISH_EMBEDDING_MODEL_DIGEST", "sha256:test-digest")

    payload = {
        "question_type": "E1",
        "policy_version": "2",
        "rule": {},
        "answer": {"answer": "answer"},
    }
    with TestClient(main.app) as client:
        first = client.post("/v1/grade/english", json=payload)
        assert first.status_code == 200
        assert first.json()["dependency_versions"] == {
            "embedding": {
                "id": "test-model",
                "revision": "test-revision",
                "digest": "sha256:test-digest",
            },
            "runtime": {"sentence-transformers": "test-version"},
        }
        assert client.post("/v1/grade/english", json=payload).status_code == 200
        assert client.get("/ready").json() == {
            "status": "ready",
            "english_embedding_model": "ready",
        }

    assert FakeSimilarity.instances == 1
