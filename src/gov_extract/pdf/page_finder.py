"""Identify governance-relevant page ranges within a PDF."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

logger = structlog.get_logger()

DEFAULT_KEYWORDS = [
    "board of directors",
    "directors' report",
    "our board",
    "committee report",
    "proxy statement",
    "governance",
]

# Headings that signal a section *after* governance (we stop including pages here)
STOP_KEYWORDS = [
    "remuneration report",
    "directors' remuneration",
    "financial statements",
    "independent auditor",
    "consolidated income",
    "balance sheet",
    "cash flow statement",
    "notes to the",
    "shareholder information",
]


@dataclass
class PageRange:
    """Inclusive page range."""

    start: int
    end: int

    def __len__(self) -> int:
        return self.end - self.start + 1

    def pages(self) -> list[int]:
        """Return list of page numbers in this range."""
        return list(range(self.start, self.end + 1))


def find_governance_pages(
    pages: dict[int, str],
    keywords: list[str] | None = None,
    context_pages: int = 2,
) -> list[PageRange]:
    """Identify pages likely to contain board governance information.

    Strategy:
    1. Scan every page for governance keyword matches.
    2. Group consecutive matching pages (with small gaps) into ranges.
    3. Expand each range by `context_pages` on each side for completeness.
    4. Fall back to the full document if nothing is found.

    Args:
        pages: Dict mapping 1-indexed page number to page text.
        keywords: List of lowercase keywords to match. Defaults to DEFAULT_KEYWORDS.
        context_pages: Number of extra pages to include around matched pages.

    Returns:
        List of PageRange objects covering governance-relevant content.
    """
    if keywords is None:
        keywords = DEFAULT_KEYWORDS

    kw_lower = [k.lower() for k in keywords]
    stop_lower = [k.lower() for k in STOP_KEYWORDS]

    if not pages:
        return []

    min_page = min(pages)
    max_page = max(pages)

    matched: set[int] = set()
    for page_num, text in pages.items():
        text_lower = text.lower()
        if any(kw in text_lower for kw in kw_lower):
            matched.add(page_num)

    if not matched:
        logger.warning("governance_pages_not_found", falling_back="full_document")
        return [PageRange(min_page, max_page)]

    # Expand by context_pages
    expanded: set[int] = set()
    for p in matched:
        for offset in range(-context_pages, context_pages + 1):
            neighbour = p + offset
            if min_page <= neighbour <= max_page:
                expanded.add(neighbour)

    # Remove pages that look like post-governance sections (remuneration, financials)
    # but only if they weren't directly matched as governance
    filtered: set[int] = set()
    for p in expanded:
        text_lower = pages.get(p, "").lower()
        is_stop = any(sk in text_lower for sk in stop_lower)
        is_direct_match = p in matched
        if not is_stop or is_direct_match:
            filtered.add(p)

    if not filtered:
        filtered = expanded

    sorted_pages = sorted(filtered)

    # Group into contiguous ranges (gap tolerance = 3 pages)
    ranges: list[PageRange] = []
    start = sorted_pages[0]
    prev = sorted_pages[0]

    for p in sorted_pages[1:]:
        if p - prev > 3:
            ranges.append(PageRange(start, prev))
            start = p
        prev = p
    ranges.append(PageRange(start, prev))

    total = sum(len(r) for r in ranges)
    logger.info(
        "governance_pages_found",
        ranges=[(r.start, r.end) for r in ranges],
        total_pages=total,
    )
    return ranges
