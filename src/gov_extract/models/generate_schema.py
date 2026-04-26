"""Generate the JSON Schema from Pydantic models and write to schemas/."""

import json
from pathlib import Path

from gov_extract.models.document import BoardGovernanceDocument


def generate() -> None:
    """Generate Draft 2020-12 JSON Schema from BoardGovernanceDocument."""
    schema = BoardGovernanceDocument.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["version"] = "1.0.0"

    out = Path(__file__).parent.parent.parent.parent / "schemas" / "board_governance.schema.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema, indent=2))
    print(f"Schema written to {out}")


if __name__ == "__main__":
    generate()
