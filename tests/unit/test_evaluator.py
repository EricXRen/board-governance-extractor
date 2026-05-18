"""Unit tests for the evaluation loop (director matching + document-level fields)."""

from __future__ import annotations

import pytest

from gov_extract.evaluation.evaluator import (
    DocumentResult,
    _evaluate_document_fields,
    _filter_new_candidates,
    evaluate,
)
from gov_extract.models.board_summary import BoardSummary
from gov_extract.models.director import AttendanceDetails, BiographicalDetails, BoardRoleDetails, Director
from gov_extract.models.director_election import DirectorElection, DirectorElectionSummary
from gov_extract.models.document import Board, BoardGovernanceDocument
from gov_extract.models.metadata import CompanyMetadata


def _make_candidate(name: str) -> Director:
    return Director(
        biographical=BiographicalDetails(full_name=name),
        board_role=BoardRoleDetails(
            designation="Non-Executive Director",
            board_role="NED",
            independence_status="Independent",
            year_end_status="Active",
        ),
        attendance=AttendanceDetails(),
    )


def _make_doc(
    voting_standard: str | None = None,
    board_evaluation: bool | None = None,
    board_size: int | None = None,
    pct_women: float | None = None,
    num_directors_to_elect: int | None = None,
    incumbent_nominees: list[str] | None = None,
    new_nominees: list[str] | None = None,
    candidates: list[Director] | None = None,
) -> BoardGovernanceDocument:
    summary = BoardSummary(
        voting_standard=voting_standard,  # type: ignore[arg-type]
        board_evaluation=board_evaluation,
        board_size=board_size,
        pct_women=pct_women,
    )
    election: DirectorElection | None = None
    if num_directors_to_elect is not None or incumbent_nominees or new_nominees or candidates:
        election = DirectorElection(
            summary=DirectorElectionSummary(
                num_directors_to_elect=num_directors_to_elect,
                incumbent_nominees=incumbent_nominees or [],
                new_nominees=new_nominees or [],
            ),
            candidates=candidates or [],
        )
    return BoardGovernanceDocument(
        company=CompanyMetadata(
            company_name="Test Co",
            filing_type="Annual Report",
            fiscal_year_end="2025-12-31",
            source_pdf_path="/tmp/test.pdf",
            extraction_timestamp="2025-01-01T00:00:00+00:00",
            llm_provider="anthropic",
            llm_model="claude-sonnet-4-6",
        ),
        current_board=Board(summary=summary),
        director_election=election,
    )


_DOC_FIELD_METRICS = {
    "current_board.summary.voting_standard": "exact_match",
    "current_board.summary.board_evaluation": "exact_match",
    "current_board.summary.board_size": "numeric_error",
    "current_board.summary.pct_women": "numeric_error",
    "director_election.summary.num_directors_to_elect": "numeric_error",
    "director_election.summary.incumbent_nominees": "list_f1",
    "director_election.summary.new_nominees": "list_f1",
}

_THRESHOLDS = {
    "fuzzy_match": 90.0,
    "list_f1": 0.90,
    "semantic_similarity": 0.80,
    "numeric_error_tolerance": 0.05,
}


class TestEvaluateDocumentFields:
    def test_all_matching(self) -> None:
        doc = _make_doc(
            voting_standard="Majority",
            board_evaluation=True,
            board_size=10,
            pct_women=30.0,
            num_directors_to_elect=3,
            incumbent_nominees=["Alice", "Bob"],
            new_nominees=["Carol"],
        )
        results = _evaluate_document_fields(doc, doc, _DOC_FIELD_METRICS, _THRESHOLDS)
        assert len(results) == 7
        assert all(fr.passed for fr in results)

    def test_voting_standard_mismatch(self) -> None:
        ext = _make_doc(voting_standard="Plurality")
        gt = _make_doc(voting_standard="Majority")
        results = _evaluate_document_fields(ext, gt, _DOC_FIELD_METRICS, _THRESHOLDS)
        voting_result = next(r for r in results if r.field_path == "current_board.summary.voting_standard")
        assert not voting_result.passed
        assert voting_result.failure_mode == "below_threshold"

    def test_board_evaluation_false_negative(self) -> None:
        ext = _make_doc(board_evaluation=None)
        gt = _make_doc(board_evaluation=True)
        results = _evaluate_document_fields(ext, gt, _DOC_FIELD_METRICS, _THRESHOLDS)
        be_result = next(r for r in results if r.field_path == "current_board.summary.board_evaluation")
        assert not be_result.passed
        assert be_result.failure_mode == "false_negative"

    def test_election_nominees_list_f1(self) -> None:
        ext = _make_doc(incumbent_nominees=["Alice", "Bob"], new_nominees=["Carol"])
        gt = _make_doc(incumbent_nominees=["Alice", "Bob", "Dave"], new_nominees=["Carol"])
        results = _evaluate_document_fields(ext, gt, _DOC_FIELD_METRICS, _THRESHOLDS)
        inc_result = next(r for r in results if r.field_path == "director_election.summary.incumbent_nominees")
        # Recall = 2/3 ≈ 0.67, below list_f1 threshold of 0.90
        assert not inc_result.passed

    def test_null_election_fields_both_absent(self) -> None:
        ext = _make_doc()  # no election
        gt = _make_doc()   # no election
        results = _evaluate_document_fields(ext, gt, _DOC_FIELD_METRICS, _THRESHOLDS)
        election_results = [r for r in results if r.field_path.startswith("director_election")]
        assert all(fr.passed for fr in election_results)

    def test_empty_document_field_metrics(self) -> None:
        doc = _make_doc(voting_standard="Majority")
        results = _evaluate_document_fields(doc, doc, {}, _THRESHOLDS)
        assert results == []


class TestEvaluateWithDocumentFields:
    def test_document_field_results_populated(self) -> None:
        doc = _make_doc(voting_standard="Majority", board_size=10)
        result: DocumentResult = evaluate(
            doc, doc, {}, _THRESHOLDS,
            document_field_metrics=_DOC_FIELD_METRICS,
        )
        assert len(result.document_field_results) == 7

    def test_document_fields_contribute_to_pass_rate(self) -> None:
        ext = _make_doc(voting_standard="Plurality", board_size=10)
        gt = _make_doc(voting_standard="Majority", board_size=10)
        # voting_standard will fail; everything else matches (or both null)
        result = evaluate(
            ext, gt, {}, _THRESHOLDS,
            document_field_metrics={"current_board.summary.voting_standard": "exact_match"},
        )
        assert result.document_field_pass_rate < 1.0
        assert "current_board.summary.voting_standard" in result.per_field_pass_rate

    def test_no_document_field_metrics_backward_compat(self) -> None:
        doc = _make_doc()
        result = evaluate(doc, doc, {}, _THRESHOLDS)
        assert result.document_field_results == []

    def test_document_perfect_match_requires_doc_fields(self) -> None:
        ext = _make_doc(board_evaluation=False)
        gt = _make_doc(board_evaluation=True)
        result = evaluate(
            ext, gt, {}, _THRESHOLDS,
            document_field_metrics={"current_board.summary.board_evaluation": "exact_match"},
        )
        assert not result.document_perfect_match


_DIRECTOR_FIELD_METRICS = {
    "biographical.full_name": "exact_match",
    "board_role.independence_status": "exact_match",
}


class TestElectionCandidateResults:
    def test_filter_new_candidates_basic(self) -> None:
        alice = _make_candidate("Alice Smith")
        bob = _make_candidate("Bob Jones")  # incumbent
        carol = _make_candidate("Carol White")
        result = _filter_new_candidates([alice, bob, carol], ["Alice Smith", "Carol White"])
        names = [d.biographical.full_name for d in result]
        assert "Alice Smith" in names
        assert "Carol White" in names
        assert "Bob Jones" not in names

    def test_filter_new_candidates_case_insensitive(self) -> None:
        # Matching is case-insensitive (fuzzy ratio normalises to lower)
        candidate = _make_candidate("ALICE SMITH")
        result = _filter_new_candidates([candidate], ["Alice Smith"])
        assert len(result) == 1

    def test_filter_new_candidates_empty_nominees(self) -> None:
        alice = _make_candidate("Alice Smith")
        result = _filter_new_candidates([alice], [])
        assert result == []

    def test_filter_new_candidates_empty_candidates(self) -> None:
        result = _filter_new_candidates([], ["Alice Smith"])
        assert result == []

    def test_evaluate_new_candidates_matching(self) -> None:
        carol = _make_candidate("Carol White")
        doc = _make_doc(new_nominees=["Carol White"], candidates=[carol])
        result = evaluate(doc, doc, _DIRECTOR_FIELD_METRICS, _THRESHOLDS)
        assert len(result.election_candidate_results) == 1
        assert result.election_candidate_results[0].director_name == "Carol White"
        assert result.election_candidate_results[0].matched

    def test_evaluate_incumbent_excluded(self) -> None:
        alice = _make_candidate("Alice Smith")   # incumbent re-standing
        carol = _make_candidate("Carol White")   # new
        doc = _make_doc(
            incumbent_nominees=["Alice Smith"],
            new_nominees=["Carol White"],
            candidates=[alice, carol],
        )
        result = evaluate(doc, doc, _DIRECTOR_FIELD_METRICS, _THRESHOLDS)
        names = [dr.director_name for dr in result.election_candidate_results]
        assert "Carol White" in names
        assert "Alice Smith" not in names

    def test_evaluate_candidate_false_negative(self) -> None:
        carol = _make_candidate("Carol White")
        ext = _make_doc(new_nominees=[], candidates=[])       # model missed carol
        gt = _make_doc(new_nominees=["Carol White"], candidates=[carol])
        result = evaluate(ext, gt, _DIRECTOR_FIELD_METRICS, _THRESHOLDS)
        # GT carol is unmatched → one unmatched result
        assert len(result.election_candidate_results) == 1
        assert not result.election_candidate_results[0].matched

    def test_evaluate_no_election_returns_empty(self) -> None:
        doc = _make_doc()  # no election
        result = evaluate(doc, doc, _DIRECTOR_FIELD_METRICS, _THRESHOLDS)
        assert result.election_candidate_results == []

    def test_candidate_fields_contribute_to_pass_rate(self) -> None:
        carol_ext = _make_candidate("Carol White")
        carol_gt = _make_candidate("Carol White")
        ext = _make_doc(new_nominees=["Carol White"], candidates=[carol_ext])
        gt = _make_doc(new_nominees=["Carol White"], candidates=[carol_gt])
        result = evaluate(ext, gt, _DIRECTOR_FIELD_METRICS, _THRESHOLDS)
        assert "biographical.full_name" in result.per_field_pass_rate

    def test_document_perfect_match_requires_candidates(self) -> None:
        carol_ext = _make_candidate("Carol White")
        carol_gt = _make_candidate("Carol White")
        # Make carol_ext differ on independence_status from carol_gt
        from gov_extract.models.director import BoardRoleDetails
        carol_ext = Director(
            biographical=BiographicalDetails(full_name="Carol White"),
            board_role=BoardRoleDetails(
                designation="Non-Executive Director",
                board_role="NED",
                independence_status="Not Independent",  # differs from GT
                year_end_status="Active",
            ),
            attendance=AttendanceDetails(),
        )
        ext = _make_doc(new_nominees=["Carol White"], candidates=[carol_ext])
        gt = _make_doc(new_nominees=["Carol White"], candidates=[carol_gt])
        result = evaluate(ext, gt, _DIRECTOR_FIELD_METRICS, _THRESHOLDS)
        assert not result.document_perfect_match
