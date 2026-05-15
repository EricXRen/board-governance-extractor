"""System and user prompt templates for governance data extraction."""

from __future__ import annotations

import json

from gov_extract.models.board_summary import BoardSummary
from gov_extract.models.director import Director
from gov_extract.models.director_election import DirectorElection


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
- For lists (other_positions, committee_memberships, etc.), return an empty list [] if nothing is stated.
- For full_name, extract only the given name and surname — strip any pre-nominals (Sir, Lord, Dr) and post-nominals (CBE, OBE, FCA, etc.). Store post-nominals separately in the post_nominals field.
- Return a JSON object `{{"directors": [...]}}` containing all Director objects. If no directors are found, return `{{"directors": []}}`.

The Director object schema is:
```json
{schema}
```

Output format: Return a JSON object `{{"directors": [...]}}` where each element matches the Director schema exactly."""


def markdown_system_prompt() -> str:
    """Return the system prompt for the first round of two-round extraction.

    The model is asked to produce rich Markdown — no schema constraints, no
    JSON formatting pressure — so it can focus entirely on recall.

    Returns:
        System prompt string.
    """
    return """You are a governance data analyst extracting board director information from corporate filings.

Your task is to read the provided filing text and produce a comprehensive Markdown document that captures ALL board director information present.

CRITICAL INSTRUCTIONS:
- Extract ONLY what is explicitly stated in the text. Do NOT infer, guess, or fabricate.
- For each director, create a section headed with their full name (given name + surname only; strip pre-nominals and post-nominals from the heading but note them separately).
- Under each director, include every available detail as labelled bullet points, for example:
  - **Role / Designation:** Non-Executive Director
  - **Board role:** Senior Independent Director
  - **Independence:** Independent
  - **Year joined:** 2018 / Date joined: 2018-03-01
  - **Tenure:** 7 years
  - **Term end year:** 2027
  - **Age / Age band:** 58 / 55–60
  - **Gender:** Female
  - **Post-nominals:** CBE
  - **Affiliation:** University of Oxford
  - **Committee memberships:** Audit Committee (Member), Risk Committee (Chair)
  - **Other positions:** Senior Independent Director
  - **Shares held:** 12,500 / % of outstanding: 0.002%
  - **Career summary:** <biography as written>
  - **Board attendance:** 10/12
  - **Committee attendance:** Audit Committee 7/7, Risk Committee 5/6
  - **Year-end status:** Active
- If a field is not present in the text, omit it entirely — do not write "N/A" or "unknown".
- Preserve exact wording for names, dates, and titles."""


def markdown_user_prompt(
    chunk_text: str,
    company_name: str,
    filing_type: str,
    fiscal_year_end: str,
    start_page: int,
    end_page: int,
) -> str:
    """Return the user prompt for the first (markdown) round.

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

Extract all board director information and present it as a Markdown document with one section per director.

--- BEGIN TEXT ---
{chunk_text}
--- END TEXT ---

Produce a Markdown document covering every director mentioned. Capture all available details."""


def structured_from_markdown_system_prompt() -> str:
    """Return the system prompt for the second (structuring) round.

    The model receives curated Markdown from round one and converts it to the
    Director JSON schema — less cognitive load than working from raw PDF text.

    Returns:
        System prompt string with embedded Director JSON schema.
    """
    schema = json.dumps(Director.model_json_schema(), indent=2)
    return f"""You are a governance data analyst converting a Markdown summary into structured JSON.

You have been given a Markdown document that was carefully extracted from a corporate filing. Your task is to convert it into a JSON array of Director objects.

CRITICAL INSTRUCTIONS:
- Convert ONLY what is present in the Markdown. Do NOT infer, guess, or hallucinate.
- Return `null` for any field not mentioned in the Markdown.
- For lists (other_directorships, other_positions, etc.), return [] if nothing is stated.
- For full_name, use only the given name and surname — strip any pre-nominals and post-nominals.
- Return a JSON object `{{"directors": [...]}}` containing all Director objects. If no directors are present, return `{{"directors": []}}`.

The Director object schema is:
```json
{schema}
```

Output format: Return a JSON object `{{"directors": [...]}}` where each element matches the Director schema exactly."""


def structured_from_markdown_user_prompt(
    markdown_text: str,
    company_name: str,
    filing_type: str,
    fiscal_year_end: str,
) -> str:
    """Return the user prompt for the second (structuring) round.

    Args:
        markdown_text: Combined Markdown from all first-round extractions.
        company_name: Name of the company.
        filing_type: e.g. "Annual Report".
        fiscal_year_end: ISO-8601 date string.

    Returns:
        Formatted user prompt string.
    """
    return f"""The following Markdown was extracted from the {filing_type} for {company_name} (fiscal year ending {fiscal_year_end}).

Convert this into a JSON object `{{"directors": [...]}}` matching the provided schema.

--- BEGIN MARKDOWN ---
{markdown_text}
--- END MARKDOWN ---

Return a JSON object `{{"directors": [...]}}` containing every director present in the Markdown."""


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

Return a JSON object `{{"directors": [...]}}` containing every director you can identify from this text."""


def board_summary_system_prompt() -> str:
    """Return the system prompt for board-level summary extraction.

    Returns:
        System prompt string with embedded BoardSummary JSON schema.
    """
    schema = json.dumps(BoardSummary.model_json_schema(), indent=2)
    return f"""You are a governance data analyst extracting board-level summary statistics from corporate filings.

Your task is to extract aggregate governance metrics for the full board — NOT per-director details.

CRITICAL INSTRUCTIONS:
- Extract ONLY what is explicitly stated in the text. Do NOT infer, guess, or hallucinate.
- Return `null` for any field not present in the text.
- For percentage fields (pct_women, pct_independent), return a number between 0 and 100.
- For ceo_chair_separated: return true if the CEO and Chair are explicitly stated to be different people, false if the same person holds both roles, null if not stated.
- For voting_standard: return "Majority" or "Plurality" only if the director election voting standard is explicitly stated.
- The notes field may capture any other stated board governance policy (e.g. board tenure policy, retirement age, diversity targets).

The BoardSummary schema is:
```json
{schema}
```

Output format: Return a single BoardSummary JSON object (not an array)."""


def board_summary_user_prompt(
    text: str,
    company_name: str,
    filing_type: str,
    fiscal_year_end: str,
    is_markdown: bool = False,
) -> str:
    """Return the user prompt for board summary extraction.

    Args:
        text: Governance text or markdown to extract from.
        company_name: Name of the company.
        filing_type: e.g. "Annual Report".
        fiscal_year_end: ISO-8601 date string.
        is_markdown: True when ``text`` is a pre-extracted Markdown summary
            rather than raw filing text.

    Returns:
        Formatted user prompt string.
    """
    source_label = "Markdown summary extracted from" if is_markdown else "text extracted from"
    return f"""The following is {source_label} the {filing_type} for {company_name} (fiscal year ending {fiscal_year_end}).

Extract the board-level governance summary statistics.

Look especially for:
- Whether CEO and Board Chair roles are held by the same or different people
- The voting standard used for director elections (majority vs plurality)
- Total number of directors on the board
- Number of executive, non-executive, and independent directors
- Percentage of women on the board
- Percentage of independent directors
- Average director age
- Average director tenure
- Any stated board governance policies

--- BEGIN TEXT ---
{text}
--- END TEXT ---

Return a single BoardSummary JSON object."""


def director_election_system_prompt() -> str:
    """Return the system prompt for director election extraction.

    Returns:
        System prompt string with embedded DirectorElection JSON schema.
    """
    schema = json.dumps(DirectorElection.model_json_schema(), indent=2)
    return f"""You are a governance data analyst extracting director election information from corporate filings.

Your task is to find the director election section (annual general meeting agenda, proxy vote proposal, or similar) and extract structured data.

CRITICAL INSTRUCTIONS:
- Extract ONLY what is explicitly stated in the text. Do NOT infer, guess, or hallucinate.
- Return `null` for the entire object if there is no director election section in the text.
- For `candidates_disclosed`: return `false` only when the filing explicitly states that candidate names are withheld or confidential. Return `true` when candidate names are listed. Return `null` if the filing does not comment on disclosure.
- `incumbent_nominees` are current board members standing for re-election. `new_nominees` are candidates not currently on the board.
- For each candidate in `candidates`, extract as much biographical and role detail as is stated — return `null` for any field not present.
- For candidate `full_name`, strip pre-nominals and post-nominals (same rule as current directors).

The DirectorElection schema is:
```json
{schema}
```

Output format: Return a single DirectorElection JSON object, or `null` if no election section exists."""


def director_election_user_prompt(
    text: str,
    company_name: str,
    filing_type: str,
    fiscal_year_end: str,
    is_markdown: bool = False,
) -> str:
    """Return the user prompt for director election extraction.

    Args:
        text: Full governance text or combined round-1 markdown.
        company_name: Name of the company.
        filing_type: e.g. "Annual Report".
        fiscal_year_end: ISO-8601 date string.
        is_markdown: True when ``text`` is a pre-extracted Markdown summary.

    Returns:
        Formatted user prompt string.
    """
    source_label = "Markdown summary extracted from" if is_markdown else "text extracted from"
    return f"""The following is {source_label} the {filing_type} for {company_name} (fiscal year ending {fiscal_year_end}).

Find the director election section (AGM agenda, proxy statement proposals, or similar) and extract:
- How many director seats are up for election
- Which current board members are standing for re-election (incumbent nominees)
- Which candidates are newly proposed (new nominees)
- Whether candidate names are publicly disclosed
- Full details for each candidate (use the Director schema)

If the filing contains no director election section, return null.

--- BEGIN TEXT ---
{text}
--- END TEXT ---

Return a single DirectorElection JSON object, or null if no election section exists."""
