"""Orchestrate LLM calls across chunks and merge partial Director lists."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import RootModel

from gov_extract.extraction.chunker import TextChunk
from gov_extract.extraction.prompts import system_prompt, user_prompt
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
) -> BoardGovernanceDocument:
    """Run the full extraction pipeline over all chunks.

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

    Returns:
        Validated BoardGovernanceDocument.
    """
    logger.info(
        "extraction_started",
        company=company_name,
        num_chunks=len(chunks),
        provider=provider_name,
        model=model_name,
    )

    all_director_lists: list[list[Director]] = []
    for chunk in chunks:
        directors = _extract_chunk(provider, chunk, company_name, filing_type, fiscal_year_end)
        all_director_lists.append(directors)

    merged_directors = _deduplicate_directors(all_director_lists)
    logger.info(
        "extraction_complete",
        company=company_name,
        total_directors=len(merged_directors),
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
