"""Deterministic, reviewed content-policy baseline for generated candidates.

Changing a rule requires a policy-version increment and a regression case.
"""

from dataclasses import dataclass
import re
from typing import Iterable, Literal, Pattern
import unicodedata


CONTENT_POLICY_VERSION = "minor-content-policy-v1"

_UNSAFE_REMEDIATION = "Remove unsafe content before asking for teacher review."
_MATURE_THEME_REMEDIATION = "Revise the content or ask a teacher to review the mature theme."
_COPYRIGHT_REMEDIATION = (
    "Replace direct reproduction requests with original material before asking for teacher review."
)
_SEPARATORS = re.compile(r"[\W_]+", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")
_SELF_HARM_SUPPORT_PREFIX = re.compile(
    r"if\s+(?:a\s+)?(?:student|someone)\s+(?:searches|asks)\s+['\"]?\s*$"
)
_SELF_HARM_SUPPORT_PREFIX_COLLAPSED = re.compile(r"if(?:a)?(?:student|someone)(?:searches|asks)$")
_SELF_HARM_SUPPORT_SUFFIX = re.compile(
    r"^['\"]?,?\s*(?:explain\s+how\s+to\s+seek|direct\s+(?:them|the\s+reader)\s+to)\s+(?:immediate\s+)?help\b"
)
_SELF_HARM_SUPPORT_SUFFIX_COLLAPSED = re.compile(
    r"^(?:explainhowtoseek|direct(?:them|thereader)to)(?:immediate)?help"
)
_SELF_HARM_EDUCATIONAL_PREFIX = re.compile(r"(?:explain|discuss|describe)(?:\s+why)?\s+['\"]?\s*$")
_SELF_HARM_EDUCATIONAL_PREFIX_COLLAPSED = re.compile(r"(?:explain|discuss|describe)(?:why)?$")
_SELF_HARM_DANGER_AND_SUPPORT_SUFFIX = re.compile(
    r"^['\"]?\s+(?:is|are)\s+(?:dangerous|harmful|unsafe)\b"
    r".{0,80}\b(?:seek|get|find|contact)\s+(?:immediate\s+)?help\b"
)
_SELF_HARM_DANGER_AND_SUPPORT_SUFFIX_COLLAPSED = re.compile(
    r"^(?:is|are)(?:dangerous|harmful|unsafe)"
    r".{0,80}(?:seek|get|find|contact)(?:immediate)?help\b"
)
_ANTI_BIAS_PREFIX = re.compile(
    r"(?:reject|condemn)(?:\s+the)?(?:\s+(?:false|harmful))?\s+claim\s+that\s+$"
)
_ANTI_BIAS_PREFIX_COLLAPSED = re.compile(r"(?:reject|condemn)(?:the)?(?:false|harmful)?claimthat$")
_ANTI_BIAS_EDUCATIONAL_PREFIX = re.compile(
    r"(?:explain|discuss|analyze|evaluate)\s+why\s+(?:the\s+)?claim\s+that\s+$"
)
_ANTI_BIAS_EDUCATIONAL_PREFIX_COLLAPSED = re.compile(
    r"(?:explain|discuss|analyze|evaluate)why(?:the)?claimthat$"
)
_ANTI_BIAS_REJECTION_SUFFIX = re.compile(
    r"^\s+(?:is|are)\s+(?:false|wrong|harmful|untrue|a\s+myth)\b"
)
_ANTI_BIAS_REJECTION_SUFFIX_COLLAPSED = re.compile(
    r"^(?:is|are)(?:false|wrong|harmful|untrue|amyth)\b"
)


@dataclass(frozen=True)
class ContentPolicyMatch:
    code: str
    severity: Literal["warning", "blocked"]
    category: str
    rule_id: str
    remediation: str


@dataclass(frozen=True)
class _ContentPolicyRule:
    code: str
    severity: Literal["warning", "blocked"]
    category: str
    rule_id: str
    remediation: str
    patterns: tuple[Pattern[str], Pattern[str]]
    context_exclusion: Literal["anti_bias", "self_harm_support"] | None = None

    def as_match(self) -> ContentPolicyMatch:
        return ContentPolicyMatch(
            code=self.code,
            severity=self.severity,
            category=self.category,
            rule_id=self.rule_id,
            remediation=self.remediation,
        )


def _latin_patterns(normalized: str, collapsed: str) -> tuple[Pattern[str], Pattern[str]]:
    boundary = r"(?<![^\W_])"
    end_boundary = r"(?![^\W_])"
    return (
        re.compile(f"{boundary}(?:{normalized}){end_boundary}"),
        re.compile(f"{boundary}(?:{collapsed}){end_boundary}"),
    )


def _patterns(
    normalized: str,
    collapsed: str,
    *chinese_phrases: str,
    chinese_patterns: tuple[str, ...] = (),
) -> tuple[Pattern[str], Pattern[str]]:
    normal_latin, collapsed_latin = _latin_patterns(normalized, collapsed)
    if not chinese_phrases and not chinese_patterns:
        return normal_latin, collapsed_latin
    chinese = "|".join([*(re.escape(phrase) for phrase in chinese_phrases), *chinese_patterns])
    return (
        re.compile(f"(?:{normal_latin.pattern}|{chinese})"),
        re.compile(f"(?:{collapsed_latin.pattern}|{chinese})"),
    )


_RULES: tuple[_ContentPolicyRule, ...] = (
    _ContentPolicyRule(
        code="unsafe_minor_content",
        severity="blocked",
        category="adult_content",
        rule_id="adult-explicit-v1",
        remediation=_UNSAFE_REMEDIATION,
        patterns=_patterns(
            "(?:explicit adult content|pornographic|sexual content)",
            "(?:explicitadultcontent|pornographic|sexualcontent)",
            "露骨成人内容",
        ),
    ),
    _ContentPolicyRule(
        code="unsafe_minor_content",
        severity="blocked",
        category="self_harm_instruction",
        rule_id="self-harm-instruction-v1",
        remediation=_UNSAFE_REMEDIATION,
        patterns=_patterns(
            "(?:how to cut yourself|self-harm instructions)",
            "(?:howtocutyourself|selfharminstructions)",
            "如何自残",
        ),
        context_exclusion="self_harm_support",
    ),
    _ContentPolicyRule(
        code="unsafe_minor_content",
        severity="blocked",
        category="graphic_violence",
        rule_id="graphic-violence-v1",
        remediation=_UNSAFE_REMEDIATION,
        patterns=_patterns(
            "(?:graphic dismemberment|graphic violence)",
            "(?:graphicdismemberment|graphicviolence)",
            "血腥肢解",
        ),
    ),
    _ContentPolicyRule(
        code="unsafe_minor_content",
        severity="blocked",
        category="unsafe_instruction",
        rule_id="unsafe-instruction-v1",
        remediation=_UNSAFE_REMEDIATION,
        patterns=_patterns(
            "(?:instructions to )?build a bomb", "(?:instructionsto)?buildabomb", "制作炸弹"
        ),
    ),
    _ContentPolicyRule(
        code="unsafe_minor_content",
        severity="blocked",
        category="hate_or_bias",
        rule_id="hate-or-bias-v1",
        remediation=_UNSAFE_REMEDIATION,
        patterns=_patterns(
            "(?:disabled|black|jewish|muslim|gay) people are inferior",
            "(?:disabled|black|jewish|muslim|gay)peopleareinferior",
            "残疾人低人一等",
        ),
        context_exclusion="anti_bias",
    ),
    _ContentPolicyRule(
        code="mature_theme_requires_review",
        severity="warning",
        category="substance_use",
        rule_id="substance-use-v1",
        remediation=_MATURE_THEME_REMEDIATION,
        patterns=_patterns("drug use", "druguse", "吸毒"),
    ),
    _ContentPolicyRule(
        code="mature_theme_requires_review",
        severity="warning",
        category="gambling",
        rule_id="gambling-v1",
        remediation=_MATURE_THEME_REMEDIATION,
        patterns=_patterns("casino gambling", "casinogambling", "赌场赌博"),
    ),
    _ContentPolicyRule(
        code="mature_theme_requires_review",
        severity="warning",
        category="non_graphic_death_or_trauma",
        rule_id="non-graphic-death-or-trauma-v1",
        remediation=_MATURE_THEME_REMEDIATION,
        patterns=_patterns("death and grief", "deathandgrief", "死亡与悲伤"),
    ),
    _ContentPolicyRule(
        code="copyright_reproduction_risk",
        severity="blocked",
        category="direct_reproduction_request",
        rule_id="direct-reproduction-request-v1",
        remediation=_COPYRIGHT_REMEDIATION,
        patterns=_patterns(
            r"(?:copy|reproduce)\s+(?:(?:a|the)\s+)?(?:textbook\s+page\s+\d+|the\s+full\s+passage|the\s+protected\s+question\s+bank)(?:\s+verbatim)?",
            r"(?:copy|reproduce)(?:(?:a|the))?(?:textbookpage\d+|thefullpassage|theprotectedquestionbank)(?:verbatim)?",
            chinese_patterns=(r"抄写教材第\d+页",),
        ),
    ),
)


def _normalized_forms(texts: Iterable[str]) -> tuple[str, str]:
    normalized_texts = [
        _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", text).casefold()).strip()
        for text in texts
    ]
    collapsed_texts = [_SEPARATORS.sub("", text) for text in normalized_texts]
    return "\x00".join(normalized_texts), "\x00".join(collapsed_texts)


def _is_contextual_exclusion(
    context_exclusion: Literal["anti_bias", "self_harm_support"] | None,
    value: str,
    match: re.Match[str],
) -> bool:
    if context_exclusion is None:
        return False

    prefix = value[max(0, match.start() - 100) : match.start()]
    suffix = value[match.end() : match.end() + 100]
    if context_exclusion == "anti_bias":
        has_rejection_prefix = bool(
            _ANTI_BIAS_PREFIX.search(prefix) or _ANTI_BIAS_PREFIX_COLLAPSED.search(prefix)
        )
        has_educational_frame = bool(
            (
                _ANTI_BIAS_EDUCATIONAL_PREFIX.search(prefix)
                and _ANTI_BIAS_REJECTION_SUFFIX.search(suffix)
            )
            or (
                _ANTI_BIAS_EDUCATIONAL_PREFIX_COLLAPSED.search(prefix)
                and _ANTI_BIAS_REJECTION_SUFFIX_COLLAPSED.search(suffix)
            )
        )
        return has_rejection_prefix or has_educational_frame
    has_support_request = bool(
        (
            _SELF_HARM_SUPPORT_PREFIX.search(prefix)
            or _SELF_HARM_SUPPORT_PREFIX_COLLAPSED.search(prefix)
        )
        and (
            _SELF_HARM_SUPPORT_SUFFIX.search(suffix)
            or _SELF_HARM_SUPPORT_SUFFIX_COLLAPSED.search(suffix)
        )
    )
    has_educational_frame = bool(
        (
            _SELF_HARM_EDUCATIONAL_PREFIX.search(prefix)
            and _SELF_HARM_DANGER_AND_SUPPORT_SUFFIX.search(suffix)
        )
        or (
            _SELF_HARM_EDUCATIONAL_PREFIX_COLLAPSED.search(prefix)
            and _SELF_HARM_DANGER_AND_SUPPORT_SUFFIX_COLLAPSED.search(suffix)
        )
    )
    return has_support_request or has_educational_frame


def _has_unexcluded_match(
    pattern: Pattern[str],
    value: str,
    context_exclusion: Literal["anti_bias", "self_harm_support"] | None,
) -> bool:
    for match in pattern.finditer(value):
        if not _is_contextual_exclusion(context_exclusion, value, match):
            return True
    return False


def find_candidate_content_matches(texts: Iterable[str]) -> tuple[ContentPolicyMatch, ...]:
    normalized = _normalized_forms(texts)
    matches: list[ContentPolicyMatch] = []
    seen: set[tuple[str, str, str]] = set()
    for rule in _RULES:
        if any(
            _has_unexcluded_match(pattern, value, rule.context_exclusion)
            for pattern, value in zip(rule.patterns, normalized, strict=True)
        ):
            key = (rule.code, rule.category, rule.rule_id)
            if key not in seen:
                seen.add(key)
                matches.append(rule.as_match())
    return tuple(matches)
