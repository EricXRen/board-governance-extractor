"""Unit tests for the extraction pipeline.

All LLM calls are intercepted by MockProvider / FailingProvider — no real API
keys or network access required.  The four strategy combinations
(chunking × extraction_rounds) are each tested independently.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gov_extract.extraction.chunker import TextChunk
from gov_extract.extraction.extractor import (
    DirectorList,
    _compute_board_summary,
    _deduplicate_directors,
    _extract_chunk,
    _structured_from_markdown,
    run_extraction,
)
from gov_extract.models.board_summary import BoardSummary
from gov_extract.models.director import (
    AttendanceDetails,
    BiographicalDetails,
    BoardRoleDetails,
    Director,
)
from gov_extract.models.document import BoardGovernanceDocument


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _director(name: str, designation: str = "Non-Executive Director") -> Director:
    return Director(
        biographical=BiographicalDetails(full_name=name, age=50),
        board_role=BoardRoleDetails(
            designation=designation,
            board_role="NED",
            independence_status="Independent",
            year_end_status="Active",
        ),
        attendance=AttendanceDetails(),
    )


def _director_dict(name: str) -> dict:
    """Minimal valid Director JSON dict for raw-JSON fallback tests."""
    return {
        "biographical": {
            "full_name": name,
        },
        "board_role": {
            "designation": "Non-Executive Director",
            "board_role": "NED",
            "independence_status": "Independent",
            "year_end_status": "Active",
            "committee_memberships": [],
            "committee_chair_of": [],
            "other_positions": [],
        },
        "attendance": {"committee_attendance": []},
    }


def _chunk(n: int = 1) -> TextChunk:
    return TextChunk(text=f"governance text chunk {n}", start_page=(n - 1) * 5 + 1, end_page=n * 5)


# ---------------------------------------------------------------------------
# Mock providers
# ---------------------------------------------------------------------------

class MockProvider:
    """Configurable mock implementing the LLMProvider protocol.

    Returns a fixed DirectorList and BoardSummary from extract(); counts
    extract_text() calls.
    """

    def __init__(
        self,
        directors: list[Director] | None = None,
        markdown: str = "",
        board_summary: BoardSummary | None = None,
    ) -> None:
        self._directors = directors or []
        self._markdown = markdown
        self._board_summary = board_summary or BoardSummary()
        self.extract_calls: list[type] = []
        self.extract_text_call_count: int = 0

    def extract(self, system_prompt: str, user_prompt: str, response_model: type) -> object:
        self.extract_calls.append(response_model)
        if response_model is DirectorList:
            return DirectorList(directors=self._directors)
        if response_model is BoardSummary:
            return self._board_summary
        return response_model()

    def extract_text(self, system_prompt: str, user_prompt: str) -> str:
        self.extract_text_call_count += 1
        return self._markdown

    def extract_raw_json(self, system_prompt: str, user_prompt: str) -> str:
        return json.dumps(
            {"directors": [_director_dict(d.biographical.full_name) for d in self._directors]}
        )


class FailingProvider:
    """Raises on extract() to force the extractor-level raw-JSON fallback path."""

    def __init__(self, raw_json: str) -> None:
        self._raw_json = raw_json

    def extract(self, system_prompt: str, user_prompt: str, response_model: type) -> object:
        raise ValueError("structured extraction intentionally failed")

    def extract_text(self, system_prompt: str, user_prompt: str) -> str:
        return ""

    def extract_raw_json(self, system_prompt: str, user_prompt: str) -> str:
        return self._raw_json


# Shared keyword-only args for run_extraction calls
_DEFAULTS: dict = dict(
    company_name="Test Co",
    filing_type="Annual Report",
    fiscal_year_end="2025-12-31",
    source_pdf_path="/tmp/test.pdf",
    provider_name="mock",
    model_name="mock-model",
)


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestDeduplicateDirectors:
    def test_identical_name_merged(self) -> None:
        result = _deduplicate_directors([[_director("Alice Smith")], [_director("Alice Smith")]])
        assert len(result) == 1

    def test_different_names_both_kept(self) -> None:
        result = _deduplicate_directors([[_director("Alice Smith")], [_director("Bob Jones")]])
        assert len(result) == 2

    def test_fuzzy_match_treated_as_same_person(self) -> None:
        # Post-nominal suffix ("CBE") scores just below 85 with the simple fallback
        # character-frequency algorithm.  rapidfuzz token_sort_ratio gives ~92.
        pytest.importorskip("rapidfuzz", reason="rapidfuzz required for post-nominal fuzzy dedup")
        result = _deduplicate_directors([[_director("Alice Smith CBE")], [_director("Alice Smith")]])
        assert len(result) == 1

    def test_empty_inputs(self) -> None:
        assert _deduplicate_directors([[], []]) == []

    def test_null_field_filled_from_supplement(self) -> None:
        base = _director("Alice Smith")
        supplement = Director(
            biographical=BiographicalDetails(full_name="Alice Smith", affiliation="Oxford University"),
            board_role=base.board_role,
            attendance=base.attendance,
        )
        result = _deduplicate_directors([[base], [supplement]])
        assert result[0].biographical.affiliation == "Oxford University"

    def test_existing_non_null_field_not_overwritten(self) -> None:
        base = Director(
            biographical=BiographicalDetails(full_name="Alice Smith", age=50),
            board_role=BoardRoleDetails(
                designation="Non-Executive Director",
                board_role="NED",
                independence_status="Independent",
                year_end_status="Active",
            ),
            attendance=AttendanceDetails(),
        )
        supplement = Director(
            biographical=BiographicalDetails(full_name="Alice Smith", age=99),
            board_role=base.board_role,
            attendance=base.attendance,
        )
        result = _deduplicate_directors([[base], [supplement]])
        assert result[0].biographical.age == 50


# ---------------------------------------------------------------------------
# Board summary computation
# ---------------------------------------------------------------------------

class TestComputeBoardSummary:
    def test_board_size_derived_from_director_count(self) -> None:
        result = _compute_board_summary(BoardSummary(), [_director("A"), _director("B")])
        assert result.board_size == 2

    def test_stated_board_size_not_overwritten(self) -> None:
        result = _compute_board_summary(BoardSummary(board_size=99), [_director("A")])
        assert result.board_size == 99

    def test_executive_and_ned_counts(self) -> None:
        directors = [
            _director("A", "Executive Director"),
            _director("B", "Non-Executive Director"),
            _director("C", "Non-Executive Director"),
        ]
        result = _compute_board_summary(BoardSummary(), directors)
        assert result.num_executive_directors == 1
        assert result.num_non_executive_directors == 2

    def test_pct_independent_all_independent(self) -> None:
        result = _compute_board_summary(BoardSummary(), [_director("A"), _director("B")])
        assert result.pct_independent == pytest.approx(100.0)

    def test_avg_age_computed(self) -> None:
        def _d_age(name: str, age: int) -> Director:
            return Director(
                biographical=BiographicalDetails(full_name=name, age=age),
                board_role=BoardRoleDetails(
                    designation="Non-Executive Director",
                    board_role="NED",
                    independence_status="Independent",
                    year_end_status="Active",
                ),
                attendance=AttendanceDetails(),
            )

        result = _compute_board_summary(BoardSummary(), [_d_age("A", 40), _d_age("B", 60)])
        assert result.avg_director_age == pytest.approx(50.0)

    def test_avg_tenure_computed(self) -> None:
        def _d_tenure(name: str, t: float) -> Director:
            return Director(
                biographical=BiographicalDetails(full_name=name),
                board_role=BoardRoleDetails(
                    designation="Non-Executive Director",
                    board_role="NED",
                    independence_status="Independent",
                    year_end_status="Active",
                    tenure_years=t,
                ),
                attendance=AttendanceDetails(),
            )

        result = _compute_board_summary(BoardSummary(), [_d_tenure("A", 4.0), _d_tenure("B", 6.0)])
        assert result.avg_tenure_years == pytest.approx(5.0)

    def test_ceo_chair_separated_true(self) -> None:
        chair = Director(
            biographical=BiographicalDetails(full_name="Alice"),
            board_role=BoardRoleDetails(
                designation="Chair",
                board_role="Chair",
                independence_status="Chair (independent on appointment)",
                year_end_status="Active",
            ),
            attendance=AttendanceDetails(),
        )
        ceo = Director(
            biographical=BiographicalDetails(full_name="Bob"),
            board_role=BoardRoleDetails(
                designation="Executive Director",
                board_role="Group Chief Executive",
                independence_status="N/A (Executive)",
                year_end_status="Active",
            ),
            attendance=AttendanceDetails(),
        )
        result = _compute_board_summary(BoardSummary(), [chair, ceo])
        assert result.ceo_chair_separated is True

    def test_empty_directors_leaves_summary_unchanged(self) -> None:
        summary = BoardSummary(board_size=5)
        result = _compute_board_summary(summary, [])
        assert result.board_size == 5
        assert result.num_executive_directors is None


# ---------------------------------------------------------------------------
# Strategy: chunking=True, rounds=1
# ---------------------------------------------------------------------------

class TestChunkingTrueRounds1:
    """One structured LLM call per chunk; results are merged and deduplicated."""

    def test_extract_called_once_per_chunk(self) -> None:
        chunks = [_chunk(i) for i in range(1, 4)]
        provider = MockProvider(directors=[_director("Alice Smith")])
        run_extraction(provider=provider, chunks=chunks, chunking=True, extraction_rounds=1, **_DEFAULTS)
        assert provider.extract_calls.count(DirectorList) == 3

    def test_no_extract_text_calls(self) -> None:
        provider = MockProvider()
        run_extraction(provider=provider, chunks=[_chunk(1)], chunking=True, extraction_rounds=1, **_DEFAULTS)
        assert provider.extract_text_call_count == 0

    def test_same_director_across_chunks_deduplicated(self) -> None:
        # MockProvider returns "Alice Smith" for every chunk — she should appear once.
        chunks = [_chunk(i) for i in range(1, 4)]
        provider = MockProvider(directors=[_director("Alice Smith")])
        doc = run_extraction(provider=provider, chunks=chunks, chunking=True, extraction_rounds=1, **_DEFAULTS)
        assert len(doc.current_board.directors) == 1
        assert doc.current_board.directors[0].biographical.full_name == "Alice Smith"

    def test_returns_board_governance_document(self) -> None:
        doc = run_extraction(
            provider=MockProvider(directors=[_director("Alice Smith")]),
            chunks=[_chunk(1)],
            chunking=True,
            extraction_rounds=1,
            **_DEFAULTS,
        )
        assert isinstance(doc, BoardGovernanceDocument)
        assert doc.company.company_name == "Test Co"

    def test_board_summary_extracted(self) -> None:
        provider = MockProvider(board_summary=BoardSummary(board_size=7))
        doc = run_extraction(provider=provider, chunks=[_chunk(1)], chunking=True, extraction_rounds=1, **_DEFAULTS)
        assert doc.current_board.summary.board_size == 7


# ---------------------------------------------------------------------------
# Strategy: chunking=False, rounds=1
# ---------------------------------------------------------------------------

class TestChunkingFalseRounds1:
    """All chunks collapsed into one text; single structured LLM call."""

    def test_extract_called_exactly_once_for_directors(self) -> None:
        chunks = [_chunk(i) for i in range(1, 4)]
        provider = MockProvider(directors=[_director("Alice Smith")])
        run_extraction(provider=provider, chunks=chunks, chunking=False, extraction_rounds=1, **_DEFAULTS)
        assert provider.extract_calls.count(DirectorList) == 1

    def test_no_extract_text_calls(self) -> None:
        provider = MockProvider()
        run_extraction(provider=provider, chunks=[_chunk(1), _chunk(2)], chunking=False, extraction_rounds=1, **_DEFAULTS)
        assert provider.extract_text_call_count == 0

    def test_directors_returned(self) -> None:
        provider = MockProvider(directors=[_director("Alice Smith"), _director("Bob Jones")])
        doc = run_extraction(provider=provider, chunks=[_chunk(1)], chunking=False, extraction_rounds=1, **_DEFAULTS)
        assert len(doc.current_board.directors) == 2


# ---------------------------------------------------------------------------
# Strategy: chunking=True, rounds=2
# ---------------------------------------------------------------------------

class TestChunkingTrueRounds2:
    """Round 1: extract_text per chunk. Round 2: one structured call over combined markdown."""

    def test_extract_text_called_once_per_chunk(self) -> None:
        chunks = [_chunk(i) for i in range(1, 4)]
        provider = MockProvider(directors=[_director("Alice Smith")], markdown="## Alice Smith\n- Role: NED")
        run_extraction(provider=provider, chunks=chunks, chunking=True, extraction_rounds=2, **_DEFAULTS)
        assert provider.extract_text_call_count == 3

    def test_structured_extract_called_once(self) -> None:
        chunks = [_chunk(i) for i in range(1, 4)]
        provider = MockProvider(directors=[_director("Alice Smith")], markdown="## Alice Smith\n- Role: NED")
        run_extraction(provider=provider, chunks=chunks, chunking=True, extraction_rounds=2, **_DEFAULTS)
        assert provider.extract_calls.count(DirectorList) == 1

    def test_directors_returned(self) -> None:
        provider = MockProvider(directors=[_director("Alice Smith")], markdown="## Alice Smith")
        doc = run_extraction(
            provider=provider, chunks=[_chunk(1)], chunking=True, extraction_rounds=2, **_DEFAULTS
        )
        assert len(doc.current_board.directors) == 1


# ---------------------------------------------------------------------------
# Strategy: chunking=False, rounds=2
# ---------------------------------------------------------------------------

class TestChunkingFalseRounds2:
    """Single extract_text call; one structured pass over combined markdown."""

    def test_extract_text_called_once(self) -> None:
        chunks = [_chunk(i) for i in range(1, 4)]
        provider = MockProvider(directors=[_director("Alice Smith")], markdown="## Alice Smith")
        run_extraction(provider=provider, chunks=chunks, chunking=False, extraction_rounds=2, **_DEFAULTS)
        assert provider.extract_text_call_count == 1

    def test_structured_extract_called_once(self) -> None:
        chunks = [_chunk(i) for i in range(1, 4)]
        provider = MockProvider(directors=[_director("Alice Smith")], markdown="## Alice Smith")
        run_extraction(provider=provider, chunks=chunks, chunking=False, extraction_rounds=2, **_DEFAULTS)
        assert provider.extract_calls.count(DirectorList) == 1

    def test_markdown_written_to_disk_when_path_provided(self, tmp_path: Path) -> None:
        provider = MockProvider(markdown="## Alice Smith\n- Role: Chair")
        run_extraction(
            provider=provider,
            chunks=[_chunk(1)],
            chunking=False,
            extraction_rounds=2,
            markdown_output_path=tmp_path / "round1.md",
            **_DEFAULTS,
        )
        content = (tmp_path / "round1.md").read_text()
        assert "Alice Smith" in content

    def test_no_markdown_file_when_path_not_provided(self, tmp_path: Path) -> None:
        provider = MockProvider(markdown="## Alice Smith")
        run_extraction(
            provider=provider, chunks=[_chunk(1)], chunking=False, extraction_rounds=2, **_DEFAULTS
        )
        assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestRunExtractionEdgeCases:
    def test_invalid_rounds_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="extraction_rounds"):
            run_extraction(
                provider=MockProvider(),
                chunks=[_chunk(1)],
                chunking=True,
                extraction_rounds=3,
                **_DEFAULTS,
            )

    def test_empty_chunks_returns_empty_director_list(self) -> None:
        doc = run_extraction(
            provider=MockProvider(), chunks=[], chunking=True, extraction_rounds=1, **_DEFAULTS
        )
        assert doc.current_board.directors == []

    def test_metadata_populated_correctly(self) -> None:
        doc = run_extraction(
            provider=MockProvider(),
            chunks=[_chunk(1)],
            chunking=True,
            extraction_rounds=1,
            company_name="Lloyds Banking Group",
            filing_type="Annual Report",
            fiscal_year_end="2024-12-31",
            source_pdf_path="/data/lbg.pdf",
            provider_name="azure",
            model_name="gpt-4o-deployment",
            company_ticker="LLOY.L",
        )
        assert doc.company.company_name == "Lloyds Banking Group"
        assert doc.company.company_ticker == "LLOY.L"
        assert doc.company.llm_provider == "azure"
        assert doc.company.llm_model == "gpt-4o-deployment"


# ---------------------------------------------------------------------------
# Extractor-level fallback: _extract_chunk
# ---------------------------------------------------------------------------

class TestExtractChunkFallback:
    """When extract() raises, _extract_chunk falls back to extract_raw_json()."""

    def test_directors_key_unwrapped(self) -> None:
        raw = json.dumps({"directors": [_director_dict("Alice Smith")]})
        result = _extract_chunk(FailingProvider(raw), _chunk(1), "Co", "AR", "2025-12-31")
        assert len(result) == 1
        assert result[0].biographical.full_name == "Alice Smith"

    def test_empty_dict_returns_empty_list(self) -> None:
        result = _extract_chunk(FailingProvider("{}"), _chunk(1), "Co", "AR", "2025-12-31")
        assert result == []

    def test_raw_list_at_root_parsed(self) -> None:
        raw = json.dumps([_director_dict("Bob Jones")])
        result = _extract_chunk(FailingProvider(raw), _chunk(1), "Co", "AR", "2025-12-31")
        assert len(result) == 1
        assert result[0].biographical.full_name == "Bob Jones"

    def test_single_director_dict_wrapped_in_list(self) -> None:
        raw = json.dumps(_director_dict("Carol White"))
        result = _extract_chunk(FailingProvider(raw), _chunk(1), "Co", "AR", "2025-12-31")
        assert len(result) == 1
        assert result[0].biographical.full_name == "Carol White"

    def test_multiple_directors_from_directors_key(self) -> None:
        raw = json.dumps({"directors": [_director_dict("A"), _director_dict("B"), _director_dict("C")]})
        result = _extract_chunk(FailingProvider(raw), _chunk(1), "Co", "AR", "2025-12-31")
        assert len(result) == 3

    def test_invalid_json_returns_empty_list(self) -> None:
        result = _extract_chunk(FailingProvider("not json"), _chunk(1), "Co", "AR", "2025-12-31")
        assert result == []


# ---------------------------------------------------------------------------
# Extractor-level fallback: _structured_from_markdown
# ---------------------------------------------------------------------------

class TestStructuredFromMarkdownFallback:
    """When extract() raises, _structured_from_markdown falls back to extract_raw_json()."""

    def test_directors_key_unwrapped(self) -> None:
        raw = json.dumps({"directors": [_director_dict("Alice Smith")]})
        result = _structured_from_markdown(FailingProvider(raw), "## Alice", "Co", "AR", "2025-12-31")
        assert len(result) == 1

    def test_empty_dict_returns_empty_list(self) -> None:
        result = _structured_from_markdown(FailingProvider("{}"), "## Empty", "Co", "AR", "2025-12-31")
        assert result == []

    def test_raw_list_at_root_parsed(self) -> None:
        raw = json.dumps([_director_dict("Bob Jones")])
        result = _structured_from_markdown(FailingProvider(raw), "## Bob", "Co", "AR", "2025-12-31")
        assert len(result) == 1

    def test_single_director_dict_wrapped_in_list(self) -> None:
        raw = json.dumps(_director_dict("Carol White"))
        result = _structured_from_markdown(FailingProvider(raw), "## Carol", "Co", "AR", "2025-12-31")
        assert len(result) == 1
        assert result[0].biographical.full_name == "Carol White"
