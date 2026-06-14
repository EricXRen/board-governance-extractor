"""LangExtract-based extraction backend for director data."""

from __future__ import annotations

import os
from typing import Any

import structlog

from gov_extract.models.director import (
    AttendanceDetails,
    BiographicalDetails,
    BoardRoleDetails,
    Director,
    SourceReference,
)

logger = structlog.get_logger()

_VALID_DESIGNATIONS = frozenset(["Executive Director", "Non-Executive Director", "Chair"])
_VALID_INDEPENDENCE = frozenset(
    [
        "Independent",
        "Not Independent",
        "Chair (independent on appointment)",
        "N/A (Executive)",
    ]
)


def _str_attr(attributes: dict[str, Any], key: str) -> str | None:
    """Extract a string attribute, returning None for missing/null/empty values."""
    val = attributes.get(key)
    if val is None or val == "null" or val == "":
        return None
    return str(val).strip() or None


def _int_attr(attributes: dict[str, Any], key: str) -> int | None:
    """Extract an int attribute, returning None on missing or parse failure."""
    val = attributes.get(key)
    if val is None or val == "null" or val == "":
        return None
    try:
        return int(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _float_attr(attributes: dict[str, Any], key: str) -> float | None:
    """Extract a float attribute, returning None on missing or parse failure."""
    val = attributes.get(key)
    if val is None or val == "null" or val == "":
        return None
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _list_attr(attributes: dict[str, Any], key: str) -> list[str]:
    """Extract a list attribute; handles list or semicolon-delimited string."""
    val = attributes.get(key)
    if not val:
        return []
    if isinstance(val, list):
        return [str(v).strip() for v in val if v and str(v).strip()]
    if isinstance(val, str):
        if val in ("null", ""):
            return []
        return [v.strip() for v in val.split(";") if v.strip()]
    return []


def _extraction_to_director(
    extraction: Any,
    text: str,
    page_offsets: list[tuple[int, int]],
) -> Director | None:
    """Map a single flat LangExtract Extraction to a Director Pydantic model.

    Args:
        extraction: A langextract Extraction with extraction_class, extraction_text,
            attributes dict, and char_interval.
        text: The full combined governance text passed to LangExtract.
        page_offsets: List of (page_number, start_offset) in ascending offset order,
            used to derive page_number from char_interval.

    Returns:
        Director, or None if extraction_class != 'director' or full_name is absent.
    """
    if extraction.extraction_class != "director":
        return None

    attrs: dict[str, Any] = extraction.attributes or {}
    full_name = _str_attr(attrs, "full_name") or (extraction.extraction_text or "").strip()
    if not full_name:
        return None

    designation_raw = _str_attr(attrs, "designation")
    designation = (
        designation_raw if designation_raw in _VALID_DESIGNATIONS else "Non-Executive Director"
    )
    independence_raw = _str_attr(attrs, "independence_status")
    independence = independence_raw if independence_raw in _VALID_INDEPENDENCE else "Independent"
    board_role_str = _str_attr(attrs, "board_role") or designation
    year_end_status = _str_attr(attrs, "year_end_status") or "Active"

    biographical = BiographicalDetails(
        full_name=full_name,
        post_nominals=_str_attr(attrs, "post_nominals"),
        age=_int_attr(attrs, "age"),
        age_band=_str_attr(attrs, "age_band"),
        gender=_str_attr(attrs, "gender"),
        affiliation=_str_attr(attrs, "affiliation"),
        career_summary=_str_attr(attrs, "career_summary"),
    )

    board_role = BoardRoleDetails(
        designation=designation,  # type: ignore[arg-type]
        board_role=board_role_str,
        independence_status=independence,  # type: ignore[arg-type]
        year_joined_board=_int_attr(attrs, "year_joined_board"),
        date_joined_board=_str_attr(attrs, "date_joined_board"),
        tenure_years=_float_attr(attrs, "tenure_years"),
        term_end_year=_int_attr(attrs, "term_end_year"),
        year_end_status=year_end_status,
        committee_memberships=_list_attr(attrs, "committee_memberships"),
        committee_chair_of=_list_attr(attrs, "committee_chair_of"),
        other_positions=_list_attr(attrs, "other_positions"),
        num_holding_shares=_int_attr(attrs, "num_holding_shares"),
        pct_holding_shares=_float_attr(attrs, "pct_holding_shares"),
    )

    attendance = AttendanceDetails(
        board_meetings_attended=_int_attr(attrs, "board_meetings_attended"),
        board_meetings_scheduled=_int_attr(attrs, "board_meetings_scheduled"),
        board_attendance_pct=_float_attr(attrs, "board_attendance_pct"),
    )

    # Derive source_ref from char_interval (None means LangExtract flagged as hallucination)
    source_ref: SourceReference | None = None
    ci = getattr(extraction, "char_interval", None)
    if ci is not None:
        char_start: int | None = getattr(ci, "start_pos", None)
        char_end: int | None = getattr(ci, "end_pos", None)

        page_number: int | None = None
        if char_start is not None and page_offsets:
            for pg_num, pg_start in reversed(page_offsets):
                if char_start >= pg_start:
                    page_number = pg_num
                    break

        quoted_text: str | None = None
        if char_start is not None and char_end is not None:
            snippet = text[char_start:char_end]
            quoted_text = snippet[:200] if snippet else None

        source_ref = SourceReference(
            page_number=page_number,
            char_start=char_start,
            char_end=char_end,
            quoted_text=quoted_text,
        )

    return Director(
        biographical=biographical,
        board_role=board_role,
        attendance=attendance,
        source_ref=source_ref,
    )


def _get_langextract_model(llm_provider: str, llm_model: str) -> Any:
    """Return a pre-configured OpenAILanguageModel for the given provider and model.

    We bypass LangExtract's pattern-based router and always instantiate
    OpenAILanguageModel directly. This is required because DeepSeek model IDs
    (deepseek-*) match the Ollama pattern and would otherwise be misrouted.

    Args:
        llm_provider: Provider name from config (e.g. "openai", "deepseek").
        llm_model: Model ID from config (e.g. "gpt-4o", "deepseek-chat").

    Returns:
        Configured OpenAILanguageModel instance.
    """
    from langextract.providers.openai import OpenAILanguageModel  # type: ignore[import]

    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL")
    return OpenAILanguageModel(
        model_id=llm_model,
        api_key=api_key,
        base_url=base_url,
    )


def run_langextract_extraction(
    pages: dict[int, str],
    company_name: str,
    llm_provider: str,
    llm_model: str,
) -> list[Director]:
    """Run LangExtract over governance pages and return mapped Director objects.

    The full governance text is passed to LangExtract in one call.
    char_interval provenance from LangExtract is mapped to source_ref on each Director.

    Args:
        pages: Dict mapping page numbers to extracted page text.
        company_name: Company name for logging.
        llm_provider: Provider name (e.g. "openai", "deepseek").
        llm_model: Model ID (e.g. "gpt-4o", "deepseek-chat").

    Returns:
        List of Director objects with source_ref populated where LangExtract
        provides char_interval grounding.

    Raises:
        RuntimeError: If langextract is not installed.
    """
    try:
        import langextract as lx  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "langextract is required for extraction_backend='langextract'. "
            "Install it with: uv sync --extra langextract"
        ) from exc

    from gov_extract.extraction.langextract_examples import PROMPT_DESCRIPTION, get_director_examples

    examples = get_director_examples()
    model = _get_langextract_model(llm_provider, llm_model)

    # Concatenate pages in order, tracking per-page character start offsets
    sorted_pages = sorted(pages.items())
    page_offsets: list[tuple[int, int]] = []
    current_offset = 0
    for page_num, page_text in sorted_pages:
        page_offsets.append((page_num, current_offset))
        current_offset += len(page_text) + 2  # +2 for "\n\n" separator
    combined_text = "\n\n".join(text for _, text in sorted_pages)

    logger.info(
        "langextract_extraction_started",
        company=company_name,
        pages=len(pages),
        total_chars=len(combined_text),
        model=str(model),
    )

    try:
        annotated_doc = lx.extract(combined_text, PROMPT_DESCRIPTION, examples, model=model)
        raw_extractions = getattr(annotated_doc, "extractions", []) or []
    except Exception as e:
        logger.error("langextract_extraction_failed", company=company_name, error=str(e))
        return []

    directors: list[Director] = []
    for extraction in raw_extractions:
        try:
            director = _extraction_to_director(extraction, combined_text, page_offsets)
            if director is not None:
                directors.append(director)
        except Exception as e:
            logger.warning(
                "extraction_to_director_failed",
                extraction_text=getattr(extraction, "extraction_text", "?"),
                error=str(e),
            )

    logger.info(
        "langextract_extraction_complete",
        company=company_name,
        raw_extractions=len(raw_extractions),
        directors_mapped=len(directors),
    )
    return directors
