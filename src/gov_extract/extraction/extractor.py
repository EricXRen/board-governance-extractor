"""Orchestrate LLM calls across chunks and merge partial Director lists."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from pydantic import RootModel

from gov_extract.extraction.chunker import TextChunk
from gov_extract.extraction.prompts import (
    board_summary_system_prompt,
    board_summary_user_prompt,
    markdown_system_prompt,
    markdown_user_prompt,
    structured_from_markdown_system_prompt,
    structured_from_markdown_user_prompt,
    system_prompt,
    user_prompt,
)
from gov_extract.llm.base import LLMProvider
from gov_extract.models.board_summary import BoardSummary
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
            elif isinstance(parsed, dict):
                for key in ("directors", "root", "items", "data", "results"):
                    if key in parsed and isinstance(parsed[key], list):
                        directors = [Director.model_validate(d) for d in parsed[key]]
                        break
                else:
                    try:
                        directors = [Director.model_validate(parsed)]
                    except Exception:
                        directors = []
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
            elif isinstance(parsed, dict):
                for key in ("directors", "root", "items", "data", "results"):
                    if key in parsed and isinstance(parsed[key], list):
                        directors = [Director.model_validate(d) for d in parsed[key]]
                        break
                else:
                    try:
                        directors = [Director.model_validate(parsed)]
                    except Exception:
                        directors = []
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


def _extract_board_summary(
    provider: LLMProvider,
    text: str,
    company_name: str,
    filing_type: str,
    fiscal_year_end: str,
    is_markdown: bool = False,
) -> BoardSummary:
    """Extract board-level summary statistics from governance text or markdown.

    This is always a single LLM call over the full governance text (not chunked),
    since the metrics are aggregate and typically stated once in the filing.

    Args:
        provider: Configured LLM provider.
        text: Full governance text or combined round-1 markdown.
        company_name: Company name for the user prompt.
        filing_type: Filing type for the user prompt.
        fiscal_year_end: Fiscal year end date for the user prompt.
        is_markdown: True when ``text`` is pre-extracted Markdown (round 2).

    Returns:
        BoardSummary with any fields explicitly stated in the text populated.
    """
    sys_prompt = board_summary_system_prompt()
    usr_prompt = board_summary_user_prompt(
        text, company_name, filing_type, fiscal_year_end, is_markdown=is_markdown
    )
    try:
        result = provider.extract(sys_prompt, usr_prompt, BoardSummary)
        summary = result if isinstance(result, BoardSummary) else BoardSummary()
    except Exception as e:
        logger.warning("board_summary_extraction_failed_structured", error=str(e))
        try:
            raw = provider.extract_raw_json(sys_prompt, usr_prompt)
            summary = BoardSummary.model_validate_json(raw)
        except Exception as e2:
            logger.error("board_summary_extraction_failed", error=str(e2))
            summary = BoardSummary()

    logger.info("board_summary_extracted", company=company_name)
    return summary


def _compute_board_summary(summary: BoardSummary, directors: list[Director]) -> BoardSummary:
    """Fill in BoardSummary fields that can be derived from the Director list.

    Only fills fields that are currently ``None`` — stated values from the
    filing are never overwritten.

    Computable fields:
    - ``board_size``: total number of directors
    - ``num_executive_directors``: count with designation "Executive Director"
    - ``num_non_executive_directors``: count with designation "Non-Executive Director"
    - ``num_independent_directors``: count with independence_status "Independent"
      or "Chair (independent on appointment)"
    - ``pct_independent``: num_independent / board_size * 100
    - ``avg_director_age``: mean age across directors with a known age
    - ``avg_tenure_years``: mean tenure across directors with a known tenure
    - ``ceo_chair_separated``: True if Chair and CEO are different directors

    Not computable (no gender field on Director):
    - ``pct_women`` — must come from the filing text.

    Not computable:
    - ``voting_standard`` — must come from the filing text.

    Args:
        summary: Partially-populated BoardSummary from LLM extraction.
        directors: Extracted director list for the same document.

    Returns:
        Updated BoardSummary with computed fields filled where previously None.
    """
    if not directors:
        return summary

    data = summary.model_dump()

    if data["board_size"] is None:
        data["board_size"] = len(directors)

    execs = [d for d in directors if d.board_role.designation == "Executive Director"]
    neds = [d for d in directors if d.board_role.designation == "Non-Executive Director"]
    independents = [
        d for d in directors
        if d.board_role.independence_status in (
            "Independent", "Chair (independent on appointment)"
        )
    ]

    if data["num_executive_directors"] is None:
        data["num_executive_directors"] = len(execs)
    if data["num_non_executive_directors"] is None:
        data["num_non_executive_directors"] = len(neds)
    if data["num_independent_directors"] is None:
        data["num_independent_directors"] = len(independents)

    total = data["board_size"] or len(directors)
    if data["pct_independent"] is None and total > 0:
        data["pct_independent"] = round(len(independents) / total * 100, 1)

    ages = [d.biographical.age for d in directors if d.biographical.age is not None]
    if data["avg_director_age"] is None and ages:
        data["avg_director_age"] = round(sum(ages) / len(ages), 1)

    tenures = [d.board_role.tenure_years for d in directors if d.board_role.tenure_years is not None]
    if data["avg_tenure_years"] is None and tenures:
        data["avg_tenure_years"] = round(sum(tenures) / len(tenures), 1)

    if data["ceo_chair_separated"] is None:
        chair_names = {
            d.biographical.full_name for d in directors
            if d.board_role.designation == "Chair"
        }
        ceo_names = {
            d.biographical.full_name for d in directors
            if "chief executive" in (d.board_role.board_role or "").lower()
            or "ceo" in (d.board_role.board_role or "").lower()
        }
        if chair_names and ceo_names:
            data["ceo_chair_separated"] = chair_names.isdisjoint(ceo_names)

    return BoardSummary.model_validate(data)


def _run_parallel(
    fn: Any,
    chunks: list[TextChunk],
    provider: LLMProvider,
    company_name: str,
    filing_type: str,
    fiscal_year_end: str,
    max_workers: int = 5,
) -> list[Any]:
    """Run ``fn(provider, chunk, company_name, filing_type, fiscal_year_end)`` for every
    chunk in parallel using a thread pool, returning results in chunk order.

    Falls back to a plain sequential loop when there is only one chunk (avoids
    thread-pool overhead for single_pass mode).

    Args:
        fn: ``_extract_chunk`` or ``_extract_chunk_markdown``.
        chunks: Ordered list of text chunks to process.
        provider: Configured LLM provider (thread-safe: each call is independent).
        company_name: Forwarded to ``fn``.
        filing_type: Forwarded to ``fn``.
        fiscal_year_end: Forwarded to ``fn``.
        max_workers: Maximum number of concurrent threads.

    Returns:
        List of results in the same order as ``chunks``.
    """
    if len(chunks) <= 1:
        return [fn(provider, c, company_name, filing_type, fiscal_year_end) for c in chunks]

    results: list[Any] = [None] * len(chunks)
    with ThreadPoolExecutor(max_workers=min(max_workers, len(chunks))) as executor:
        futures = {
            executor.submit(fn, provider, chunk, company_name, filing_type, fiscal_year_end): idx
            for idx, chunk in enumerate(chunks)
        }
        for future in as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()  # re-raises any exception from the worker

    return results


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
    chunking: bool = True,
    extraction_rounds: int = 1,
    max_chunk_workers: int = 5,
    markdown_output_path: Path | None = None,
) -> BoardGovernanceDocument:
    """Run the full extraction pipeline over all chunks.

    The two axes are independent and combine freely:

    ``chunking``:
      - ``True`` — iterate over chunks, extract each, deduplicate and merge.
      - ``False`` — concatenate all chunks into one text, single LLM call.

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
        chunking: True = chunk pages and merge results; False = single pass over all pages.
        extraction_rounds: ``1`` (direct structured) or ``2`` (markdown then structured).
        max_chunk_workers: Maximum parallel threads for chunk LLM calls. Only
            applies when ``chunking=True`` and there is more than one chunk.
            Tune this down if you hit provider rate limits.
        markdown_output_path: If provided and ``extraction_rounds == 2``, the
            combined round-1 Markdown is written to this path before the
            structured pass. Useful for debugging and prompt iteration.

    Returns:
        Validated BoardGovernanceDocument.

    Raises:
        ValueError: If extraction_rounds is not recognised.
    """
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
        chunking=chunking,
        extraction_rounds=extraction_rounds,
    )

    # Determine which input chunks to use for each LLM call.
    # chunking=False: collapse everything into one synthetic chunk before any LLM call.
    if not chunking and chunks:
        combined_text = "\n\n".join(c.text for c in chunks)
        effective_chunks = [TextChunk(combined_text, chunks[0].start_page, chunks[-1].end_page)]
    else:
        effective_chunks = chunks

    summary_text: str = ""  # populated in each branch, used for board summary extraction
    is_markdown_summary = False

    if extraction_rounds == 2:
        # Round 1: extract each (effective) chunk to Markdown — parallel when chunking=True.
        markdown_parts = _run_parallel(
            _extract_chunk_markdown,
            effective_chunks,
            provider,
            company_name,
            filing_type,
            fiscal_year_end,
            max_workers=max_chunk_workers,
        )
        combined_markdown = "\n\n---\n\n".join(p for p in markdown_parts if p)

        logger.info(
            "markdown_rounds_complete",
            num_parts=len(markdown_parts),
            total_markdown_chars=len(combined_markdown),
        )

        if markdown_output_path is not None:
            markdown_output_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_output_path.write_text(combined_markdown, encoding="utf-8")
            logger.info("markdown_saved", path=str(markdown_output_path))

        # Round 2: convert combined Markdown to structured Directors in one call.
        merged_directors = _structured_from_markdown(
            provider, combined_markdown, company_name, filing_type, fiscal_year_end
        )
        summary_text = combined_markdown
        is_markdown_summary = True
    else:
        # Single round: direct structured extraction — parallel when chunking=True.
        all_director_lists = _run_parallel(
            _extract_chunk,
            effective_chunks,
            provider,
            company_name,
            filing_type,
            fiscal_year_end,
            max_workers=max_chunk_workers,
        )
        # single_pass produces one chunk so dedup is a no-op, but it's harmless.
        merged_directors = _deduplicate_directors(all_director_lists)
        summary_text = "\n\n".join(c.text for c in effective_chunks)

    logger.info(
        "extraction_complete",
        company=company_name,
        total_directors=len(merged_directors),
        chunking=chunking,
        extraction_rounds=extraction_rounds,
    )

    # Extract and compute board-level summary.
    board_summary = _extract_board_summary(
        provider, summary_text, company_name, filing_type, fiscal_year_end,
        is_markdown=is_markdown_summary,
    )
    board_summary = _compute_board_summary(board_summary, merged_directors)

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

    return BoardGovernanceDocument(company=metadata, directors=merged_directors, board_summary=board_summary)
