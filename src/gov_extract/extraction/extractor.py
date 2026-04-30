"""Orchestrate LLM calls across chunks and merge partial Director lists."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import RootModel

from gov_extract.extraction.chunker import TextChunk
from gov_extract.extraction.prompts import (
    markdown_system_prompt,
    markdown_user_prompt,
    structured_from_markdown_system_prompt,
    structured_from_markdown_user_prompt,
    system_prompt,
    user_prompt,
)
from gov_extract.llm.base import LLMProvider
from gov_extract.models.director import Director
from gov_extract.models.document import BoardGovernanceDocument
from gov_extract.models.metadata import CompanyMetadata

logger = structlog.get_logger()

# Fuzzy match threshold for merging directors from different chunks
_MERGE_THRESHOLD = 85


class DirectorList(RootModel[list[Director]]):
    """Root model wrapping a list of directors for structured output."""

    root: list[Director]


def _fuzzy_ratio(a: str, b: str) -> float:
    """Simple character-level similarity ratio for director name matching."""
    try:
        from rapidfuzz import fuzz

        return fuzz.token_sort_ratio(a, b)
    except ImportError:
        # Simple fallback without rapidfuzz
        a_lower = a.lower().strip()
        b_lower = b.lower().strip()
        if a_lower == b_lower:
            return 100.0
        common = sum(a_lower.count(c) for c in set(b_lower))
        return 100.0 * 2 * common / (len(a_lower) + len(b_lower) + 1)


def _merge_directors(base: Director, supplement: Director) -> Director:
    """Merge supplement into base, filling null fields from supplement.

    Args:
        base: Primary director record.
        supplement: Additional extraction for the same director.

    Returns:
        Merged Director with as many fields populated as possible.
    """
    base_data = base.model_dump()
    supp_data = supplement.model_dump()

    def _merge_dicts(b: dict[str, Any], s: dict[str, Any]) -> dict[str, Any]:
        result = dict(b)
        for key, sval in s.items():
            bval = b.get(key)
            if (
                bval is None
                and sval is not None
                or isinstance(bval, list)
                and isinstance(sval, list)
                and not bval
                and sval
            ):
                result[key] = sval
            elif isinstance(bval, dict) and isinstance(sval, dict):
                result[key] = _merge_dicts(bval, sval)
        return result

    merged_data = _merge_dicts(base_data, supp_data)
    return Director.model_validate(merged_data)


def _deduplicate_directors(director_lists: list[list[Director]]) -> list[Director]:
    """Merge director lists from multiple chunks by fuzzy name matching.

    Args:
        director_lists: Per-chunk lists of extracted directors.

    Returns:
        Deduplicated, merged list of directors.
    """
    merged: list[Director] = []

    for chunk_directors in director_lists:
        for new_dir in chunk_directors:
            new_name = new_dir.biographical.full_name

            best_idx = -1
            best_score = 0.0
            for idx, existing in enumerate(merged):
                score = _fuzzy_ratio(new_name, existing.biographical.full_name)
                if score > best_score:
                    best_score = score
                    best_idx = idx

            if best_score >= _MERGE_THRESHOLD and best_idx >= 0:
                merged[best_idx] = _merge_directors(merged[best_idx], new_dir)
                logger.debug(
                    "director_merged",
                    name=new_name,
                    matched=merged[best_idx].biographical.full_name,
                    score=best_score,
                )
            else:
                merged.append(new_dir)

    return merged


def _extract_chunk(
    provider: LLMProvider,
    chunk: TextChunk,
    company_name: str,
    filing_type: str,
    fiscal_year_end: str,
) -> list[Director]:
    """Extract directors from a single text chunk.

    Args:
        provider: Configured LLM provider.
        chunk: Text chunk with page metadata.
        company_name: Company name for the user prompt.
        filing_type: Filing type for the user prompt.
        fiscal_year_end: Fiscal year end date for the user prompt.

    Returns:
        List of extracted Director objects (may be empty).
    """
    sys_prompt = system_prompt()
    usr_prompt = user_prompt(
        chunk.text,
        company_name,
        filing_type,
        fiscal_year_end,
        chunk.start_page,
        chunk.end_page,
    )

    try:
        result = provider.extract(sys_prompt, usr_prompt, DirectorList)
        directors = result.root if isinstance(result, DirectorList) else []
    except Exception as e:
        logger.warning(
            "chunk_extraction_failed_structured",
            start=chunk.start_page,
            end=chunk.end_page,
            error=str(e),
        )
        try:
            raw = provider.extract_raw_json(sys_prompt, usr_prompt)
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                directors = [Director.model_validate(d) for d in parsed]
            elif isinstance(parsed, dict) and "directors" in parsed:
                directors = [Director.model_validate(d) for d in parsed["directors"]]
            else:
                directors = []
        except Exception as e2:
            logger.error(
                "chunk_extraction_failed",
                start=chunk.start_page,
                end=chunk.end_page,
                error=str(e2),
            )
            directors = []

    logger.info(
        "chunk_extracted",
        start=chunk.start_page,
        end=chunk.end_page,
        directors_found=len(directors),
    )
    return directors


def _extract_chunk_markdown(
    provider: LLMProvider,
    chunk: TextChunk,
    company_name: str,
    filing_type: str,
    fiscal_year_end: str,
) -> str:
    """Extract a text chunk to Markdown (round 1 of two-round extraction).

    Args:
        provider: Configured LLM provider.
        chunk: Text chunk with page metadata.
        company_name: Company name for the user prompt.
        filing_type: Filing type for the user prompt.
        fiscal_year_end: Fiscal year end date for the user prompt.

    Returns:
        Markdown string with all director information found in this chunk.
    """
    sys_prompt = markdown_system_prompt()
    usr_prompt = markdown_user_prompt(
        chunk.text,
        company_name,
        filing_type,
        fiscal_year_end,
        chunk.start_page,
        chunk.end_page,
    )
    try:
        markdown = provider.extract_text(sys_prompt, usr_prompt)
    except Exception as e:
        logger.error(
            "markdown_extraction_failed",
            start=chunk.start_page,
            end=chunk.end_page,
            error=str(e),
        )
        markdown = ""

    logger.info(
        "markdown_chunk_extracted",
        start=chunk.start_page,
        end=chunk.end_page,
        markdown_chars=len(markdown),
    )
    return markdown


def _structured_from_markdown(
    provider: LLMProvider,
    markdown_text: str,
    company_name: str,
    filing_type: str,
    fiscal_year_end: str,
) -> list[Director]:
    """Convert combined Markdown to structured Director objects (round 2).

    Args:
        provider: Configured LLM provider.
        markdown_text: Combined Markdown from all first-round extractions.
        company_name: Company name for the user prompt.
        filing_type: Filing type for the user prompt.
        fiscal_year_end: Fiscal year end date for the user prompt.

    Returns:
        List of extracted Director objects.
    """
    sys_prompt = structured_from_markdown_system_prompt()
    usr_prompt = structured_from_markdown_user_prompt(
        markdown_text, company_name, filing_type, fiscal_year_end
    )
    try:
        result = provider.extract(sys_prompt, usr_prompt, DirectorList)
        directors = result.root if isinstance(result, DirectorList) else []
    except Exception as e:
        logger.warning("structured_from_markdown_failed_structured", error=str(e))
        try:
            raw = provider.extract_raw_json(sys_prompt, usr_prompt)
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                directors = [Director.model_validate(d) for d in parsed]
            elif isinstance(parsed, dict) and "directors" in parsed:
                directors = [Director.model_validate(d) for d in parsed["directors"]]
            else:
                directors = []
        except Exception as e2:
            logger.error("structured_from_markdown_failed", error=str(e2))
            directors = []

    logger.info("structured_from_markdown_complete", directors_found=len(directors))
    return directors


def _extract_single_pass(
    provider: LLMProvider,
    chunks: list[TextChunk],
    company_name: str,
    filing_type: str,
    fiscal_year_end: str,
) -> list[Director]:
    """Extract all directors in one LLM call by concatenating all chunks.

    This is the baseline approach: no chunking loop, no merge step. All
    governance text is sent to the model at once. Suitable for comparing
    extraction quality against the default chunked strategy.

    Args:
        provider: Configured LLM provider.
        chunks: Text chunks to concatenate (produced by the chunker but not
            split across multiple LLM calls).
        company_name: Company name for the user prompt.
        filing_type: Filing type for the user prompt.
        fiscal_year_end: Fiscal year end date for the user prompt.

    Returns:
        List of extracted Director objects.
    """
    if not chunks:
        return []

    combined_text = "\n\n".join(c.text for c in chunks)
    start_page = chunks[0].start_page
    end_page = chunks[-1].end_page

    combined_chunk = TextChunk(text=combined_text, start_page=start_page, end_page=end_page)

    logger.info(
        "single_pass_extraction",
        start_page=start_page,
        end_page=end_page,
        total_chars=len(combined_text),
    )

    return _extract_chunk(provider, combined_chunk, company_name, filing_type, fiscal_year_end)


def run_extraction(
    provider: LLMProvider,
    chunks: list[TextChunk],
    company_name: str,
    filing_type: str,
    fiscal_year_end: str,
    source_pdf_path: str,
    provider_name: str,
    model_name: str,
    company_ticker: str | None = None,
    report_date: str | None = None,
    extraction_method: str = "chunked",
    extraction_rounds: int = 1,
) -> BoardGovernanceDocument:
    """Run the full extraction pipeline over all chunks.

    The two axes are independent and combine freely:

    ``extraction_method``:
      - ``"chunked"`` — iterate over chunks, extract each, deduplicate and merge.
      - ``"single_pass"`` — concatenate all chunks into one text, single LLM call.

    ``extraction_rounds``:
      - ``1`` — direct structured-output extraction (default).
      - ``2`` — first extract to Markdown (no schema constraints), then convert
        the combined Markdown to structured JSON in a second LLM call. Tends to
        improve recall at the cost of an extra API call.

    Args:
        provider: Configured LLM provider.
        chunks: List of text chunks from governance pages.
        company_name: Company name.
        filing_type: e.g. "Annual Report".
        fiscal_year_end: ISO-8601 date.
        source_pdf_path: Path to the source PDF.
        provider_name: e.g. "anthropic".
        model_name: e.g. "claude-sonnet-4-6".
        company_ticker: Optional ticker symbol.
        report_date: Optional report publication date (ISO-8601).
        extraction_method: ``"chunked"`` or ``"single_pass"``.
        extraction_rounds: ``1`` (direct structured) or ``2`` (markdown then structured).

    Returns:
        Validated BoardGovernanceDocument.

    Raises:
        ValueError: If extraction_method or extraction_rounds is not recognised.
    """
    if extraction_method not in ("chunked", "single_pass"):
        raise ValueError(
            f"Unknown extraction_method '{extraction_method}'. Use 'chunked' or 'single_pass'."
        )
    if extraction_rounds not in (1, 2):
        raise ValueError(
            f"Unknown extraction_rounds '{extraction_rounds}'. Use 1 or 2."
        )

    logger.info(
        "extraction_started",
        company=company_name,
        num_chunks=len(chunks),
        provider=provider_name,
        model=model_name,
        extraction_method=extraction_method,
        extraction_rounds=extraction_rounds,
    )

    # Determine which input chunks to use for each LLM call.
    # single_pass: collapse everything into one synthetic chunk before any LLM call.
    if extraction_method == "single_pass" and chunks:
        combined_text = "\n\n".join(c.text for c in chunks)
        effective_chunks = [TextChunk(combined_text, chunks[0].start_page, chunks[-1].end_page)]
    else:
        effective_chunks = chunks

    if extraction_rounds == 2:
        # Round 1: extract each (effective) chunk to Markdown.
        markdown_parts = [
            _extract_chunk_markdown(provider, chunk, company_name, filing_type, fiscal_year_end)
            for chunk in effective_chunks
        ]
        combined_markdown = "\n\n---\n\n".join(p for p in markdown_parts if p)

        logger.info(
            "markdown_rounds_complete",
            num_parts=len(markdown_parts),
            total_markdown_chars=len(combined_markdown),
        )

        # Round 2: convert combined Markdown to structured Directors in one call.
        merged_directors = _structured_from_markdown(
            provider, combined_markdown, company_name, filing_type, fiscal_year_end
        )
    else:
        # Single round: direct structured extraction.
        all_director_lists: list[list[Director]] = []
        for chunk in effective_chunks:
            directors = _extract_chunk(provider, chunk, company_name, filing_type, fiscal_year_end)
            all_director_lists.append(directors)
        # single_pass has only one chunk so dedup is a no-op, but it's harmless.
        merged_directors = _deduplicate_directors(all_director_lists)

    logger.info(
        "extraction_complete",
        company=company_name,
        total_directors=len(merged_directors),
        extraction_method=extraction_method,
        extraction_rounds=extraction_rounds,
    )

    metadata = CompanyMetadata(
        company_name=company_name,
        company_ticker=company_ticker,
        filing_type=filing_type,
        fiscal_year_end=fiscal_year_end,
        report_date=report_date,
        source_pdf_path=source_pdf_path,
        extraction_timestamp=datetime.now(UTC).isoformat(),
        llm_provider=provider_name,
        llm_model=model_name,
    )

    return BoardGovernanceDocument(company=metadata, directors=merged_directors)
