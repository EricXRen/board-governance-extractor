"""Unit tests for governance page detection."""

from __future__ import annotations

from gov_extract.pdf.page_finder import PageRange, find_governance_pages


def _make_pages(content_map: dict[int, str]) -> dict[int, str]:
    return content_map


class TestPageRange:
    def test_len(self) -> None:
        r = PageRange(5, 10)
        assert len(r) == 6

    def test_pages(self) -> None:
        r = PageRange(3, 5)
        assert r.pages() == [3, 4, 5]


class TestFindGovernancePages:
    def test_empty_pages(self) -> None:
        result = find_governance_pages({})
        assert result == []

    def test_no_keywords_found_falls_back_to_full(self) -> None:
        pages = {1: "Annual financial statements", 2: "Balance sheet", 3: "Cash flow"}
        result = find_governance_pages(pages)
        assert len(result) == 1
        assert result[0].start == 1
        assert result[0].end == 3

    def test_finds_governance_page(self) -> None:
        pages = {
            1: "Introduction",
            2: "Our Board of Directors overview",
            3: "Director biographies",
            4: "Financial results",
        }
        result = find_governance_pages(pages, keywords=["board of directors"])
        assert any(r.start <= 2 <= r.end for r in result)

    def test_context_expansion(self) -> None:
        pages = {i: "filler text" for i in range(1, 20)}
        pages[10] = "Our board of directors and governance overview"
        result = find_governance_pages(pages, keywords=["board of directors"], context_pages=2)
        # Should include pages 8–12 (10 ± 2)
        all_included = [p for r in result for p in r.pages()]
        assert 10 in all_included
        assert 8 in all_included
        assert 12 in all_included

    def test_merges_nearby_ranges(self) -> None:
        pages = {i: "filler" for i in range(1, 30)}
        pages[10] = "board of directors"
        pages[12] = "governance committee report"
        result = find_governance_pages(pages, keywords=["board of directors", "committee report"])
        # Pages 10 and 12 are only 2 pages apart; should merge
        all_pages = [p for r in result for p in r.pages()]
        assert 10 in all_pages
        assert 12 in all_pages

    def test_multiple_governance_sections(self) -> None:
        pages = {i: "filler" for i in range(1, 100)}
        pages[20] = "board of directors section"
        pages[50] = "committee report details"
        result = find_governance_pages(pages, keywords=["board of directors", "committee report"])
        all_pages = [p for r in result for p in r.pages()]
        assert 20 in all_pages
        assert 50 in all_pages
