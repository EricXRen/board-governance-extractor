"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from gov_extract.models.director import (
    AttendanceDetails,
    BiographicalDetails,
    BoardRoleDetails,
    CommitteeAttendance,
    Director,
)
from gov_extract.models.document import BoardGovernanceDocument
from gov_extract.models.metadata import CompanyMetadata

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_director() -> Director:
    return Director(
        biographical=BiographicalDetails(
            full_name="Robin Budenberg",
            post_nominals="CBE",
            age=62,
            gender="Male",
            affiliation="UK Financial Investments",
            career_summary="Former CEO of UK Financial Investments.",
        ),
        board_role=BoardRoleDetails(
            designation="Chair",
            board_role="Chair",
            independence_status="Chair (independent on appointment)",
            year_joined_board=2020,
            date_joined_board="2020-04-01",
            tenure_years=5.0,
            year_end_status="Active",
            committee_memberships=["Nominations Committee"],
            committee_chair_of=["Nominations Committee"],
            other_positions=["Chair"],
        ),
        attendance=AttendanceDetails(
            board_meetings_attended=10,
            board_meetings_scheduled=10,
            board_attendance_pct=1.0,
            committee_attendance=[
                CommitteeAttendance(
                    committee_name="Nominations Committee",
                    meetings_attended=5,
                    meetings_scheduled=5,
                    attendance_pct=1.0,
                    is_chair=True,
                )
            ],
        ),
    )


@pytest.fixture
def sample_document(sample_director: Director) -> BoardGovernanceDocument:
    return BoardGovernanceDocument(
        company=CompanyMetadata(
            company_name="Test Company",
            filing_type="Annual Report",
            fiscal_year_end="2025-12-31",
            source_pdf_path="/tmp/test.pdf",
            extraction_timestamp="2025-01-01T00:00:00+00:00",
            llm_provider="anthropic",
            llm_model="claude-sonnet-4-6",
        ),
        directors=[sample_director],
    )
