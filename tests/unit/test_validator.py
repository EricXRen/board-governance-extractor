"""Unit tests for JSON schema validation."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from gov_extract.extraction.validator import validate_json, validate_json_file
from gov_extract.models.document import BoardGovernanceDocument


def _minimal_doc_dict() -> dict:
    return {
        "company": {
            "company_name": "Test Co",
            "filing_type": "Annual Report",
            "fiscal_year_end": "2025-12-31",
            "source_pdf_path": "/tmp/test.pdf",
            "extraction_timestamp": "2025-01-01T00:00:00+00:00",
            "llm_provider": "anthropic",
            "llm_model": "claude-sonnet-4-6",
        },
        "directors": [],
    }


class TestValidateJson:
    def test_valid_empty_directors(self) -> None:
        doc = validate_json(_minimal_doc_dict())
        assert isinstance(doc, BoardGovernanceDocument)
        assert doc.directors == []

    def test_valid_with_director(self, sample_document: BoardGovernanceDocument) -> None:
        data = sample_document.model_dump(mode="json")
        doc = validate_json(data)
        assert len(doc.directors) == 1

    def test_missing_required_field_raises(self) -> None:
        bad = _minimal_doc_dict()
        del bad["company"]["company_name"]
        with pytest.raises(ValidationError):
            validate_json(bad)

    def test_invalid_designation_raises(self) -> None:
        data = _minimal_doc_dict()
        data["directors"] = [
            {
                "biographical": {"full_name": "Test Person"},
                "board_role": {
                    "designation": "INVALID",
                    "board_role": "NED",
                    "independence_status": "Independent",
                    "year_end_status": "Active",
                },
                "attendance": {},
            }
        ]
        with pytest.raises(ValidationError):
            validate_json(data)


class TestValidateJsonFile:
    def test_valid_file(self, sample_document: BoardGovernanceDocument) -> None:
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(sample_document.model_dump(mode="json"), f)
            path = Path(f.name)

        doc = validate_json_file(path)
        assert doc.company.company_name == sample_document.company.company_name
        path.unlink()

    def test_nonexistent_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            validate_json_file(Path("/nonexistent/path.json"))
