"""Serialise BoardGovernanceDocument to a JSON file."""

from __future__ import annotations

import json
from pathlib import Path

import structlog

from gov_extract.models.document import BoardGovernanceDocument

logger = structlog.get_logger()


def write_json(doc: BoardGovernanceDocument, path: Path) -> Path:
    """Write a BoardGovernanceDocument to a JSON file.

    Args:
        doc: The document to serialise.
        path: Output file path (.json).

    Returns:
        The path written to.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = doc.model_dump(mode="json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("json_written", path=str(path), directors=len(doc.current_board.directors))
    return path


def output_path(company_name: str, fiscal_year: str, output_dir: Path) -> Path:
    """Build the canonical output file path for a JSON export.

    Args:
        company_name: Company name (spaces replaced with nothing).
        fiscal_year: e.g. "2025".
        output_dir: Directory for output files.

    Returns:
        Path like output_dir/CompanyName_2025_Board_Governance.json.
    """
    safe_name = company_name.replace(" ", "")
    return output_dir / f"{safe_name}_{fiscal_year}_Board_Governance.json"
