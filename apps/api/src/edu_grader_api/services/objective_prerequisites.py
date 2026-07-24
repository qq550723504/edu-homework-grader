"""Versioned, de-identified objective-prerequisite alignment signals."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    CurriculumObjective,
    CurriculumObjectiveRevision,
    CurriculumPrerequisite,
    CurriculumProfileStatus,
)

OBJECTIVE_PREREQUISITE_RULESET_VERSION = "objective-prerequisite-v1"

Resolution = Literal[
    "target",
    "prerequisite",
    "out_of_scope",
    "ambiguous",
    "unresolved",
    "graph_invalid",
]
FindingSeverity = Literal["warning", "blocked"]

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class ObjectivePrerequisiteFinding:
    code: str
    severity: FindingSeverity
    evidence: dict[str, object]
    remediation: str


@dataclass(frozen=True, slots=True)
class ObjectivePrerequisiteEvaluation:
    target_objective_code: str
    resolution: Resolution
    candidate_alias_digest: str | None
    matched_objective_code: str | None
    prerequisite_depth: int | None
    allowed_objective_count: int
    prerequisite_revision_count: int
    findings: tuple[ObjectivePrerequisiteFinding, ...]

    def feature_summary(self) -> dict[str, object]:
        return {
            "availability": "available",
            "version": OBJECTIVE_PREREQUISITE_RULESET_VERSION,
            "target_objective_code": self.target_objective_code,
            "resolution": self.resolution,
            "candidate_alias_digest": self.candidate_alias_digest,
            "matched_objective_code": self.matched_objective_code,
            "prerequisite_depth": self.prerequisite_depth,
            "allowed_objective_count": self.allowed_objective_count,
            "prerequisite_revision_count": self.prerequisite_revision_count,
        }


def evaluate_objective_prerequisite_alignment(
    session: Session,
    *,
    target_revision: CurriculumObjectiveRevision,
    candidate_knowledge_point: object,
) -> ObjectivePrerequisiteEvaluation:
    """Resolve a candidate claim against an immutable prerequisite closure.

    Only objective codes, graph counts, a coarse resolution, and a normalized
    alias digest are returned. Curriculum text and the candidate's raw claim
    are never persisted in the evaluation signal or findings.
    """

    target_objective = target_revision.objective
    candidate_alias = (
        _normalize_alias(candidate_knowledge_point)
        if isinstance(candidate_knowledge_point, str)
        else ""
    )
    candidate_alias_digest = _alias_digest(candidate_alias)

    closure, depths, graph_invalid_reason = _prerequisite_closure(
        session, target_revision_id=target_revision.id
    )
    if graph_invalid_reason is not None:
        evidence = {
            "ruleset_version": OBJECTIVE_PREREQUISITE_RULESET_VERSION,
            "target_objective_code": target_objective.code,
            "reason": graph_invalid_reason,
        }
        return ObjectivePrerequisiteEvaluation(
            target_objective_code=target_objective.code,
            resolution="graph_invalid",
            candidate_alias_digest=candidate_alias_digest,
            matched_objective_code=None,
            prerequisite_depth=None,
            allowed_objective_count=1,
            prerequisite_revision_count=max(len(closure) - 1, 0),
            findings=(
                ObjectivePrerequisiteFinding(
                    code="objective_prerequisite_graph_invalid",
                    severity="blocked",
                    evidence=evidence,
                    remediation=(
                        "Correct the curriculum prerequisite graph before validating candidates."
                    ),
                ),
            ),
        )

    revisions = list(
        session.scalars(
            select(CurriculumObjectiveRevision).where(CurriculumObjectiveRevision.id.in_(closure))
        )
    )
    if len(revisions) != len(closure):
        evidence = {
            "ruleset_version": OBJECTIVE_PREREQUISITE_RULESET_VERSION,
            "target_objective_code": target_objective.code,
            "reason": "revision_missing",
        }
        return ObjectivePrerequisiteEvaluation(
            target_objective_code=target_objective.code,
            resolution="graph_invalid",
            candidate_alias_digest=candidate_alias_digest,
            matched_objective_code=None,
            prerequisite_depth=None,
            allowed_objective_count=1,
            prerequisite_revision_count=max(len(closure) - 1, 0),
            findings=(
                ObjectivePrerequisiteFinding(
                    code="objective_prerequisite_graph_invalid",
                    severity="blocked",
                    evidence=evidence,
                    remediation=(
                        "Correct the curriculum prerequisite graph before validating candidates."
                    ),
                ),
            ),
        )

    allowed_objective_depths: dict[UUID, int] = {}
    for revision in revisions:
        depth = depths[revision.id]
        previous = allowed_objective_depths.get(revision.objective_id)
        if previous is None or depth < previous:
            allowed_objective_depths[revision.objective_id] = depth

    objectives = list(
        session.scalars(
            select(CurriculumObjective).where(
                CurriculumObjective.profile_id == target_objective.profile_id,
                CurriculumObjective.status == CurriculumProfileStatus.ACTIVE,
            )
        )
    )
    objectives_by_id = {objective.id: objective for objective in objectives}
    objectives_by_id[target_objective.id] = target_objective

    aliases: dict[str, set[UUID]] = defaultdict(set)
    for objective in objectives_by_id.values():
        for value in (objective.code, objective.knowledge_point):
            alias = _normalize_alias(value) if isinstance(value, str) else ""
            if alias:
                aliases[alias].add(objective.id)

    matched_ids = aliases.get(candidate_alias, set()) if candidate_alias else set()
    mapping_enforced = bool(
        _normalize_alias(target_objective.knowledge_point)
        if isinstance(target_objective.knowledge_point, str)
        else ""
    )
    common_evidence = {
        "ruleset_version": OBJECTIVE_PREREQUISITE_RULESET_VERSION,
        "target_objective_code": target_objective.code,
        "candidate_alias_digest": candidate_alias_digest,
    }

    if len(matched_ids) == 1:
        matched_id = next(iter(matched_ids))
        matched_objective = objectives_by_id[matched_id]
        if matched_id in allowed_objective_depths:
            depth = allowed_objective_depths[matched_id]
            return ObjectivePrerequisiteEvaluation(
                target_objective_code=target_objective.code,
                resolution="target" if depth == 0 else "prerequisite",
                candidate_alias_digest=candidate_alias_digest,
                matched_objective_code=matched_objective.code,
                prerequisite_depth=depth,
                allowed_objective_count=len(allowed_objective_depths),
                prerequisite_revision_count=max(len(closure) - 1, 0),
                findings=(),
            )
        evidence = {
            **common_evidence,
            "matched_objective_code": matched_objective.code,
            "allowed_objective_count": len(allowed_objective_depths),
        }
        return ObjectivePrerequisiteEvaluation(
            target_objective_code=target_objective.code,
            resolution="out_of_scope",
            candidate_alias_digest=candidate_alias_digest,
            matched_objective_code=matched_objective.code,
            prerequisite_depth=None,
            allowed_objective_count=len(allowed_objective_depths),
            prerequisite_revision_count=max(len(closure) - 1, 0),
            findings=(
                ObjectivePrerequisiteFinding(
                    code="objective_prerequisite_out_of_scope",
                    severity="blocked",
                    evidence=evidence,
                    remediation=(
                        "Regenerate the candidate using only the target objective and its approved prerequisites."
                    ),
                ),
            ),
        )

    if len(matched_ids) > 1:
        evidence = {**common_evidence, "match_count": len(matched_ids)}
        return ObjectivePrerequisiteEvaluation(
            target_objective_code=target_objective.code,
            resolution="ambiguous",
            candidate_alias_digest=candidate_alias_digest,
            matched_objective_code=None,
            prerequisite_depth=None,
            allowed_objective_count=len(allowed_objective_depths),
            prerequisite_revision_count=max(len(closure) - 1, 0),
            findings=(
                ObjectivePrerequisiteFinding(
                    code="objective_prerequisite_ambiguous",
                    severity="warning",
                    evidence=evidence,
                    remediation=(
                        "Use the exact curriculum objective code or a unique approved knowledge-point label."
                    ),
                ),
            ),
        )

    findings: tuple[ObjectivePrerequisiteFinding, ...] = ()
    if mapping_enforced and candidate_alias:
        findings = (
            ObjectivePrerequisiteFinding(
                code="objective_prerequisite_unresolved",
                severity="warning",
                evidence=common_evidence,
                remediation=(
                    "Use the target objective code or an approved prerequisite knowledge-point label."
                ),
            ),
        )
    return ObjectivePrerequisiteEvaluation(
        target_objective_code=target_objective.code,
        resolution="unresolved",
        candidate_alias_digest=candidate_alias_digest,
        matched_objective_code=None,
        prerequisite_depth=None,
        allowed_objective_count=len(allowed_objective_depths),
        prerequisite_revision_count=max(len(closure) - 1, 0),
        findings=findings,
    )


def unavailable_objective_prerequisite_signal(reason: str) -> dict[str, object]:
    return {
        "availability": "unavailable",
        "version": OBJECTIVE_PREREQUISITE_RULESET_VERSION,
        "target_objective_code": None,
        "resolution": None,
        "candidate_alias_digest": None,
        "matched_objective_code": None,
        "prerequisite_depth": None,
        "allowed_objective_count": 0,
        "prerequisite_revision_count": 0,
        "reason": reason,
    }


def _prerequisite_closure(
    session: Session, *, target_revision_id: UUID
) -> tuple[set[UUID], dict[UUID, int], str | None]:
    discovered = {target_revision_id}
    depths = {target_revision_id: 0}
    pending: deque[UUID] = deque([target_revision_id])
    adjacency: dict[UUID, list[UUID]] = defaultdict(list)

    while pending:
        batch: list[UUID] = []
        while pending and len(batch) < 128:
            batch.append(pending.popleft())
        rows = session.execute(
            select(
                CurriculumPrerequisite.objective_revision_id,
                CurriculumPrerequisite.prerequisite_revision_id,
            ).where(CurriculumPrerequisite.objective_revision_id.in_(batch))
        )
        for objective_revision_id, prerequisite_revision_id in rows:
            adjacency[objective_revision_id].append(prerequisite_revision_id)
            next_depth = depths[objective_revision_id] + 1
            if prerequisite_revision_id not in discovered:
                discovered.add(prerequisite_revision_id)
                depths[prerequisite_revision_id] = next_depth
                pending.append(prerequisite_revision_id)
            elif next_depth < depths[prerequisite_revision_id]:
                depths[prerequisite_revision_id] = next_depth

    if _has_cycle(adjacency, discovered):
        return discovered, depths, "cycle_detected"
    return discovered, depths, None


def _has_cycle(adjacency: dict[UUID, list[UUID]], nodes: set[UUID]) -> bool:
    colors: dict[UUID, int] = {}
    for root in nodes:
        if colors.get(root, 0) != 0:
            continue
        stack: list[tuple[UUID, bool]] = [(root, False)]
        while stack:
            node, exiting = stack.pop()
            if exiting:
                colors[node] = 2
                continue
            color = colors.get(node, 0)
            if color == 1:
                return True
            if color == 2:
                continue
            colors[node] = 1
            stack.append((node, True))
            for prerequisite_id in reversed(adjacency.get(node, [])):
                prerequisite_color = colors.get(prerequisite_id, 0)
                if prerequisite_color == 1:
                    return True
                if prerequisite_color == 0:
                    stack.append((prerequisite_id, False))
    return False


def _normalize_alias(value: str) -> str:
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", value).casefold()).strip()


def _alias_digest(value: str) -> str | None:
    if not value:
        return None
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"
