# Board Governance Extraction — Product Requirements

## 1. Purpose

Build a Python command-line application that automatically extracts structured board-of-directors governance data from PDF filings (annual reports, proxy statements) for any public company, and exports the result as both an Excel workbook and a JSON file. The extraction must be driven by a Large Language Model (LLM), with support for Anthropic, OpenAI/DeepSeek, and Azure OpenAI backends. An offline evaluation harness compares extracted data against manually-annotated ground truth.

**Reference example:** `LBG_Board_Governance_2025.xlsx` (Lloyds Banking Group FY2025) defines the canonical output schema.

---

## 2. Stakeholders

| Role | Interest |
|------|----------|
| Eric (primary user) | Run extractions against any company's filing; switch LLM provider freely |
| Governance analysts | Consume structured Excel and JSON outputs downstream |
| Developers / Claude Code | Build and maintain the codebase |

---

## 3. Functional Requirements

### FR-1 — PDF Ingestion

| ID | Requirement |
|----|-------------|
| FR-1.1 | Accept a local PDF file path as input. |
| FR-1.2 | Accept a remote HTTPS URL pointing to a PDF; download and cache locally. |
| FR-1.3 | Support multi-hundred-page PDFs by chunking pages intelligently (page-range or semantic). |
| FR-1.4 | Pre-identify governance-relevant pages (e.g. "Board of Directors", "Directors' Report", "Proxy Statement", "Committee Reports") before sending to the LLM, to minimise token usage. |
| FR-1.5 | Preserve raw extracted page text alongside LLM outputs for auditability. |

### FR-2 — Data Extraction

The application must extract the following fields per director. All fields are **optional** (the LLM must emit `null` when a value is absent rather than hallucinating).

#### FR-2.1 Biographical & Professional

| Field | Type | Notes |
|-------|------|-------|
| `full_name` | string | As printed, including post-nominals (e.g. "Sir Robin Budenberg CBE") |
| `post_nominals` | string | Honours/qualifications appended to name |
| `age` | integer | If exact age is given; otherwise `null` |
| `age_band` | string | If only a band is given (e.g. "56–60") |
| `nationality` | string | As disclosed |
| `qualifications` | list[string] | Professional qualifications (e.g. ACA, MBA) |
| `expertise_areas` | list[string] | Key skills/domains as listed in the report |
| `career_summary` | string | Free-text biography as extracted |
| `other_directorships` | list[string] | External board roles held currently |

#### FR-2.2 Board Role & Independence

| Field | Type | Notes |
|-------|------|-------|
| `designation` | enum | `"Executive Director"`, `"Non-Executive Director"`, `"Chair"` |
| `board_role` | string | E.g. "Group Chief Executive", "Senior Independent Director" |
| `independence_status` | enum | `"Independent"`, `"Not Independent"`, `"Chair (independent on appointment)"`, `"N/A (Executive)"` |
| `year_joined_board` | integer | Year of board appointment |
| `date_joined_board` | string | Full date if available (ISO-8601: YYYY-MM-DD) |
| `tenure_years` | float | Computed or stated tenure in years |
| `year_end_status` | string | E.g. "Active", "Retired YYYY-MM-DD" |
| `committee_memberships` | list[string] | Names of committees the director sits on |
| `committee_chair_of` | list[string] | Names of committees the director chairs |
| `special_roles` | list[string] | E.g. "Senior Independent Director", "Chair of Scottish Widows Group" |

#### FR-2.3 Attendance & Performance

| Field | Type | Notes |
|-------|------|-------|
| `board_meetings_attended` | integer | |
| `board_meetings_scheduled` | integer | |
| `board_attendance_pct` | float | Computed as attended/scheduled |
| `committee_attendance` | list[CommitteeAttendance] | Per-committee breakdown |
| `attendance_notes` | string | Reasons for absences as disclosed |

`CommitteeAttendance` object:

```json
{
  "committee_name": "Audit Committee",
  "meetings_attended": 7,
  "meetings_scheduled": 7,
  "attendance_pct": 1.0,
  "is_chair": false
}
```

#### FR-2.4 Company Metadata (document-level)

| Field | Type | Notes |
|-------|------|-------|
| `company_name` | string | |
| `company_ticker` | string | If disclosed |
| `filing_type` | string | E.g. "Annual Report", "Proxy Statement" |
| `fiscal_year_end` | string | ISO-8601 date |
| `report_date` | string | Date of publication (ISO-8601) |
| `source_pdf_path` | string | Absolute or relative path to input file |
| `extraction_timestamp` | string | ISO-8601 UTC timestamp of when extraction ran |
| `llm_provider` | string | E.g. "anthropic", "openai", "azure_openai" |
| `llm_model` | string | E.g. "claude-opus-4-6" |

### FR-3 — Output: Excel Workbook

| ID | Requirement |
|----|-------------|
| FR-3.1 | Produce a `.xlsx` file following the four-sheet layout in `LBG_Board_Governance_2025.xlsx`: **Board Overview**, **Biographical Details**, **Committee Memberships**, **Meeting Attendance**. |
| FR-3.2 | Apply consistent professional formatting: Arial font, navy header row, colour-coded rows (Executive, Chair, NED), attendance percentage traffic-light colouring. |
| FR-3.3 | Include a source/metadata footer on every sheet. |
| FR-3.4 | Name the file `{CompanyName}_{FiscalYear}_Board_Governance.xlsx`. |

### FR-4 — Output: JSON File

| ID | Requirement |
|----|-------------|
| FR-4.1 | Produce a `.json` file that validates against the project's JSON Schema (`schemas/board_governance.schema.json`). |
| FR-4.2 | The top-level object must contain a `company` metadata block and a `directors` array. |
| FR-4.3 | Every field defined in FR-2 must appear in the schema (nullable where appropriate). |
| FR-4.4 | Name the file `{CompanyName}_{FiscalYear}_Board_Governance.json`. |
| FR-4.5 | The schema file itself must be versioned with a `$schema` declaration and a `version` field. |

### FR-5 — LLM Provider Support

| ID | Requirement |
|----|-------------|
| FR-5.1 | Support **Anthropic** models (e.g. `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5`) via the `anthropic` SDK. |
| FR-5.2 | Support **OpenAI-compatible** models (OpenAI, DeepSeek) via the `openai` SDK. |
| FR-5.3 | Support **Azure OpenAI** via the `openai` SDK with a configurable `base_url`, `api_version`, and `deployment_name`. This is the primary path for corporate environments. |
| FR-5.4 | Provider and model are selectable via CLI flags and/or environment variables. |
| FR-5.5 | All LLM calls use **structured output / JSON mode** where the provider supports it; otherwise a validated JSON extraction step is applied. |
| FR-5.6 | Implement retry logic with exponential back-off for transient API errors (rate limits, timeouts). |
| FR-5.7 | Log token usage per extraction run. |

### FR-6 — Evaluation Harness

The harness compares a machine-extracted JSON against a manually-annotated ground-truth JSON for the same company/filing. Evaluation operates at three levels — field, director, and document — and supports cross-corpus aggregation for benchmarking.

#### FR-6.1 Field-Level Metrics

Each field is scored and declared **pass** or **fail** independently, using the metric appropriate to its type. A null prediction when the ground truth is non-null is always a fail (false negative). A non-null prediction when the ground truth is null is always a fail (hallucination). These two failure modes are tracked separately so they can be distinguished in the report.

| Field Type | Metric | Pass condition |
|-----------|--------|----------------|
| Simple text (name, role, nationality) | **Exact Match** (normalised) and **Fuzzy Match** | Fuzzy ratio ≥ threshold (default 90) |
| Dates | **Exact Match** on ISO-8601 string; **Year-only EM** as fallback | Exact match, or year-only match if configured |
| Numeric values (age, tenure, meetings) | **Absolute Error** and **Relative Error** | Relative error ≤ tolerance (default 5%) |
| Enums (designation, independence status) | **Exact Match** | Strings identical after normalisation |
| Lists of short strings (expertise, committees, directorships) | **Set-based Precision, Recall, F1** (order-insensitive) | F1 ≥ threshold (default 0.90) |
| Long free text (career summary, biography) | **Semantic Similarity** (`all-MiniLM-L6-v2`) | Cosine similarity ≥ threshold (default 0.80) |
| Nested objects (committee attendance records) | Decomposed into sub-field metrics above | All sub-fields pass |

#### FR-6.2 Pass/Fail Classification at Field Level

Every field evaluation produces a `FieldResult`:

```python
@dataclass
class FieldResult:
    field_path: str          # e.g. "biographical.full_name"
    metric_used: str         # e.g. "fuzzy_match"
    predicted_value: Any
    ground_truth_value: Any
    score: float             # continuous score in [0.0, 1.0]
    passed: bool             # True if score meets threshold
    failure_mode: str | None # "false_negative" | "hallucination" | "below_threshold" | None
```

The `failure_mode` field is critical: it distinguishes a missing extraction (the LLM returned `null` when data was present) from a hallucination (the LLM invented a value when the source had none) from a below-threshold match (a value was extracted but was not accurate enough).

#### FR-6.3 Director Matching

Before any field comparison, extracted directors must be matched to ground-truth directors by name. Use fuzzy name matching (threshold 90) on `biographical.full_name`. Directors present in extraction but absent in ground truth are **false positive directors** (all fields scored 0, failure mode "hallucination"). Directors present in ground truth but absent in extraction are **false negative directors** (all fields scored 0, failure mode "false_negative"). Both categories contribute to document-level scores.

#### FR-6.4 Aggregate Metrics — Three Levels

**Level 1 — Director-level**

| Metric | Definition |
|--------|------------|
| `director_field_pass_rate` | Fraction of fields passing for this director (e.g. 18/20 = 0.90) |
| `director_perfect_match` | `True` only if every field passes (strict) |
| `director_false_negative_count` | Number of fields that were null in extraction but non-null in ground truth |
| `director_hallucination_count` | Number of fields that were non-null in extraction but null in ground truth |

The `director_perfect_match` flag is strict and will often be `False` for directors with rich biographies — use `director_field_pass_rate` as the primary per-director quality signal.

**Level 2 — Document-level**

| Metric | Definition |
|--------|------------|
| `document_field_pass_rate` | Fraction of all (director × field) pairs that pass across the document |
| `document_perfect_match` | `True` only if every director achieves `director_perfect_match` |
| `director_perfect_match_rate` | Fraction of directors in the document achieving perfect match |
| `per_field_pass_rate` | Dict mapping each field path to its pass rate across all directors in the document |
| `per_field_type_pass_rate` | Aggregated pass rate by field category (biographical, board_role, attendance) |
| `false_negative_rate` | Fraction of expected field values that were missed (null in extraction) |
| `hallucination_rate` | Fraction of extracted field values that had no ground-truth counterpart |

The `per_field_pass_rate` breakdown is the primary tool for prompt engineering: it shows exactly which fields are systematically hard to extract (e.g. `career_summary` at 73% → improve the biography prompt section).

**Level 3 — Corpus-level (across multiple documents)**

| Metric | Definition |
|--------|------------|
| `corpus_field_pass_rate` | Mean `document_field_pass_rate` across all evaluated documents |
| `corpus_document_perfect_match_rate` | Fraction of documents achieving `document_perfect_match` |
| `corpus_per_field_pass_rate` | Per-field pass rates pooled across all documents |

Corpus-level metrics are produced when `gov-extract evaluate-corpus` is run against a directory of (extracted, ground-truth) pairs. These are the headline numbers for comparing LLM providers or prompt versions.

#### FR-6.5 Regression Gate

The `evaluate` command must exit with a non-zero status code if any configured threshold is breached, making it suitable for use in CI. The gate thresholds are configurable in `config.yaml`:

```yaml
evaluation:
  regression_gate:
    document_field_pass_rate: 0.90      # fail if overall pass rate drops below 90%
    director_perfect_match_rate: 0.50   # fail if fewer than 50% of directors are perfect
    hallucination_rate: 0.05            # fail if more than 5% of fields are hallucinated
```

#### FR-6.6 Evaluation Report

Three output artefacts are produced per evaluation run:

- **`evaluation_report.json`** — machine-readable, nested structure: document-level summary → per-director summary → per-field `FieldResult`. Suitable for programmatic comparison across runs.
- **`evaluation_report.xlsx`** — human-readable tabular view with one row per (director, field), columns: field path, metric, predicted value, ground-truth value, continuous score, pass/fail, failure mode. Conditional formatting highlights failures in red and hallucinations in amber.
- **Stdout summary table** (via `rich`) — three panels: document-level headline metrics, per-field-type pass rates, and a list of the five worst-performing fields by pass rate.

#### FR-6.7 CLI Extensions for Evaluation

```
gov-extract evaluate        --extracted <extracted.json>
                            --ground-truth <ground_truth.json>
                            --output-dir <path>
                            [--thresholds <thresholds_yaml>]
                            [--fail-on-regression]   # exit 1 if gate thresholds breached

gov-extract evaluate-corpus --extracted-dir <dir/>   # all *_extracted.json files
                            --ground-truth-dir <dir/> # matching *_ground_truth.json files
                            --output-dir <path>
                            [--thresholds <thresholds_yaml>]
```

### FR-7 — CLI Interface

```
gov-extract extract  --input <pdf_path_or_url>
                     --company <name>
                     --year <fiscal_year>
                     --provider <anthropic|openai|azure_openai>
                     --model <model_id>
                     --output-dir <path>
                     [--page-hint <governance_start_page>]
                     [--config <config_yaml>]

gov-extract evaluate --extracted <extracted.json>
                     --ground-truth <ground_truth.json>
                     --output-dir <path>
                     [--thresholds <thresholds_yaml>]

gov-extract validate         --json <file.json>         # validates against JSON schema only

gov-extract evaluate-corpus --extracted-dir <dir/>      # cross-document corpus evaluation
                            --ground-truth-dir <dir/>
                            --output-dir <path>
                            [--thresholds <thresholds_yaml>]
```

### FR-8 — Configuration

- A `config.yaml` file controls: default provider, model, output directory, page-detection keywords, chunking strategy, evaluation thresholds.
- All secrets (API keys, Azure endpoint) are loaded from environment variables or a `.env` file; never hardcoded.

---

## 4. Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-1 | **Accuracy:** `document_field_pass_rate` ≥ 0.90 on the LBG reference document; F1 for committee membership and attendance fields ≥ 0.95; `hallucination_rate` ≤ 0.05. |
| NFR-2 | **Latency:** End-to-end extraction of a 300-page annual report completes within 5 minutes on a standard developer laptop (network-dependent). |
| NFR-3 | **Reproducibility:** Given the same PDF, provider, and model, the JSON output must be semantically equivalent across runs (deterministic prompting; temperature=0). |
| NFR-4 | **Extensibility:** Adding a new LLM provider requires only a new class implementing the `LLMProvider` protocol; no changes to extraction logic. |
| NFR-5 | **Observability:** Structured logging (JSON lines) to a log file per run; includes page ranges processed, token counts, and per-field extraction confidence where available. |
| NFR-6 | **Testability:** ≥ 80% unit-test coverage on extraction logic, schema validation, and evaluation metrics. |
| NFR-7 | **Packaging:** Distributed as a `uv`-managed Python project; `uv run gov-extract` works out of the box after `uv sync`. |

---

## 5. Data Model — Python (Pydantic v2)

The canonical Python data model mirrors the JSON schema and is used for LLM structured output, validation, and serialisation.

```
BoardGovernanceDocument
├── company: CompanyMetadata
└── directors: list[Director]
    ├── biographical: BiographicalDetails
    ├── board_role: BoardRoleDetails
    └── attendance: AttendanceDetails
        └── committee_attendance: list[CommitteeAttendance]
```

All models derive from `pydantic.BaseModel` with `model_config = ConfigDict(extra="forbid")`.

---

## 6. JSON Schema

Located at `schemas/board_governance.schema.json`. Draft 2020-12. All fields nullable by default; required fields are `full_name`, `designation`, and the company metadata block.

---

## 7. Constraints & Assumptions

- Python ≥ 3.11.
- `uv` is the sole package/environment manager; no `pip install` outside `uv`.
- The application does not OCR scanned PDFs (out of scope for v1); PDFs must have a text layer.
- Ground-truth JSON files for evaluation are created manually by the user; the tool does not generate them.
- The tool does not submit data to any external service other than the chosen LLM API.
- Azure OpenAI deployments may lag behind the latest model versions; the tool must gracefully degrade structured output to prompt-based JSON extraction if the deployment does not support JSON mode.

---

## 8. Out of Scope (v1)

- OCR of scanned/image PDFs.
- Web scraping (SEC EDGAR, Companies House) — PDF path only.
- Financial interests / remuneration extraction (planned for v2).
- Multi-document merging (e.g. combining annual report + proxy statement).
- GUI or web interface.
- Database persistence.
