# Board Governance Extractor

Extract structured board-of-directors governance data from PDF filings (annual reports, proxy statements) using an LLM, and export the results as an Excel workbook and JSON file.

Supports Anthropic Claude, OpenAI (including GPT-5 and reasoning models), DeepSeek, and Azure OpenAI.

---

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Provider Setup](#provider-setup)
- [Quick Start](#quick-start)
- [Commands](#commands)
  - [extract](#extract)
  - [validate](#validate)
  - [evaluate](#evaluate)
  - [evaluate-corpus](#evaluate-corpus)
- [Extraction Strategies](#extraction-strategies)
- [Configuration Reference](#configuration-reference)
- [Output Format](#output-format)
- [Schema Generation](#schema-generation)
- [Evaluation Harness](#evaluation-harness)

---

## Features

- Extracts per-director biographical details, board roles, committee memberships, and meeting attendance from any PDF with a text layer
- Extracts board-level governance statistics: CEO/chair separation, voting standard, board size, % women, % independent, average age and tenure
- Exports to a five-sheet Excel workbook and a validated JSON file
- Supports Anthropic Claude, OpenAI (including reasoning models o1/o3/o4/gpt-5), DeepSeek, and Azure OpenAI via a pluggable provider layer
- Four configurable extraction strategies combining page chunking (`chunking: true/false`) and LLM pass count (`extraction_rounds: 1/2`)
- Offline evaluation harness with field-level metrics, regression gating, and Excel/JSON reports

---

## Installation

Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```bash
# Clone the repository
git clone <repo-url>
cd board-governance-extractor

# Install all dependencies (including evaluation and dev extras)
uv sync --extra eval --extra dev
```

To install only the core extraction dependencies (no evaluation tools):

```bash
uv sync
```

---

## Provider Setup

Copy `.env.example` to `.env` and fill in the credentials for your chosen provider. Never commit `.env`.

```bash
cp .env.example .env
```

**.env contents:**

```dotenv
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# OpenAI / DeepSeek
OPENAI_API_KEY=sk-...
# OPENAI_BASE_URL=https://api.deepseek.com   # uncomment for DeepSeek

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_API_VERSION=2024-08-01-preview
AZURE_OPENAI_DEPLOYMENT=gpt-4o
```

Select the active provider and model in `config.yaml` (see [Configuration Reference](#configuration-reference)), or pass `--provider` / `--model` flags at runtime.

---

## Quick Start

```bash
# Extract board governance data from a local PDF
uv run gov-extract extract \
  --input examples/2025-lbg-annual-report.pdf \
  --company "Lloyds Banking Group" \
  --year 2025 \
  --provider anthropic \
  --model claude-sonnet-4-6 \
  --output-dir ./outputs

# Validate the output JSON against the schema
uv run gov-extract validate \
  --json outputs/LloydsBankingGroup_2025_Board_Governance.json

# Evaluate against a ground-truth annotation
uv run gov-extract evaluate \
  --extracted outputs/LloydsBankingGroup_2025_Board_Governance.json \
  --ground-truth tests/fixtures/lbg_ground_truth.json \
  --output-dir ./outputs
```

---

## Commands

### extract

Extract structured board governance data from a PDF filing.

```
gov-extract extract
  --input <pdf_path_or_url>   Local file path or HTTPS URL to the PDF
  --company <name>            Company name (used in output filenames)
  --year <fiscal_year>        Fiscal year, e.g. 2025
  [--provider <name>]         LLM provider: anthropic | openai | azure_openai
  [--model <model_id>]        Model ID, e.g. claude-sonnet-4-6 or gpt-4o
  [--filing-type <type>]      Default: "Annual Report"
  [--fiscal-year-end <date>]  ISO-8601 date, e.g. 2025-12-31. Default: {year}-12-31
  [--ticker <symbol>]         Company ticker symbol
  [--report-date <date>]      Report publication date (ISO-8601)
  [--page-hint <page>]        Approximate governance section start page
  [--output-dir <path>]       Output directory. Default: ./outputs
  [--config <path>]           Path to a custom config.yaml
```

**Examples:**

```bash
# From a local file, using Azure OpenAI
uv run gov-extract extract \
  --input filings/hsbc-ar-2024.pdf \
  --company HSBC \
  --year 2024 \
  --provider azure_openai \
  --output-dir ./outputs

# From a URL (PDF is downloaded and cached)
uv run gov-extract extract \
  --input https://example.com/annual-report-2025.pdf \
  --company "Acme Corp" \
  --year 2025 \
  --provider openai \
  --model gpt-4o
```

Output files:

- `{output_dir}/{Company}_{Year}_Board_Governance.xlsx`
- `{output_dir}/{Company}_{Year}_Board_Governance.json`

---

### validate

Validate a JSON output file against the JSON Schema and Pydantic model. Useful for checking ground-truth files or debugging extraction output.

```
gov-extract validate
  --json <file.json>   Path to the JSON file to validate
  [--config <path>]
```

```bash
uv run gov-extract validate --json outputs/LloydsBankingGroup_2025_Board_Governance.json
# Valid! 11 directors, company: Lloyds Banking Group
```

Exits with code 1 on validation failure.

---

### evaluate

Compare an extracted JSON against a manually-annotated ground-truth JSON. Produces field-level metrics, a regression gate check, and three output artefacts.

```
gov-extract evaluate
  --extracted <extracted.json>
  --ground-truth <ground_truth.json>
  [--output-dir <path>]
  [--thresholds <thresholds.yaml>]
  [--fail-on-regression]       Exit 1 if any regression gate threshold is breached
  [--config <path>]
```

```bash
uv run gov-extract evaluate \
  --extracted outputs/LloydsBankingGroup_2025_Board_Governance.json \
  --ground-truth tests/fixtures/lbg_ground_truth.json \
  --output-dir ./outputs \
  --fail-on-regression
```

Outputs written to `--output-dir`:

- `evaluation_report.json` — machine-readable nested results (document → director → field)
- `evaluation_report.xlsx` — one row per (director × field) with conditional formatting
- Stdout summary table (via `rich`) — headline metrics, per-field-type pass rates, five worst fields

---

### evaluate-corpus

Evaluate multiple extracted/ground-truth pairs in one run and aggregate corpus-level metrics.

```
gov-extract evaluate-corpus
  --extracted-dir <dir/>      Directory containing *_extracted.json files
  --ground-truth-dir <dir/>   Directory containing matching *_ground_truth.json files
  [--output-dir <path>]
  [--thresholds <thresholds.yaml>]
  [--config <path>]
```

Files are matched by stem: `lbg_extracted.json` pairs with `lbg_ground_truth.json`.

```bash
uv run gov-extract evaluate-corpus \
  --extracted-dir ./outputs/extracted \
  --ground-truth-dir ./tests/fixtures \
  --output-dir ./outputs/corpus_eval
```

---

## Extraction Strategies

Two independent config options control how extraction is performed:

### `chunking`

Controls whether governance page text is split into chunks before being sent to the LLM.

| Value | Behaviour |
|-------|-----------|
| `true` (default) | Pages are split into overlapping chunks (≤ `max_pages_per_chunk`). Each chunk is extracted independently; results are merged by fuzzy director-name matching. Handles documents of any size. |
| `false` | All governance pages are concatenated into a single text and sent to the LLM in one call. Simpler baseline; may exceed context limits on very long documents. |

### `extraction_rounds`

Controls the number of LLM passes per input unit.

| Value | Behaviour |
|-------|-----------|
| `1` (default) | Direct structured-output extraction. The LLM is given the raw page text and must return valid JSON in one shot. |
| `2` | Two-pass: the LLM first extracts all information as free-form **Markdown** (no schema constraints, maximising recall), then a second LLM call converts the combined Markdown to structured JSON. Typically improves data completeness at the cost of one extra API call. |

### Combinations

These two settings are fully orthogonal, giving four strategies:

| `chunking` | `extraction_rounds` | Description |
|------------|---------------------|-------------|
| `true` | `1` | Default. Per-chunk structured output, results merged. |
| `true` | `2` | Per-chunk Markdown extraction, combined, then one structured pass. |
| `false` | `1` | All text in one structured call (baseline). |
| `false` | `2` | All text to one Markdown call, then one structured call. |

Configure in `config.yaml`:

```yaml
llm:
  chunking: true       # true = chunk pages; false = single pass
  extraction_rounds: 1 # 1 | 2
```

---

## Configuration Reference

All runtime configuration lives in `config.yaml`. Secrets (API keys, endpoints) are loaded exclusively from environment variables or `.env` — never from `config.yaml`.

```yaml
llm:
  default_provider: anthropic        # anthropic | openai | azure_openai
  default_model: claude-sonnet-4-6
  judge_provider: openai             # provider used for LLM-based evaluation metrics
  judge_model: gpt-4o-mini
  temperature: 0                     # must be 0 for reproducibility
  reasoning_effort: null             # null = auto-detect; or "low" | "medium" | "high"
                                     # applies to OpenAI o1/o3/o4/gpt-5 series
  chunking: true                     # true = chunk pages; false = single pass
  extraction_rounds: 1               # 1 (direct structured) | 2 (markdown then structured)
  max_retries: 5
  timeout_seconds: 120

pdf:
  cache_dir: "~/.gov_extract/cache"  # downloaded PDFs are cached here
  max_pages_per_chunk: 15            # pages per chunk in "chunked" mode
  governance_keywords:               # keywords used to detect governance sections
    - "board of directors"
    - "directors' report"
    - "our board"
    - "committee report"
    - "proxy statement"
    - "governance"

output:
  default_dir: "./outputs"

logging:
  level: INFO
  format: json      # "json" (structured log file) | "console" (human-readable)
  file: "gov_extract.log"

evaluation:
  field_metrics:                     # metric function per field path
    "biographical.full_name": exact_match
    "biographical.career_summary": llm_semantic_similarity
    # ... (see config.yaml for full list)
  thresholds:
    fuzzy_match: 90.0
    list_f1: 0.90
    semantic_similarity: 0.80
    numeric_error_tolerance: 0.05
  regression_gate:
    document_field_pass_rate: 0.90
    director_perfect_match_rate: 0.50
    hallucination_rate: 0.05
```

### `reasoning_effort` (OpenAI GPT-5 / o-series models)

OpenAI's reasoning models (o1, o3, o4-mini, gpt-5 and later) use a `reasoning_effort` parameter instead of `temperature`. The provider auto-detects this from the model name, defaulting to `"medium"`. Override explicitly if needed:

```yaml
llm:
  default_provider: openai
  default_model: gpt-5
  reasoning_effort: high   # "low" | "medium" | "high"
```

For non-reasoning models (e.g. `gpt-4o`), `reasoning_effort` is ignored and `temperature` is used.

---

## Output Format

### Excel Workbook

Five sheets — the first is a high-level summary, the rest cover per-director detail:

| Sheet | Contents |
|-------|----------|
| Board Summary | Aggregate governance metrics: CEO/chair separation, voting standard, board size, avg age/tenure, % women, % independent |
| Board Overview | All directors, all key fields — master reference |
| Biographical Details | Name, age, nationality, qualifications, expertise, career summary, external directorships |
| Committee Memberships | Director × committee matrix: `C` (chair), `M` (member), `–` (not a member) |
| Meeting Attendance | Board and per-committee attendance with traffic-light percentage colouring |

### JSON File

Validates against `schemas/board_governance.schema.json` (JSON Schema Draft 2020-12). Top-level structure:

```json
{
  "company": {
    "company_name": "Lloyds Banking Group",
    "filing_type": "Annual Report",
    "fiscal_year_end": "2024-12-31",
    "llm_provider": "anthropic",
    "llm_model": "claude-sonnet-4-6",
    "extraction_timestamp": "2025-04-30T10:00:00+00:00"
  },
  "directors": [
    {
      "biographical": { "full_name": "Sir Robin Budenberg CBE", ... },
      "board_role": { ... },
      "attendance": { ... }
    }
  ],
  "board_summary": {
    "ceo_chair_separated": true,
    "voting_standard": "Majority",
    "board_size": 11,
    "num_executive_directors": 2,
    "num_non_executive_directors": 9,
    "num_independent_directors": 9,
    "pct_women": 45.5,
    "pct_independent": 81.8,
    "avg_director_age": 58.3,
    "avg_tenure_years": 4.7,
    "notes": null
  }
}
```

---

## Schema Generation

The JSON Schema is generated from the Pydantic models and committed to `schemas/board_governance.schema.json`. Regenerate it after any model change:

```bash
uv run python -m gov_extract.models.generate_schema
```

Validate an existing output file against the schema only (no Pydantic):

```bash
uv run gov-extract validate --json <file.json>
```

---

## Evaluation Harness

The evaluation harness scores extraction quality by comparing a machine-extracted JSON against a manually-annotated ground-truth JSON.

### Metrics by field type

| Field type | Metric |
|------------|--------|
| Name, role, nationality | Fuzzy match (threshold 90) |
| Enums (designation, independence) | Exact match |
| Dates | Exact ISO-8601 match; year-only fallback |
| Numeric (age, tenure, attendance counts) | Relative error ≤ 5% |
| Lists (committees, expertise, qualifications) | Set-based F1 (threshold 0.90) |
| Free text (career summary) | LLM semantic similarity (threshold 0.80) |

### Failure modes

Every field result carries a `failure_mode`:

| Mode | Meaning |
|------|---------|
| `false_negative` | Extraction returned `null`, ground truth is non-null (missed value) |
| `hallucination` | Extraction returned a value, ground truth is `null` (invented value) |
| `below_threshold` | Both present but score below threshold |
| `null` | Field passed |

### Regression gate

`--fail-on-regression` causes `evaluate` to exit with code 1 if any threshold in `config.yaml` is breached — suitable for CI pipelines:

```yaml
evaluation:
  regression_gate:
    document_field_pass_rate: 0.90    # overall (director × field) pass rate
    director_perfect_match_rate: 0.50  # fraction of directors with every field passing
    hallucination_rate: 0.05           # fraction of extracted values with no GT counterpart
```

### Creating ground-truth files

Ground-truth JSON files are authored manually. Use `validate` to confirm the file is schema-compliant before using it in evaluation:

```bash
uv run gov-extract validate --json tests/fixtures/lbg_ground_truth.json
```

The structure is identical to the extraction output. The reference ground-truth for Lloyds Banking Group is at `tests/fixtures/lbg_ground_truth.json`.

---

## Development

```bash
# Run unit tests with coverage
uv run pytest tests/unit/ -v --cov=src/gov_extract --cov-report=term-missing

# Lint and format
uv run ruff check . && uv run ruff format .

# Type-check
uv run mypy src/
```

Integration tests (require API keys) are skipped automatically if the relevant environment variable is absent.
