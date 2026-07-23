from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Iterable, Mapping


GENERATED_QUESTION_CANDIDATES_SCHEMA_V1 = "generated_question_candidates-v1"
GENERATED_QUESTION_CANDIDATES_SCHEMA_V2 = "generated_question_candidates-v2"
ALL_ACTIVE_CURRICULUM_PROFILES = "all_active_curriculum_profiles"


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """Immutable, server-owned contract for a generation prompt version."""

    version: str
    system_instructions: str
    schema_version: str
    allowed_question_types: frozenset[str]
    profile_scope: str
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        normalized_metadata = {
            "allowed_question_types": sorted(self.allowed_question_types),
            "profile_scope": self.profile_scope,
            "schema_version": self.schema_version,
            "version": self.version,
        }
        payload = {
            "metadata": normalized_metadata,
            "system_instructions": self.system_instructions,
        }
        canonical = json.dumps(
            payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        object.__setattr__(
            self,
            "fingerprint",
            hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )


_GENERATOR_V1 = PromptTemplate(
    version="generator-v1",
    system_instructions=(
        "Generate de-identified candidate homework questions. "
        "E4 must return a nonblank generated reading_material containing every E4 "
        "evidence phrase; all other types must return reading_material null. "
        "Return only JSON conforming to the supplied schema."
    ),
    schema_version=GENERATED_QUESTION_CANDIDATES_SCHEMA_V1,
    allowed_question_types=frozenset({"M1", "M2", "E1", "E2", "E3", "E4"}),
    profile_scope=ALL_ACTIVE_CURRICULUM_PROFILES,
)

_GENERATOR_V2 = PromptTemplate(
    version="generator-v2",
    system_instructions=(
        "Generate de-identified candidate homework questions. "
        "For request.items, generate exactly one candidate for each ordered input item "
        "and return the candidates in the same order. Each candidate must use the same "
        "question_type and target the requested target_difficulty of its corresponding "
        "item; do not omit, add, reorder, or merge candidates. "
        "E4 must return a nonblank generated reading_material containing every E4 "
        "evidence phrase; all other types must return reading_material null. "
        "Return only JSON conforming to the supplied schema."
    ),
    schema_version=GENERATED_QUESTION_CANDIDATES_SCHEMA_V1,
    allowed_question_types=frozenset({"M1", "M2", "E1", "E2", "E3", "E4"}),
    profile_scope=ALL_ACTIVE_CURRICULUM_PROFILES,
)

_GENERATOR_V3 = PromptTemplate(
    version="generator-v3",
    system_instructions=(
        "Generate de-identified candidate homework questions. "
        "For request.items, generate exactly one candidate for each ordered input item "
        "and return the candidates in the same order. Each candidate must use the same "
        "question_type and target the requested target_difficulty of its corresponding "
        "item; do not omit, add, reorder, or merge candidates. "
        "For M1 and M2, return verification_assertions and end explanation with "
        "Final answer: followed exactly by final_answer_text; M2 must also return "
        "JSON-encoded final_answer_mathjson. "
        "E4 must return a nonblank generated reading_material containing every E4 "
        "evidence phrase; all other types must return reading_material null. "
        "Return only JSON conforming to the supplied schema."
    ),
    schema_version=GENERATED_QUESTION_CANDIDATES_SCHEMA_V2,
    allowed_question_types=frozenset({"M1", "M2", "E1", "E2", "E3", "E4"}),
    profile_scope=ALL_ACTIVE_CURRICULUM_PROFILES,
)

PROMPT_TEMPLATE_CATALOG: Mapping[str, PromptTemplate] = MappingProxyType(
    {
        _GENERATOR_V1.version: _GENERATOR_V1,
        _GENERATOR_V2.version: _GENERATOR_V2,
        _GENERATOR_V3.version: _GENERATOR_V3,
    }
)


def resolve_prompt_template(
    version: str, requested_question_types: Iterable[str]
) -> PromptTemplate:
    """Return a catalog template only when it covers every requested question type."""
    template = PROMPT_TEMPLATE_CATALOG.get(version)
    if template is None:
        raise ValueError("unknown prompt template version")

    requested_types = frozenset(requested_question_types)
    if not requested_types.issubset(template.allowed_question_types):
        raise ValueError("requested question types are not allowed by prompt template")
    return template
