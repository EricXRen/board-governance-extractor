"""Unit tests for Pydantic data models."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from gov_extract.models.director import (
    AttendanceDetails,
    BiographicalDetails,
    BoardRoleDetails,
    CommitteeAttendance,
    Director,
)
from gov_extract.models.director_election import DirectorElection, DirectorElectionSummary
from gov_extract.models.document import BoardGovernanceDocument, Board
from gov_extract.models.metadata import CompanyMetadata


def make_metadata(**kwargs: object) -> CompanyMetadata:
    defaults = dict(
        company_name="Test Co",
        filing_type="Annual Report",
        fiscal_year_end="2025-12-31",
        source_pdf_path="/tmp/test.pdf",
        extraction_timestamp="2025-01-01T00:00:00+00:00",
        llm_provider="anthropic",
        llm_model="claude-sonnet-4-6",
    )
    defaults.update(kwargs)
    return CompanyMetadata(**defaults)  # type: ignore[arg-type]


def make_director(**kwargs: object) -> Director:
    defaults: dict = dict(
        biographical=BiographicalDetails(full_name="Jane Smith"),
        board_role=BoardRoleDetails(
            designation="Non-Executive Director",
            board_role="NED",
            independence_status="Independent",
            year_end_status="Active",
        ),
        attendance=AttendanceDetails(),
    )
    defaults.update(kwargs)
    return Director(**defaults)


class TestCompanyMetadata:
    def test_valid(self) -> None:
        m = make_metadata()
        assert m.company_name == "Test Co"
        assert m.company_ticker is None

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            CompanyMetadata(  # type: ignore[call-arg]
                company_name="X",
                filing_type="AR",
                fiscal_year_end="2025-12-31",
                source_pdf_path="/tmp/x.pdf",
                extraction_timestamp="2025-01-01T00:00:00+00:00",
                llm_provider="openai",
                llm_model="gpt-4o",
                extra_field="oops",
            )

    def test_ticker_optional(self) -> None:
        m = make_metadata(company_ticker="LLOY.L")
        assert m.company_ticker == "LLOY.L"


class TestDirectorModels:
    def test_valid_director(self) -> None:
        d = make_director()
        assert d.biographical.full_name == "Jane Smith"
        assert d.attendance.board_meetings_attended is None

    def test_invalid_designation(self) -> None:
        with pytest.raises(ValidationError):
            BoardRoleDetails(
                designation="Director",  # type: ignore[arg-type]
                board_role="NED",
                independence_status="Independent",
                year_end_status="Active",
            )

    def test_invalid_independence(self) -> None:
        with pytest.raises(ValidationError):
            BoardRoleDetails(
                designation="Non-Executive Director",
                board_role="NED",
                independence_status="Somewhat independent",  # type: ignore[arg-type]
                year_end_status="Active",
            )

    def test_committee_attendance(self) -> None:
        ca = CommitteeAttendance(
            committee_name="Audit",
            meetings_attended=5,
            meetings_scheduled=5,
            attendance_pct=1.0,
            is_chair=True,
        )
        assert ca.is_chair is True

    def test_biographical_defaults(self) -> None:
        bio = BiographicalDetails(full_name="Test Person")
        assert bio.gender is None
        assert bio.affiliation is None
        assert bio.career_summary is None

    def test_extra_field_forbidden_biographical(self) -> None:
        with pytest.raises(ValidationError):
            BiographicalDetails(full_name="X", unknown_field="y")  # type: ignore[call-arg]


class TestBoardGovernanceDocument:
    def test_round_trip_json(self, sample_document: BoardGovernanceDocument) -> None:
        serialised = sample_document.model_dump_json()
        parsed = json.loads(serialised)
        restored = BoardGovernanceDocument.model_validate(parsed)
        assert restored.company.company_name == sample_document.company.company_name
        assert len(restored.current_board.directors) == len(sample_document.current_board.directors)

    def test_empty_directors(self) -> None:
        doc = BoardGovernanceDocument(company=make_metadata())
        assert doc.current_board.directors == []

    def test_model_json_schema(self) -> None:
        schema = BoardGovernanceDocument.model_json_schema()
        assert "properties" in schema
        assert "company" in schema["properties"]
        assert "current_board" in schema["properties"]

    def test_director_election_optional(self) -> None:
        doc = BoardGovernanceDocument(company=make_metadata())
        assert doc.director_election is None

    def test_director_election_round_trip(self) -> None:
        election = DirectorElection(
            summary=DirectorElectionSummary(
                num_directors_to_elect=3,
                incumbent_nominees=["Alice Smith", "Bob Jones"],
                new_nominees=["Carol White"],
                candidates_disclosed=True,
            ),
            candidates=[],
        )
        doc = BoardGovernanceDocument(
            company=make_metadata(), director_election=election
        )
        restored = BoardGovernanceDocument.model_validate_json(doc.model_dump_json())
        assert restored.director_election is not None
        assert restored.director_election.summary.num_directors_to_elect == 3
        assert restored.director_election.summary.incumbent_nominees == ["Alice Smith", "Bob Jones"]
        assert restored.director_election.summary.candidates_disclosed is True


class TestDirectorElectionModels:
    def test_summary_defaults(self) -> None:
        s = DirectorElectionSummary()
        assert s.num_directors_to_elect is None
        assert s.incumbent_nominees == []
        assert s.new_nominees == []
        assert s.candidates_disclosed is None

    def test_election_defaults(self) -> None:
        e = DirectorElection()
        assert e.candidates == []
        assert e.summary.num_directors_to_elect is None

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            DirectorElectionSummary(num_directors_to_elect=2, unknown="x")  # type: ignore[call-arg]
