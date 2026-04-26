"""System and user prompt templates for governance data extraction."""

from __future__ import annotations

import json

from gov_extract.models.director import Director


def system_prompt() -> str:
    """Return the system prompt for governance extraction.

    Returns:
        System prompt string with role, instructions, and embedded JSON schema.
    """
    schema = json.dumps(Director.model_json_schema(), indent=2)
    return f"""You are a governance data analyst extracting structured information from corporate filings.

Your task is to extract board director information from the text provided and return it as structured JSON.

CRITICAL INSTRUCTIONS:
- Extract ONLY what is explicitly stated in the text. Do NOT infer, guess, or hallucinate values.
- Return `null` for any field that is not present in the text. It is better to return null than to guess.
- Do not invent committee names, dates, attendance figures, or biographical details.
- If a field is ambiguous or unclear, return null rather than guessing.
- For lists (expertise_areas, qualifications, etc.), return an empty list [] if nothing is stated.
- Return a JSON array of Director objects. If no directors are found, return [].

The Director object schema is:
```json
{schema}
```

Output format: Return a JSON array of Director objects matching the schema exactly.
Wrap your response in a JSON code block if using raw JSON mode."""


def user_prompt(
    chunk_text: str,
    company_name: str,
    filing_type: str,
    fiscal_year_end: str,
    start_page: int,
    end_page: int,
) -> str:
    """Return a user prompt for a specific text chunk.

    Args:
        chunk_text: Extracted text from the governance pages.
        company_name: Name of the company.
        filing_type: e.g. "Annual Report".
        fiscal_year_end: ISO-8601 date string.
        start_page: First page number in this chunk.
        end_page: Last page number in this chunk.

    Returns:
        Formatted user prompt string.
    """
    return f"""The following text is extracted from pages {start_page}–{end_page} of the {filing_type} for {company_name} (fiscal year ending {fiscal_year_end}).

Extract all board directors mentioned. For each director, extract all available fields according to the schema.

--- BEGIN TEXT ---
{chunk_text}
--- END TEXT ---

Return a JSON array of Director objects. Include every director you can identify from this text."""
