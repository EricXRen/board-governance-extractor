# Board Governance Extraction App — Project Plan

## Overview

| Attribute | Value |
|-----------|-------|
| Project name | `board-governance-extractor` |
| Primary language | Python 3.11+ |
| Package manager | `uv` |
| LLM data model | Pydantic v2 |
| CLI framework | Typer |
| Target completion | 5 phases across ~6 weeks |

---

## Repository Layout

```
board-governance-extractor/
├── pyproject.toml                  # uv / PEP 621 project file
├── uv.lock
├── CLAUDE.md                       # Claude Code codebase guide
├── README.md
├── .env.example                    # env-var template (never committed with secrets)
├── config.yaml                     # default runtime configuration
│
├── schemas/
│   └── board_governance.schema.json   # JSON Schema (Draft 2020-12)
│
├── src/
│   └── gov_extract/
│       ├── __init__.py
│       ├── cli.py                  # Typer CLI entrypoint
│       ├── config.py               # Config loading (config.yaml + env)
│       │
│       ├── models/
│       │   ├── __init__.py
│       │   ├── document.py         # BoardGovernanceDocument (Pydantic)
│       │   ├── director.py         # Director, sub-models
│       │   └── metadata.py         # CompanyMetadata
│       │
│       ├── pdf/
│       │   ├── __init__.py
│       │   ├── loader.py           # Load PDF from path or URL, cache
│       │   ├── extractor.py        # pdfminer text extraction per page
│       │   └── page_finder.py      # Identify governance-relevant page ranges
│       │
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── base.py             # LLMProvider protocol / ABC
│       │   ├── anthropic_provider.py
│       │   ├── openai_provider.py  # covers OpenAI + DeepSeek
│       │   ├── azure_provider.py   # Azure OpenAI (custom base_url)
│       │   └── factory.py          # provider = factory(config)
│       │
│       ├── extraction/
│       │   ├── __init__.py
│       │   ├── prompts.py          # Prompt templates (system + user)
│       │   ├── chunker.py          # Split long text into LLM-sized chunks
│       │   ├── extractor.py        # Orchestrates LLM calls → raw JSON
│       │   └── validator.py        # JSON Schema + Pydantic validation
│       │
│       ├── export/
│       │   ├── __init__.py
│       │   ├── excel_writer.py     # openpyxl — four-sheet workbook
│       │   └── json_writer.py      # serialise + write JSON file
│       │
│       └── evaluation/
│           ├── __init__.py
│           ├── metrics.py          # All field-level metric functions
│           ├── evaluator.py        # Director × field evaluation loop
│           └── report.py           # evaluation_report.json + .xlsx
│
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_models.py
│   │   ├── test_page_finder.py
│   │   ├── test_metrics.py
│   │   └── test_validator.py
│   ├── integration/
│   │   ├── test_extraction_anthropic.py   # requires ANTHROPIC_API_KEY
│   │   └── test_extraction_azure.py       # requires AZURE_* vars
│   └── fixtures/
│       ├── lbg_ground_truth.json          # manually annotated LBG data
│       ├── lbg_sample_pages.txt           # extracted text from pp.65–99
│       └── lbg_expected_schema.json
│
└── examples/
    ├── LBG_Board_Governance_2025.xlsx     # reference output
    └── run_lbg.sh                         # example CLI invocation
```

---

## Phases & Milestones

### Phase 1 — Project Scaffold & Data Model (Week 1)

**Goal:** Runnable project skeleton with validated data models and JSON schema.

| Task | Owner | Notes |
|------|-------|-------|
| 1.1 | Dev | `uv init board-governance-extractor`; configure `pyproject.toml` with all dependencies |
| 1.2 | Dev | Implement all Pydantic v2 models in `src/gov_extract/models/` |
| 1.3 | Dev | Author `schemas/board_governance.schema.json` derived from Pydantic models (`model.model_json_schema()`) |
| 1.4 | Dev | Implement `config.py` (Pydantic Settings v2, reads `config.yaml` + env vars) |
| 1.5 | Dev | Stub `cli.py` with `extract`, `evaluate`, `validate` commands (no logic yet) |
| 1.6 | Dev | Write unit tests for model validation (valid/invalid fixtures) |

**Milestone M1:** `uv run gov-extract validate --json examples/lbg_ground_truth.json` passes.

**Key dependencies:**
```toml
[project]
dependencies = [
    "anthropic>=0.40",
    "openai>=1.50",
    "pydantic>=2.9",
    "pydantic-settings>=2.5",
    "typer>=0.13",
    "pdfminer.six>=20231228",
    "openpyxl>=3.1",
    "jsonschema>=4.23",
    "httpx>=0.27",          # PDF URL download
    "tenacity>=9.0",        # retry logic
    "python-dotenv>=1.0",
    "structlog>=24.0",      # structured logging
    "rich>=13.0",           # CLI tables
]

[project.optional-dependencies]
eval = [
    "sentence-transformers>=3.0",
    "rapidfuzz>=3.9",
    "scikit-learn>=1.5",
]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.6",
    "mypy>=1.11",
]
```

---

### Phase 2 — PDF Ingestion & Page Detection (Week 1–2)

**Goal:** Reliably extract governance-relevant page ranges from any annual report.

| Task | Notes |
|------|-------|
| 2.1 — `pdf/loader.py` | Accept local path or HTTPS URL. Download with `httpx`, cache to `~/.gov_extract/cache/`. Return `Path`. |
| 2.2 — `pdf/extractor.py` | Use `pdfminer.six` to extract per-page text. Return `dict[int, str]` (1-indexed). |
| 2.3 — `pdf/page_finder.py` | Keyword-based heuristic: scan table of contents text for headings matching configurable patterns (`["board of directors", "directors' report", "governance", "proxy", "committee report"]`). Return `list[PageRange]`. Fall back to full document if ToC detection fails. |
| 2.4 — Unit tests | Test `page_finder` against the LBG sample pages fixture; assert pp.65–99 are selected. |

**Config additions (`config.yaml`):**
```yaml
pdf:
  cache_dir: "~/.gov_extract/cache"
  governance_keywords:
    - "board of directors"
    - "directors' report"
    - "our board"
    - "committee report"
    - "proxy statement"
    - "governance"
  max_pages_per_chunk: 15
```

---

### Phase 3 — LLM Provider Layer & Extraction (Week 2–3)

**Goal:** Extract structured data from governance page text using any configured LLM.

#### 3.1 — LLM Provider Abstraction (`llm/`)

```python
class LLMProvider(Protocol):
    def extract(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> BaseModel: ...
```

All providers implement `extract()` and a `extract_raw_json()` fallback. Retry is handled by `tenacity` decorators in the base class.

| Provider class | Implementation notes |
|----------------|---------------------|
| `AnthropicProvider` | Uses `client.messages.create` with `claude-*` models. Uses tool-use / structured output for JSON extraction. |
| `OpenAIProvider` | Uses `client.beta.chat.completions.parse` with `response_format=<Pydantic model>` for models that support it; falls back to `response_format={"type": "json_object"}`. Covers OpenAI and DeepSeek (same SDK, different `base_url`). |
| `AzureOpenAIProvider` | Inherits `OpenAIProvider`. Requires `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_DEPLOYMENT`. Automatically sets `openai.AzureOpenAI(base_url=..., api_version=...)`. |
| `ProviderFactory` | `factory(config: Config) -> LLMProvider` — reads provider name from config/env. |

**Environment variables:**
```
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# OpenAI / DeepSeek
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.deepseek.com   # optional override for DeepSeek

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_API_VERSION=2024-08-01-preview
AZURE_OPENAI_DEPLOYMENT=gpt-4o
```

#### 3.2 — Extraction Orchestration (`extraction/`)

**Chunker:** Split governance page text into chunks ≤ `max_tokens_per_chunk` (default 8000 tokens, estimated by character count). Each chunk overlaps by one page with the previous to avoid splitting a director's profile across chunks.

**Prompt design (`extraction/prompts.py`):**

- **System prompt:** Instructs the LLM to act as a governance data analyst, extract only what is explicitly stated, return `null` for missing fields, never hallucinate, and produce valid JSON matching the schema.
- **User prompt:** Provides the chunk text and asks for a partial `BoardGovernanceDocument` (may contain a subset of directors if a long document is chunked).
- **Merge step:** After all chunks are processed, merge partial `Director` lists by deduplicating on `full_name` (fuzzy match) and merging fields (later chunks can supplement earlier ones).

**Validator:** After extraction, validate the merged result against the JSON schema and Pydantic model. Log any validation errors; surface them as warnings (not hard failures) so partial data is not lost.

---

### Phase 4 — Export & CLI (Week 3–4)

**Goal:** Produce the two output files and a polished CLI.

#### 4.1 — Excel Writer (`export/excel_writer.py`)

Produce the same four-sheet workbook layout as `LBG_Board_Governance_2025.xlsx`:

| Sheet | Content |
|-------|---------|
| Board Overview | Master table — all directors, all key fields |
| Biographical Details | Name, age band, nationality, expertise, career, qualifications, external directorships |
| Committee Memberships | Director × committee matrix (M / C / –) |
| Meeting Attendance | Board + per-committee attendance with traffic-light % colouring |

Formatting rules (matching the reference file):
- Font: Arial throughout.
- Header rows: navy fill (`#1B3A6B`), white bold text.
- Executives: amber tint (`#FFF3CD`); Chair: indigo tint (`#E8EAF6`); NEDs: alternating white / light blue.
- Attendance %: green ≥ 100%, yellow ≥ 80%, red < 80%.
- Source footer on every sheet.

#### 4.2 — JSON Writer (`export/json_writer.py`)

Serialise the `BoardGovernanceDocument` Pydantic model with `model.model_dump(mode="json")`. Pretty-print with 2-space indent. Write to `{output_dir}/{company}_{year}_Board_Governance.json`.

#### 4.3 — CLI (`cli.py`)

```
gov-extract extract   # FR-7
gov-extract evaluate  # FR-7
gov-extract validate  # FR-7
```

All commands use `rich` for progress bars and summary tables. Errors produce structured log output and a non-zero exit code.

---

### Phase 5 — Evaluation Harness (Week 4–5)

**Goal:** Quantitatively score extraction quality against ground-truth annotations.

#### 5.1 — Metric Functions (`evaluation/metrics.py`)

```python
def exact_match(predicted: str, ground_truth: str) -> float
def fuzzy_match(predicted: str, ground_truth: str, threshold: float = 90.0) -> float
def date_match(predicted: str, ground_truth: str) -> dict   # EM + year-only
def numeric_error(predicted: float, ground_truth: float, tolerance: float) -> dict
def list_f1(predicted: list, ground_truth: list) -> dict    # precision, recall, F1
def semantic_similarity(predicted: str, ground_truth: str, threshold: float = 0.80) -> float
```

Metric dispatch is configured in `config.yaml` per field path (using dot notation, e.g. `directors[*].full_name`).

#### 5.2 — Evaluation Loop (`evaluation/evaluator.py`)

1. Load extracted JSON and ground-truth JSON; validate both against schema.
2. Match directors between the two documents by fuzzy name match (threshold 90).
3. For each matched director pair, evaluate every field using the configured metric.
4. Accumulate per-field scores.
5. For unmatched directors (false positives / false negatives), record as 0-score entries.

#### 5.3 — Report (`evaluation/report.py`)

- `evaluation_report.json`: nested structure — document-level, per-field-type, per-director, per-field.
- `evaluation_report.xlsx`: tabular, one row per (director, field), columns: field path, metric used, predicted value, ground-truth value, score, pass/fail.
- Stdout summary table (via `rich`): aggregated scores per field category.

#### 5.4 — Ground Truth for LBG

Manually author `tests/fixtures/lbg_ground_truth.json` from the data already extracted into `LBG_Board_Governance_2025.xlsx`. This serves as the canonical regression test.

---

### Phase 6 — Testing, Documentation & Polish (Week 5–6)

| Task | Notes |
|------|-------|
| 6.1 — Unit tests | Target ≥ 80% coverage on `models/`, `evaluation/metrics.py`, `extraction/validator.py`, `pdf/page_finder.py`. |
| 6.2 — Integration test | Run full `extract` pipeline against LBG PDF using each provider (gated by env vars; skipped in CI if keys absent). Compare output against `lbg_ground_truth.json` via `evaluate` command; assert document-level score ≥ 0.90. |
| 6.3 — Linting / typing | `ruff check .`, `ruff format .`, `mypy src/` with strict settings. |
| 6.4 — README | Usage guide, provider setup instructions, environment variable reference, example commands. |
| 6.5 — `.env.example` | Document all env vars with comments. |
| 6.6 — `examples/run_lbg.sh` | Runnable end-to-end demo script. |

---

## Dependency Graph (simplified)

```
Phase 1 (Models & Schema)
    └── Phase 2 (PDF Ingestion)
            └── Phase 3 (LLM Extraction)
                    └── Phase 4 (Export & CLI)
                            └── Phase 5 (Evaluation)
                                    └── Phase 6 (Testing & Docs)
```

Phases 2 and 3 can proceed in parallel once Phase 1 models are stable. Phase 5 (evaluation) can begin once the LBG ground-truth JSON is authored (end of Phase 1).

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Pydantic v2 for data model | Enables LLM structured output via schema generation; fast validation; first-class JSON serialisation. |
| `uv` only | Deterministic, fast dependency resolution; no virtualenv management burden. |
| `tenacity` for retries | Avoids bespoke retry logic; handles rate limits and transient failures uniformly across providers. |
| `sentence-transformers` optional extra | Evaluation-only dependency; keeps the core extraction install lean for corporate environments. |
| Azure as first-class provider | Corporate firewalls often only allow Azure endpoints; Azure is *not* an afterthought — it is a supported primary path. |
| Chunked extraction with overlap | Annual reports can be 300+ pages; chunking with overlap prevents director profiles being split across context windows. |
| Null over hallucination | The system prompt explicitly instructs the LLM to return `null` rather than guess; downstream evaluation penalises hallucinated values. |
