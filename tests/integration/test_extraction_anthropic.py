"""Integration test: full extraction pipeline with Anthropic (requires API key)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)

FIXTURES = Path(__file__).parent.parent / "fixtures"
LBG_PDF = Path(__file__).parent.parent.parent / "examples" / "2025-lbg-annual-report.pdf"


@pytest.mark.skipif(not LBG_PDF.exists(), reason="LBG PDF not found in examples/")
def test_lbg_extraction_passes_regression_gate(tmp_path: Path) -> None:
    """End-to-end extraction of the LBG annual report must meet quality thresholds."""
    from gov_extract.config import get_config
    from gov_extract.evaluation.evaluator import evaluate
    from gov_extract.export.json_writer import write_json
    from gov_extract.extraction.chunker import chunk_pages
    from gov_extract.extraction.extractor import run_extraction
    from gov_extract.extraction.validator import validate_json_file
    from gov_extract.llm.factory import get_provider
    from gov_extract.pdf.extractor import extract_pages_bulk
    from gov_extract.pdf.loader import load_pdf
    from gov_extract.pdf.page_finder import find_governance_pages

    cfg = get_config()
    provider = get_provider(cfg, "anthropic", "claude-sonnet-4-6")

    pdf_path = load_pdf(str(LBG_PDF))
    pages = extract_pages_bulk(pdf_path)
    ranges = find_governance_pages(pages, cfg.pdf.governance_keywords)

    gov_pages: dict[int, str] = {}
    for r in ranges:
        for p in r.pages():
            if p in pages:
                gov_pages[p] = pages[p]

    chunks = chunk_pages(gov_pages, max_tokens=cfg.pdf.max_pages_per_chunk * 600)
    doc = run_extraction(
        provider=provider,
        chunks=chunks,
        company_name="Lloyds Banking Group",
        filing_type="Annual Report",
        fiscal_year_end="2024-12-31",
        source_pdf_path=str(LBG_PDF),
        provider_name="anthropic",
        model_name="claude-sonnet-4-6",
    )

    json_path = tmp_path / "extracted.json"
    write_json(doc, json_path)

    gt_doc = validate_json_file(FIXTURES / "lbg_ground_truth.json")
    field_metrics = cfg.evaluation.field_metrics
    thresholds = {
        "fuzzy_match": cfg.evaluation.thresholds.fuzzy_match,
        "list_f1": cfg.evaluation.thresholds.list_f1,
        "semantic_similarity": cfg.evaluation.thresholds.semantic_similarity,
        "numeric_error_tolerance": cfg.evaluation.thresholds.numeric_error_tolerance,
    }

    result = evaluate(doc, gt_doc, field_metrics, thresholds)

    assert result.document_field_pass_rate >= 0.90, (
        f"document_field_pass_rate {result.document_field_pass_rate:.3f} < 0.90"
    )
    assert result.hallucination_rate <= 0.05, (
        f"hallucination_rate {result.hallucination_rate:.3f} > 0.05"
    )

    committee_pass = result.per_field_pass_rate.get("board_role.committee_memberships", 0.0)
    assert committee_pass >= 0.95, f"committee_memberships F1 {committee_pass:.3f} < 0.95"
