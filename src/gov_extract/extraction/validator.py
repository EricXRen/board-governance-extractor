"""JSON Schema + Pydantic validation of extracted governance data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import structlog
from pydantic import ValidationError

from gov_extract.models.document import BoardGovernanceDocument

logger = structlog.get_logger()

_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent.parent / "schemas" / "board_governance.schema.json"
)


def load_schema() -> dict[str, Any]:
    """Load the JSON Schema from disk.

    Returns:
        Parsed JSON Schema dict.
    """
    if not _SCHEMA_PATH.exists():
        logger.warning("schema_not_found", path=str(_SCHEMA_PATH))
        return {}
    with open(_SCHEMA_PATH) as f:
        return json.load(f)


def validate_json(data: dict[str, Any]) -> BoardGovernanceDocument:
    """Validate a dict against the JSON Schema and Pydantic model.

    Args:
        data: Parsed JSON dict to validate.

    Returns:
        Validated BoardGovernanceDocument instance.

    Raises:
        ValidationError: If Pydantic validation fails (hard failure).
    """
    schema = load_schema()
    if schema:
        try:
            jsonschema.validate(data, schema)
        except jsonschema.ValidationError as e:
            logger.warning("jsonschema_validation_warning", error=str(e.message))

    try:
        doc = BoardGovernanceDocument.model_validate(data)
    except ValidationError as e:
        logger.error("pydantic_validation_error", errors=e.errors())
        raise

    return doc


def validate_json_file(path: Path) -> BoardGovernanceDocument:
    """Load and validate a JSON file.

    Args:
        path: Path to the JSON file.

    Returns:
        Validated BoardGovernanceDocument.
    """
    with open(path) as f:
        data = json.load(f)
    return validate_json(data)
