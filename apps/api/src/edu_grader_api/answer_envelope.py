from __future__ import annotations


class AnswerEnvelopeValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def normalize_answer_envelope(
    answer: dict[str, object], *, expected_format: str = "text-v1"
) -> dict[str, object]:
    if answer.get("format") != expected_format:
        raise AnswerEnvelopeValidationError(
            "unsupported_answer_envelope", "答案必须使用受支持的版本化协议。"
        )
    if expected_format == "mathjson-v1":
        return _normalize_mathjson_envelope(answer)
    if expected_format != "text-v1":
        raise AnswerEnvelopeValidationError(
            "unsupported_answer_envelope", "答案必须使用受支持的版本化协议。"
        )
    text = answer.get("text")
    if not isinstance(text, str):
        raise AnswerEnvelopeValidationError("invalid_text", "文本答案必须包含 text 字段。")
    return {"format": "text-v1", "text": text.strip()}


def _normalize_mathjson_envelope(answer: dict[str, object]) -> dict[str, object]:
    latex = answer.get("latex")
    if not isinstance(latex, str) or not latex.strip() or len(latex) > 2_000:
        raise AnswerEnvelopeValidationError("invalid_latex", "数学答案 LaTeX 无效或过长。")
    if "mathjson" not in answer:
        raise AnswerEnvelopeValidationError("missing_mathjson", "数学答案缺少 MathJSON。")
    return {
        "format": "mathjson-v1",
        "latex": latex,
        "mathjson": answer["mathjson"],
    }


def migrate_legacy_answer_envelope(answer: dict[str, object]) -> dict[str, object]:
    if answer.get("format") in {"text-v1", "mathjson-v1"}:
        return answer.copy()
    value = answer.get("value")
    if isinstance(value, str):
        return {"format": "text-v1", "text": value}
    nested = answer.get("answer")
    if isinstance(nested, str):
        return {"format": "text-v1", "text": nested}
    if isinstance(nested, dict) and nested.get("format") in {"text-v1", "mathjson-v1"}:
        return nested.copy()
    return answer.copy()
