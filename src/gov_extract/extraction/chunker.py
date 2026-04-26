"""Split governance page text into LLM-sized chunks with page overlap."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

logger = structlog.get_logger()

# Rough character-to-token ratio for English text
CHARS_PER_TOKEN = 4


@dataclass
class TextChunk:
    """A chunk of text with its source page range."""

    text: str
    start_page: int
    end_page: int


def chunk_pages(
    pages: dict[int, str],
    max_tokens: int = 8000,
    overlap_pages: int = 1,
) -> list[TextChunk]:
    """Split a dict of pages into token-sized chunks with one-page overlap.

    Args:
        pages: Dict of page_num → text (must be pre-filtered to governance pages).
        max_tokens: Maximum tokens per chunk (estimated by character count).
        overlap_pages: Number of pages to repeat at the start of the next chunk
            to avoid splitting a director's profile across chunks.

    Returns:
        List of TextChunk objects.
    """
    if not pages:
        return []

    max_chars = max_tokens * CHARS_PER_TOKEN
    sorted_page_nums = sorted(pages.keys())

    chunks: list[TextChunk] = []
    current_pages: list[int] = []
    current_chars = 0

    for page_num in sorted_page_nums:
        page_text = pages[page_num]
        page_chars = len(page_text)

        if current_pages and current_chars + page_chars > max_chars:
            # Emit the current chunk
            chunk_text = "\n\n".join(pages[p] for p in current_pages)
            chunks.append(TextChunk(chunk_text, current_pages[0], current_pages[-1]))

            # Start next chunk with overlap
            overlap = current_pages[-overlap_pages:] if overlap_pages > 0 else []
            current_pages = list(overlap)
            current_chars = sum(len(pages[p]) for p in current_pages)

        current_pages.append(page_num)
        current_chars += page_chars

    # Emit the last chunk
    if current_pages:
        chunk_text = "\n\n".join(pages[p] for p in current_pages)
        chunks.append(TextChunk(chunk_text, current_pages[0], current_pages[-1]))

    logger.info(
        "pages_chunked",
        total_pages=len(pages),
        num_chunks=len(chunks),
        max_tokens=max_tokens,
    )
    return chunks
