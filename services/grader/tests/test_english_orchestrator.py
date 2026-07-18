from edu_grader.english_dependencies import GrammarMatch, StaticSimilarity
from edu_grader.english_orchestrator import NoopGrammarChecker, StaticGrammarChecker, grade_english


def test_e4_high_similarity_without_scoring_point_evidence_stays_review_zero() -> None:
    result = grade_english(
        {
            "question_type": "E4",
            "policy_version": "2",
            "rule": {
                "scoring_points": [
                    {"id": "cause", "evidence_phrases": ["bridge closed"], "score": 1}
                ],
                "similarity_threshold": 0.78,
                "max_score": 1,
            },
            "answer": {"answer": "The road closure delayed them."},
        },
        grammar_checker=NoopGrammarChecker(),
        similarity=StaticSimilarity(0.95),
    )

    assert (result.decision, result.score, result.requires_review) == ("needs_review", 0, True)
    assert result.criteria[0].evidence == "no scoring-point evidence matched"
    assert result.signals[0]["highest_similarity"] == 0.95


def test_e3_returns_structured_grammar_feedback_without_rejecting_answer() -> None:
    result = grade_english(
        {
            "question_type": "E3",
            "policy_version": "1",
            "rule": {"grammar_feedback_required": True, "max_score": 1},
            "answer": {"answer": "She go home."},
        },
        grammar_checker=StaticGrammarChecker(
            [
                GrammarMatch(
                    offset=4,
                    length=2,
                    rule_id="AGREEMENT",
                    category="GRAMMAR",
                    issue_type="grammar",
                    message="Use goes",
                    replacements=["goes"],
                )
            ]
        ),
        similarity=StaticSimilarity(0),
    )

    assert result.decision == "needs_review"
    assert result.feedback[0].type == "grammar"
    assert result.feedback[0].offset == 4
    assert result.feedback[0].replacements == ["goes"]
