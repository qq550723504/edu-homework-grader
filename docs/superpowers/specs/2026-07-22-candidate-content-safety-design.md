# Candidate Content-Safety Verification Design

## Goal

Extend Issue #40's immutable candidate-verification pipeline with a local, versioned and explainable policy gate for content that is plainly unsuitable for minors, discriminatory in a harmful way, or directly asks to reproduce protected material. The gate evaluates generated candidate text only. It never sends candidate text to an external moderation service, never creates a `QuestionVersion`, and never replaces the broader governance work in Issue #43.

## Root Cause and Boundary

`question_verification.py` currently reduces safety checking to four English substring pairs. It neither distinguishes an educational mention from harmful instruction nor provides a policy version, stable rule identifier, Chinese coverage, separator-variant coverage, warning tier, or copyright-reproduction boundary.

Issue #40 owns deterministic candidate-time checks. This slice checks `prompt`, `explanation`, optional `reading_material`, and textual rule values, because those are the candidate fields already inspected by the verification pipeline. Issue #43 remains the authority for teacher-request interception, source licensing, provider data handling, rights-holder takedowns, model/prompt governance, and audit operations. Semantic copyright similarity remains the existing duplicate detector; this slice only catches direct reproduction instructions embedded in a candidate.

## Chosen Approach

Use a small local policy module built on Python's standard-library Unicode normalization and compiled regular expressions. The rules are versioned application policy, not a claim that a keyword list is a complete moderation system.

An optional local model could complement this later, but no current dependency provides reliable coverage of adult content, self-harm methods, graphic violence, discriminatory assertions, age suitability and copyright reproduction as one auditable policy. Detoxify is useful for toxicity, threats, obscenity and identity attacks, but has a heavy Torch/Transformers model stack and does not establish the missing minor-safety or copyright conditions by itself. It therefore belongs behind Issue #42 evaluation and Issue #43 model-governance approval, not as a bypass for this deterministic gate.

## Policy Semantics

`services/candidate_content_policy.py` exposes one public, deterministic interface:

```python
CONTENT_POLICY_VERSION = "minor-content-policy-v1"

@dataclass(frozen=True)
class ContentPolicyMatch:
    code: str
    severity: Literal["warning", "blocked"]
    category: str
    rule_id: str
    remediation: str

def find_candidate_content_matches(texts: Iterable[str]) -> tuple[ContentPolicyMatch, ...]: ...
```

The scanner performs NFKC normalization and `casefold`, then evaluates bounded regular expressions against a whitespace-normalized form and a separator-collapsed form. This catches ordinary casing, full-width punctuation, and spacing/punctuation evasion without attempting unsafe transliteration or probabilistic semantic inference. Rules use explicit boundaries for Latin words; Chinese rules are explicit phrases. A match contains only a policy category and rule identifier, never text, offsets, snippets, or normalized content.

Rules are ordered by a stable `rule_id`, deduplicated per `(code, category, rule_id)`, and every match is returned. This produces deterministic findings even when several different categories appear in one candidate.

| Finding code | Severity | Categories | Intended treatment |
| --- | --- | --- | --- |
| `unsafe_minor_content` | blocked | `adult_content`, `self_harm_instruction`, `graphic_violence`, `unsafe_instruction`, `hate_or_bias` | Directly unsafe or discriminatory candidate content cannot enter teacher review. |
| `mature_theme_requires_review` | warning | `substance_use`, `gambling`, `non_graphic_death_or_trauma` | Potentially legitimate health, history or civic education material; teacher review remains required. |
| `copyright_reproduction_risk` | blocked | `direct_reproduction_request` | A candidate directly instructs copying a named textbook page, full passage, or protected question bank. |

The `hate_or_bias` rules require a demeaning, exclusionary, or inferiority assertion associated with a protected-class reference. They must not match neutral identity references, factual history, or anti-bias discussion. Similarly, self-harm rules require method/instruction language rather than a neutral support-oriented reference. These boundaries are regression-tested.

## Integration and Persistence

`question_verification._safety_findings` becomes a thin adapter over the policy module. For every `ContentPolicyMatch`, it emits the existing immutable `VerificationFinding` contract:

```python
VerificationFinding(
    code=match.code,
    severity=ValidationFindingSeverity(match.severity),
    evidence={
        "category": match.category,
        "rule_id": match.rule_id,
        "policy_version": CONTENT_POLICY_VERSION,
    },
    remediation=match.remediation,
)
```

The verifier and ruleset versions advance from `verification-v3` / `rules-v3` to `verification-v4` / `rules-v4`. `_persist_run` includes the fixed `content_policy_version` in `feature_summary_json`; this changes no table and preserves append-only historical runs. A rule match blocks or warns through the existing `_status_for` behavior. Existing routing and teacher-review interfaces already return immutable finding evidence, so no API contract or migration is required.

## Non-goals

- no hosted moderation API, content upload, model download, or new processor;
- no claim of semantic moderation completeness or automatic censorship of neutral curriculum discussion;
- no teacher-request input filter, licence record, takedown workflow, model approval, or provider configuration change from Issue #43;
- no automatic publication, acceptance bypass, database schema change, or raw-content persistence in evidence;
- no changes to duplicate detection, grading policies, or Grader service behavior.

## Test Matrix

Tests use candidates through `run_candidate_verification`, plus focused unit tests for the policy module.

1. Unicode/case/separator variants of each blocked category create a blocked run with only `category`, `rule_id`, and `policy_version` evidence.
2. A candidate containing two blocked categories returns both stable findings in policy order without echoing its text.
3. Mature themes produce warning-only runs; neutral educational and support-oriented text produces no safety finding.
4. Direct textbook/page, full-passage, and protected-question-bank reproduction requests block; a generic original exercise request does not.
5. A neutral protected-class reference and anti-bias lesson do not trigger `hate_or_bias`; a directed demeaning assertion does.
6. Existing unsafe-content coverage remains compatible at the public code level, while newly persisted evidence gains the rule and policy identifiers.
7. Persisted runs contain `verification-v4`, `rules-v4`, and `content_policy_version`; no evidence, remediation, or feature summary includes candidate text.

## Documentation and Operations

`docs/ai-question-generation-plan.md` will state the exact deterministic scope, warning/block behavior, and the handoff to #42/#43. The policy module will be intentionally small and commented as a reviewed baseline: changing a pattern, category, severity or remediation requires a policy-version increment, a regression case, and #42 evaluation before it becomes default.

## Self-Review

The design directly repairs the current four-substring root cause while preserving verification, persistence and publication boundaries. It uses mature local building blocks rather than introducing a custom model, makes false-positive-sensitive categories warnings or narrowly contextualized rules, and explicitly leaves governance obligations to Issue #43. Every persisted value is non-sensitive and versioned.
