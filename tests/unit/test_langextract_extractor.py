"""Unit tests for the LangExtract extraction backend."""

from __future__ import annotations

import sys

import pytest

from gov_extract.extraction.langextract_extractor import (
    _extraction_to_director,
    _float_attr,
    _int_attr,
    _list_attr,
    _str_attr,
)
from gov_extract.models.director import Director


class FakeCharInterval:
    """Minimal stand-in for langextract.data.CharInterval."""

    def __init__(self, start: int, end: int) -> None:
        self.start_pos = start
        self.end_pos = end


class FakeExtraction:
    """Minimal stand-in for langextract.data.Extraction."""

    def __init__(
        self,
        extraction_class: str,
        extraction_text: str,
        attributes: dict,
        char_interval: object | None = None,
    ) -> None:
        self.extraction_class = extraction_class
        self.extraction_text = extraction_text
        self.attributes = attributes
        self.char_interval = char_interval


_SAMPLE_ATTRS = {
    "full_name": "Jane Smith",
    "post_nominals": "CBE",
    "gender": "Female",
    "age_band": "56-60",
    "designation": "Non-Executive Director",
    "board_role": "Senior Independent Director",
    "independence_status": "Independent",
    "year_joined_board": "2018",
    "date_joined_board": "2018-06-15",
    "tenure_years": "6.5",
    "year_end_status": "Active",
    "committee_memberships": ["Audit Committee", "Risk Committee"],
    "committee_chair_of": ["Audit Committee"],
    "num_holding_shares": "15000",
    "board_meetings_attended": "10",
    "board_meetings_scheduled": "12",
    "board_attendance_pct": "83.3",
    "career_summary": "Jane spent 20 years in investment banking.",
}

_SAMPLE_TEXT = "Jane Smith CBE  Senior Independent Director  Appointed June 2018"
_SAMPLE_PAGE_OFFSETS = [(1, 0), (2, 100), (3, 200)]


class TestAttributeHelpers:
    def test_str_attr_present(self) -> None:
        assert _str_attr({"k": "hello"}, "k") == "hello"

    def test_str_attr_null_string(self) -> None:
        assert _str_attr({"k": "null"}, "k") is None

    def test_str_attr_empty(self) -> None:
        assert _str_attr({"k": ""}, "k") is None

    def test_str_attr_missing(self) -> None:
        assert _str_attr({}, "k") is None

    def test_int_attr_valid(self) -> None:
        assert _int_attr({"k": "2018"}, "k") == 2018

    def test_int_attr_with_comma(self) -> None:
        assert _int_attr({"k": "15,000"}, "k") == 15000

    def test_int_attr_invalid(self) -> None:
        assert _int_attr({"k": "N/A"}, "k") is None

    def test_float_attr_valid(self) -> None:
        assert _float_attr({"k": "6.5"}, "k") == pytest.approx(6.5)

    def test_float_attr_null(self) -> None:
        assert _float_attr({"k": None}, "k") is None

    def test_list_attr_list(self) -> None:
        assert _list_attr({"k": ["Audit", "Risk"]}, "k") == ["Audit", "Risk"]

    def test_list_attr_semicolon_string(self) -> None:
        assert _list_attr({"k": "Audit;Risk"}, "k") == ["Audit", "Risk"]

    def test_list_attr_empty(self) -> None:
        assert _list_attr({"k": []}, "k") == []

    def test_list_attr_null_string(self) -> None:
        assert _list_attr({"k": "null"}, "k") == []

    def test_list_attr_missing(self) -> None:
        assert _list_attr({}, "k") == []


class TestExtractionToDirector:
    def test_valid_full_attributes(self) -> None:
        ext = FakeExtraction("director", "Jane Smith CBE", _SAMPLE_ATTRS)
        d = _extraction_to_director(ext, _SAMPLE_TEXT, _SAMPLE_PAGE_OFFSETS)
        assert d is not None
        assert isinstance(d, Director)
        assert d.biographical.full_name == "Jane Smith"
        assert d.biographical.post_nominals == "CBE"
        assert d.biographical.gender == "Female"
        assert d.board_role.designation == "Non-Executive Director"
        assert d.board_role.independence_status == "Independent"
        assert d.board_role.year_joined_board == 2018
        assert d.board_role.tenure_years == pytest.approx(6.5)
        assert d.board_role.committee_memberships == ["Audit Committee", "Risk Committee"]
        assert d.board_role.committee_chair_of == ["Audit Committee"]
        assert d.board_role.num_holding_shares == 15000
        assert d.attendance.board_meetings_attended == 10
        assert d.attendance.board_meetings_scheduled == 12

    def test_wrong_extraction_class_returns_none(self) -> None:
        ext = FakeExtraction("committee", "Audit Committee", {})
        assert _extraction_to_director(ext, "", []) is None

    def test_missing_full_name_uses_extraction_text(self) -> None:
        attrs = {k: v for k, v in _SAMPLE_ATTRS.items() if k != "full_name"}
        ext = FakeExtraction("director", "Jane Smith", attrs)
        d = _extraction_to_director(ext, _SAMPLE_TEXT, _SAMPLE_PAGE_OFFSETS)
        assert d is not None
        assert d.biographical.full_name == "Jane Smith"

    def test_empty_extraction_text_and_no_full_name_returns_none(self) -> None:
        ext = FakeExtraction("director", "", {})
        assert _extraction_to_director(ext, "", []) is None

    def test_invalid_designation_defaults_to_ned(self) -> None:
        attrs = {**_SAMPLE_ATTRS, "designation": "Unknown Type"}
        ext = FakeExtraction("director", "Jane Smith", attrs)
        d = _extraction_to_director(ext, _SAMPLE_TEXT, _SAMPLE_PAGE_OFFSETS)
        assert d is not None
        assert d.board_role.designation == "Non-Executive Director"

    def test_invalid_independence_defaults_to_independent(self) -> None:
        attrs = {**_SAMPLE_ATTRS, "independence_status": "Sort of independent"}
        ext = FakeExtraction("director", "Jane Smith", attrs)
        d = _extraction_to_director(ext, _SAMPLE_TEXT, _SAMPLE_PAGE_OFFSETS)
        assert d is not None
        assert d.board_role.independence_status == "Independent"

    def test_chair_designation(self) -> None:
        attrs = {**_SAMPLE_ATTRS, "designation": "Chair", "independence_status": "Chair (independent on appointment)"}
        ext = FakeExtraction("director", "Robin B", attrs)
        d = _extraction_to_director(ext, _SAMPLE_TEXT, _SAMPLE_PAGE_OFFSETS)
        assert d is not None
        assert d.board_role.designation == "Chair"

    def test_no_char_interval_gives_null_source_ref(self) -> None:
        ext = FakeExtraction("director", "Jane Smith", _SAMPLE_ATTRS, char_interval=None)
        d = _extraction_to_director(ext, _SAMPLE_TEXT, _SAMPLE_PAGE_OFFSETS)
        assert d is not None
        assert d.source_ref is None

    def test_char_interval_populates_source_ref(self) -> None:
        text = "Page content. Jane Smith CBE  Senior Independent Director. More text."
        ci = FakeCharInterval(14, 45)
        ext = FakeExtraction("director", "Jane Smith CBE", _SAMPLE_ATTRS, char_interval=ci)
        d = _extraction_to_director(ext, text, [(1, 0)])
        assert d is not None
        assert d.source_ref is not None
        assert d.source_ref.char_start == 14
        assert d.source_ref.char_end == 45
        assert d.source_ref.quoted_text == text[14:45]
        assert d.source_ref.page_number == 1

    def test_char_interval_page_number_derived_from_offsets(self) -> None:
        text = "Page1 text " + ("x" * 100) + "  Page2 text " + ("y" * 100)
        page_offsets = [(1, 0), (2, 113)]  # page 2 starts at offset 113
        ci = FakeCharInterval(120, 130)  # within page 2
        ext = FakeExtraction("director", "Jane", _SAMPLE_ATTRS, char_interval=ci)
        d = _extraction_to_director(ext, text, page_offsets)
        assert d is not None
        assert d.source_ref is not None
        assert d.source_ref.page_number == 2

    def test_quoted_text_truncated_at_200_chars(self) -> None:
        long_text = "A" * 300
        ci = FakeCharInterval(0, 300)
        ext = FakeExtraction("director", "Jane", _SAMPLE_ATTRS, char_interval=ci)
        d = _extraction_to_director(ext, long_text, [(1, 0)])
        assert d is not None
        assert d.source_ref is not None
        assert d.source_ref.quoted_text is not None
        assert len(d.source_ref.quoted_text) == 200

    def test_partial_attributes_fills_with_none(self) -> None:
        attrs = {"full_name": "John Doe", "designation": "Non-Executive Director",
                 "independence_status": "Independent", "board_role": "NED",
                 "year_end_status": "Active"}
        ext = FakeExtraction("director", "John Doe", attrs)
        d = _extraction_to_director(ext, "", [])
        assert d is not None
        assert d.biographical.age is None
        assert d.biographical.gender is None
        assert d.board_role.year_joined_board is None
        assert d.board_role.tenure_years is None
        assert d.attendance.board_meetings_attended is None


class TestRunLangextractImportError:
    def test_missing_langextract_raises_runtime_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "langextract", None)  # type: ignore[misc]

        from gov_extract.extraction.langextract_extractor import run_langextract_extraction

        with pytest.raises(RuntimeError, match="langextract is required"):
            run_langextract_extraction({1: "text"}, "Test Co", "openai", "gpt-4o")
