from edu_grader_api.services.question_fingerprints import (
    FINGERPRINT_VERSION,
    fingerprint_prompt,
    normalize_prompt,
)


def test_normalize_prompt_applies_unicode_whitespace_and_case_normalization() -> None:
    assert normalize_prompt("  Ｈｅｌｌｏ\t世界\n") == "hello 世界"


def test_fingerprint_prompt_keeps_raw_unicode_hash_and_normalized_hash_distinct() -> None:
    fingerprints = fingerprint_prompt("  Ｈｅｌｌｏ\t世界\n")

    assert fingerprints.version == FINGERPRINT_VERSION == "question-fingerprint-v1"
    assert (
        fingerprints.exact_hash
        == "687e9808bcc3ac9ff6f01158bb62da1c3c6a416704336432e7fb87433b1d5968"
    )
    assert (
        fingerprints.normalized_hash
        == "2e2625f7c51b4a2c75274ab307e86411f57aab475f4a4078df53533f7771bc7f"
    )
