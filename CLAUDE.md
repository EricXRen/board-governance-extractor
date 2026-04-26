# CLAUDE.md — Board Governance Extractor

This file is the authoritative codebase guide for Claude Code. Read it fully before touching any file.

---

## Project Identity

**Package name:** `board-governance-extractor`
**CLI entrypoint:** `gov-extract` (via `uv run gov-extract`)
**Python:** 3.11+
**Package manager:** `uv` — never use `pip` directly
**Source layout:** `src/gov_extract/` (PEP 517 src layout)

---

## Quick Commands

```bash
# Install all dependencies (including eval and dev extras)
uv sync --extra eval --extra dev

# Run the CLI
uv run gov-extract --help
uv run gov-extract extract --input examples/2025-lbg-annual-report.pdf --company "Lloyds Banking Group" --year 2025 --provider anthropic --model claude-sonnet-4-6 --output-dir ./outputs

# Validate a JSON output against the schema
uv run gov-extract validate --json outputs/LloydsBankingGroup_2025_Board_Governance.json

# Run evaluation against ground truth
uv run gov-extract evaluate --extracted outputs/LloydsBankingGroup_2025_Board_Governance.json --ground-truth tests/fixtures/lbg_ground_truth.json --output-dir ./outputs

# Run tests
uv run pytest tests/unit/ -v --cov=src/gov_extract --cov-report=term-missing

# Lint + format
uv run ruff check . && uv run ruff format .

# Type-check
uv run mypy src/
```

---

## Repository Layout

```
board-governance-extractor/
├── pyproject.toml
├── uv.lock
├── CLAUDE.md                          ← YOU ARE HERE
├── README.md
├── .env.example
├── config.yaml
├── schemas/
│   └── board_governance.schema.json   # JSON Schema Draft 2020-12
├── src/gov_extract/
│   ├── cli.py                         # Typer app; three commands: extract, evaluate, validate
│   ├── config.py                      # Pydantic Settings v2
│   ├── models/
│   │   ├── document.py                # BoardGovernanceDocument (top-level model)
│   │   ├── director.py                # Director + BiographicalDetails + BoardRoleDetails + AttendanceDetails
│   │   └── metadata.py                # CompanyMetadata
│   ├── pdf/
│   │   ├── loader.py                  # load_pdf(path_or_url) -> Path
│   │   ├── extractor.py               # extract_pages(pdf_path) -> dict[int, str]
│   │   └── page_finder.py             # find_governance_pages(pages, keywords) -> list[PageRange]
│   ├── llm/
│   │   ├── base.py                    # LLMProvider Protocol
│   │   ├── anthropic_provider.py
│   │   ├── openai_provider.py         # Also covers DeepSeek
│   │   ├── azure_provider.py          # Subclasses OpenAIProvider
│   │   └── factory.py                 # get_provider(config) -> LLMProvider
│   ├── extraction/
│   │   ├── prompts.py                 # system_prompt(), user_prompt(chunk_text)
│   │   ├── chunker.py                 # chunk_pages(pages, max_tokens) -> list[str]
│   │   ├── extractor.py               # run_extraction(provider, chunks) -> BoardGovernanceDocument
│   │   └── validator.py               # validate_json(data) -> BoardGovernanceDocument
│   ├── export/
│   │   ├── excel_writer.py            # write_excel(doc, path)
│   │   └── json_writer.py             # write_json(doc, path)
│   └── evaluation/
│       ├── metrics.py                 # exact_match, fuzzy_match, date_match, numeric_error, list_f1, semantic_similarity
│       ├── evaluator.py               # evaluate(extracted, ground_truth, thresholds) -> EvaluationResult
│       └── report.py                  # write_evaluation_report(result, output_dir)
├── tests/
│   ├── conftest.py
│   ├── unit/
│   └── fixtures/
│       ├── lbg_ground_truth.json
│       └── lbg_sample_pages.txt
└── examples/
    ├── LBG_Board_Governance_2025.xlsx
    └── run_lbg.sh
```

---

## Data Models

All models live in `src/gov_extract/models/`. They are **Pydantic v2** (`BaseModel` with `model_config = ConfigDict(extra="forbid")`). They are the single source of truth — the JSON schema is generated from them.

### Top-level

```python
# document.py
class BoardGovernanceDocument(BaseModel):
    company: CompanyMetadata
    directors: list[Director]
```

### CompanyMetadata (`metadata.py`)

```python
class CompanyMetadata(BaseModel):
    company_name: str
    company_ticker: str | None = None
    filing_type: str                        # "Annual Report" | "Proxy Statement" | ...
    fiscal_year_end: str                    # ISO-8601 date
    report_date: str | None = None          # ISO-8601 date
    source_pdf_path: str
    extraction_timestamp: str               # ISO-8601 UTC datetime
    llm_provider: str
    llm_model: str
```

### Director (`director.py`)

```python
class CommitteeAttendance(BaseModel):
    committee_name: str
    meetings_attended: int
    meetings_scheduled: int
    attendance_pct: float                   # computed: attended / scheduled
    is_chair: bool = False

class BiographicalDetails(BaseModel):
    full_name: str
    post_nominals: str | None = None
    age: int | None = None
    age_band: str | None = None             # e.g. "56–60"
    nationality: str | None = None
    qualifications: list[str] = []
    expertise_areas: list[str] = []
    career_summary: str | None = None
    other_directorships: list[str] = []

class BoardRoleDetails(BaseModel):
    designation: Literal["Executive Director", "Non-Executive Director", "Chair"]
    board_role: str                         # e.g. "Group Chief Executive"
    independence_status: Literal[
        "Independent",
        "Not Independent",
        "Chair (independent on appointment)",
        "N/A (Executive)"
    ]
    year_joined_board: int | None = None
    date_joined_board: str | None = None    # ISO-8601
    tenure_years: float | None = None
    year_end_status: str                    # "Active" | "Retired YYYY-MM-DD"
    committee_memberships: list[str] = []
    committee_chair_of: list[str] = []
    special_roles: list[str] = []

class AttendanceDetails(BaseModel):
    board_meetings_attended: int | None = None
    board_meetings_scheduled: int | None = None
    board_attendance_pct: float | None = None
    committee_attendance: list[CommitteeAttendance] = []
    attendance_notes: str | None = None

class Director(BaseModel):
    biographical: BiographicalDetails
    board_role: BoardRoleDetails
    attendance: AttendanceDetails
```

**Important:** `full_name` is accessed via `director.biographical.full_name`. When merging partial extraction results across chunks, match directors by `biographical.full_name` using fuzzy matching (threshold 90).

---

## LLM Provider Layer

### Protocol (`llm/base.py`)

```python
class LLMProvider(Protocol):
    def extract(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> BaseModel: ...

    def extract_raw_json(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str: ...  # fallback; returns raw JSON string
```

### Adding a New Provider

1. Create `src/gov_extract/llm/my_provider.py` implementing the `LLMProvider` protocol.
2. Register it in `llm/factory.py`:
   ```python
   "myprovider": MyProvider
   ```
3. Add its config block to `config.yaml` and document its env vars in `.env.example`.
4. Write a unit test in `tests/unit/test_my_provider.py` with a mocked HTTP call.
5. **No changes needed anywhere else.**

### Retry Logic

All providers must wrap their API calls with `tenacity.retry`:

```python
@retry(
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(5),
    retry=retry_if_exception_type((RateLimitError, APITimeoutError)),
    reraise=True,
)
def extract(self, ...): ...
```

### Provider-Specific Notes

**Anthropic:** Use tool use (function calling) to enforce structured output. Define a tool with the Pydantic model's JSON schema as input schema. Temperature must be 0.

**OpenAI / DeepSeek:**
- For models supporting `response_format`: use `client.beta.chat.completions.parse(response_format=BoardGovernanceDocument)`.
- For older deployments: use `response_format={"type": "json_object"}` and parse manually.
- DeepSeek: set `base_url` from `OPENAI_BASE_URL` env var; API key from `OPENAI_API_KEY`.

**Azure OpenAI:**
- Subclass `OpenAIProvider`. Override `__init__` to use `openai.AzureOpenAI(azure_endpoint=..., api_version=..., api_key=...)`.
- The deployment name (not the model name) is passed as `model=` to the API.
- Structured output availability depends on the deployment version; test with `validate` before `extract`.
- Required env vars: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_DEPLOYMENT`.

---

## Extraction Pipeline

```
PDF path/URL
    → pdf/loader.py         → local PDF path (cached)
    → pdf/extractor.py      → dict[page_num, text]
    → pdf/page_finder.py    → list[PageRange]  (governance pages only)
    → extraction/chunker.py → list[str]  (text chunks ≤ max_tokens)
    → extraction/extractor.py
         for each chunk:
             → llm/<provider>.extract(system_prompt, user_prompt, Director list model)
             → partial list[Director]
         → merge all partial Director lists (fuzzy dedup on full_name)
         → attach CompanyMetadata
    → extraction/validator.py → BoardGovernanceDocument (validated)
    → export/excel_writer.py  → .xlsx
    → export/json_writer.py   → .json
```

### Prompt Guidelines

**System prompt** must contain:
- Role: "You are a governance data analyst extracting structured information from corporate filings."
- Instruction: "Extract only what is explicitly stated. Return `null` for any field not present in the text. Do not infer, guess, or hallucinate values."
- Format: "Return a JSON array of Director objects matching the provided schema exactly."
- Schema: Embed the JSON schema of `list[Director]` as a code block.

**User prompt** structure:
```
The following text is extracted from pages {start}–{end} of the {filing_type} for {company_name} (fiscal year ending {fiscal_year_end}).

Extract all board directors mentioned. For each director extract all available fields.

--- BEGIN TEXT ---
{chunk_text}
--- END TEXT ---
```

---

## Excel Output Format

The `excel_writer.py` must produce exactly four sheets matching `examples/LBG_Board_Governance_2025.xlsx`:

| Sheet | Purpose |
|-------|---------|
| `Board Overview` | Master table: all directors, all key fields |
| `Biographical Details` | Name, age band, nationality, expertise, career, qualifications, external directorships |
| `Committee Memberships` | Director × committee matrix — `C` (chair), `M` (member), `–` (not a member) |
| `Meeting Attendance` | Board + per-committee attendance; attendance % with traffic-light colours |

**Formatting constants** (match reference file exactly):
```python
HDR_BG   = "1B3A6B"   # header row fill
HDR_FG   = "FFFFFF"   # header row text
EXEC_BG  = "FFF3CD"   # executive director row tint
CHAIR_BG = "E8EAF6"   # board chair row tint
ALT_BG   = "F2F7FC"   # alternating NED row tint
ATT_GREEN = "C8E6C9"  # attendance 100%
ATT_YELLOW= "FFF9C4"  # attendance 80–99%
ATT_RED   = "FFCDD2"  # attendance <80%
FONT_NAME = "Arial"
```

---

## Evaluation Harness

Evaluation operates at three levels: **field → director → document**, with optional **corpus-level** aggregation across multiple documents. Every evaluation run produces `evaluation_report.json`, `evaluation_report.xlsx`, and a rich stdout summary.

### FieldResult dataclass (`evaluation/metrics.py`)

Every field comparison produces a `FieldResult`. Implement this as a `dataclass` — not a dict — so type-checking catches mistakes:

```python
@dataclass
class FieldResult:
    field_path: str          # dot-notation, e.g. "biographical.full_name"
    metric_used: str         # e.g. "fuzzy_match"
    predicted_value: Any
    ground_truth_value: Any
    score: float             # continuous score in [0.0, 1.0]
    passed: bool             # True if score meets configured threshold
    failure_mode: str | None # "false_negative" | "hallucination" | "below_threshold" | None
```

**failure_mode rules (apply before computing score):**
- `"false_negative"` — predicted is `None`/`[]`, ground truth is non-null/non-empty. Score = 0.
- `"hallucination"` — predicted is non-null/non-empty, ground truth is `None`/`[]`. Score = 0.
- `"below_threshold"` — both are present, metric computed, but score < threshold. Score = computed value.
- `None` — pass.

Never silently skip null predictions. A `false_negative` and a `hallucination` both score 0 but must be counted separately in the report — they indicate different failure modes in the extraction pipeline.

### Metric function signatures (`evaluation/metrics.py`)

```python
# All functions return a score in [0.0, 1.0] unless noted.
# Callers should check for None/empty before calling — the functions
# themselves do not raise on None; they return 0.0 with appropriate failure_mode.

def exact_match(pred: str | None, gt: str | None) -> float:
    """Normalise (strip, lowercase) both strings. Return 1.0 if identical, else 0.0."""

def fuzzy_match(pred: str | None, gt: str | None, threshold: float = 90.0) -> float:
    """rapidfuzz.fuzz.token_sort_ratio. Return ratio/100 if ≥ threshold, else 0.0."""

def date_match(pred: str | None, gt: str | None) -> dict[str, float]:
    """Return {"exact": 0|1, "year_only": 0|1}. Parse ISO-8601 strings."""

def numeric_error(
    pred: float | None, gt: float | None, tolerance: float = 0.05
) -> dict[str, float]:
    """Return {"absolute_error": float, "relative_error": float, "pass": 0|1}.
    relative_error = |pred - gt| / |gt| if gt != 0 else |pred|.
    pass = 1 if relative_error <= tolerance."""

def list_f1(pred: list, gt: list) -> dict[str, float]:
    """Set-based (order-insensitive). Normalise each element (strip, lowercase).
    Return {"precision": float, "recall": float, "f1": float}."""

def semantic_similarity(
    pred: str | None, gt: str | None, threshold: float = 0.80
) -> float:
    """Cosine similarity via sentence-transformers all-MiniLM-L6-v2.
    Return similarity score in [0.0, 1.0]. Raise ImportError with clear message
    if sentence-transformers is not installed (eval extra missing)."""
```

**Sentence transformer model** is loaded lazily and cached as a module-level singleton (`_MODEL: SentenceTransformer | None = None`). Import only inside the function body, guarded by a try/except that raises a clear `RuntimeError` explaining how to install the `eval` extra.

### Metric dispatch by field path

Configured in `config.yaml` under `evaluation.field_metrics`:

```yaml
evaluation:
  field_metrics:
    "biographical.full_name":           exact_match
    "biographical.post_nominals":       fuzzy_match
    "biographical.age":                 numeric_error
    "biographical.age_band":            fuzzy_match
    "biographical.nationality":         fuzzy_match
    "biographical.qualifications":      list_f1
    "biographical.expertise_areas":     list_f1
    "biographical.career_summary":      semantic_similarity
    "biographical.other_directorships": list_f1
    "board_role.designation":           exact_match
    "board_role.board_role":            fuzzy_match
    "board_role.independence_status":   exact_match
    "board_role.year_joined_board":     numeric_error
    "board_role.tenure_years":          numeric_error
    "board_role.committee_memberships": list_f1
    "board_role.committee_chair_of":    list_f1
    "attendance.board_meetings_attended":  numeric_error
    "attendance.board_meetings_scheduled": numeric_error
    "attendance.board_attendance_pct":     numeric_error
  thresholds:
    fuzzy_match: 90.0
    list_f1: 0.90
    semantic_similarity: 0.80
    numeric_error_tolerance: 0.05      # 5% relative error
  regression_gate:
    document_field_pass_rate: 0.90     # exit 1 if below this
    director_perfect_match_rate: 0.50  # exit 1 if below this
    hallucination_rate: 0.05           # exit 1 if above this
```

### Aggregate metrics — three levels (`evaluation/evaluator.py`)

The evaluator builds results bottom-up: field → director → document.

**Director-level** (computed from all `FieldResult` objects for one director):

```python
@dataclass
class DirectorResult:
    director_name: str
    field_results: list[FieldResult]
    field_pass_rate: float       # passed_count / total_field_count
    perfect_match: bool          # True only if ALL fields passed
    false_negative_count: int    # fields where extraction missed a value
    hallucination_count: int     # fields where extraction invented a value
    matched: bool                # False if this director had no GT counterpart (FP)
                                 # or no extraction counterpart (FN)
```

`perfect_match` is strict. Use `field_pass_rate` as the primary per-director quality signal in reports and in prompts-improvement workflows — a director at 0.90 needs targeted improvement, not a complete re-extraction.

**Document-level** (computed from all `DirectorResult` objects):

```python
@dataclass
class DocumentResult:
    company_name: str
    extracted_path: str
    ground_truth_path: str
    director_results: list[DirectorResult]

    # Headline metrics
    document_field_pass_rate: float       # all (director × field) pairs
    document_perfect_match: bool          # every director has perfect_match=True
    director_perfect_match_rate: float    # fraction of directors with perfect_match

    # Breakdown by field path and category
    per_field_pass_rate: dict[str, float]       # {"biographical.full_name": 1.0, ...}
    per_field_type_pass_rate: dict[str, float]  # {"biographical": 0.87, "board_role": 0.92, ...}

    # Error type rates
    false_negative_rate: float    # missed values / total expected values
    hallucination_rate: float     # invented values / total extracted values
```

`per_field_pass_rate` is the key diagnostic for prompt engineering: low pass rate on `career_summary` → improve biography extraction prompt; low pass rate on `committee_memberships` → improve committee section chunking.

**Corpus-level** (across multiple documents, `evaluate-corpus` command):

```python
@dataclass
class CorpusResult:
    document_results: list[DocumentResult]
    corpus_field_pass_rate: float              # mean document_field_pass_rate
    corpus_document_perfect_match_rate: float  # fraction with document_perfect_match
    corpus_per_field_pass_rate: dict[str, float]  # pooled across all documents
    corpus_hallucination_rate: float
    corpus_false_negative_rate: float
```

### Regression gate (`evaluation/evaluator.py`)

After computing `DocumentResult`, check each gate threshold from config. If `--fail-on-regression` is passed (or configured as default in CI), call `sys.exit(1)` with a structured error message listing which thresholds were breached. This makes the `evaluate` command a first-class CI step.

### Report outputs (`evaluation/report.py`)

| Output | Format | Content |
|--------|--------|---------|
| `evaluation_report.json` | JSON | Full nested `DocumentResult` (or `CorpusResult`). Machine-readable; diff between runs to track regressions. |
| `evaluation_report.xlsx` | Excel | One row per (director × field). Columns: field_path, metric_used, predicted, ground_truth, score, passed, failure_mode. Red fill for `below_threshold`, amber fill for `hallucination`, yellow fill for `false_negative`. |
| Stdout | `rich` table | Three panels: (1) headline document metrics, (2) per-field-type pass rates sorted ascending (worst first), (3) five worst-performing individual fields. |

### Director matching (`evaluation/evaluator.py`)

Match extracted directors to ground-truth directors using `rapidfuzz.fuzz.token_sort_ratio` on `biographical.full_name` (threshold 90). Use a greedy best-match assignment (not one-to-many). Unmatched extracted directors → all fields scored as `hallucination`. Unmatched ground-truth directors → all fields scored as `false_negative`. Log both cases at WARNING level.

---

## Configuration (`config.yaml` + `config.py`)

`config.py` uses `pydantic-settings` v2 (`BaseSettings`). Settings are loaded from:
1. `config.yaml` (base defaults)
2. Environment variables (override, prefixed `GOV_EXTRACT_` for non-secret settings)
3. `.env` file (loaded via `python-dotenv`)

Secret keys (API keys, endpoints) are **never** in `config.yaml` — env vars only.

```yaml
# config.yaml (committed to repo — no secrets)
llm:
  default_provider: anthropic
  default_model: claude-sonnet-4-6
  temperature: 0
  max_retries: 5
  timeout_seconds: 120

pdf:
  cache_dir: "~/.gov_extract/cache"
  max_pages_per_chunk: 15
  governance_keywords:
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
  format: json        # "json" | "console"
  file: "gov_extract.log"
```

---

## Testing

### Unit tests (`tests/unit/`)

- `test_models.py` — valid/invalid Pydantic model construction; JSON schema round-trip.
- `test_page_finder.py` — keyword detection against `lbg_sample_pages.txt`; assert pp.65–99 selected.
- `test_metrics.py` — parametrised tests for every metric function with known inputs/outputs.
- `test_validator.py` — JSON schema validation of `lbg_ground_truth.json`; invalid fixture fails.

### Integration tests (`tests/integration/`)

Skipped automatically if the required env var is absent:
```python
pytest.importorskip("anthropic")
pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set"
)
```

The integration test for full extraction must run `evaluate` against `lbg_ground_truth.json` and assert:
- `document_field_pass_rate >= 0.90`
- `hallucination_rate <= 0.05`
- F1 for `board_role.committee_memberships` and attendance fields `>= 0.95`

These thresholds are the regression gate for the LBG reference document.

### Fixtures

- `tests/fixtures/lbg_ground_truth.json` — manually authored from `LBG_Board_Governance_2025.xlsx`. Contains all 11 directors with all fields populated. This is the canonical regression fixture.
- `tests/fixtures/lbg_sample_pages.txt` — plain text of LBG annual report pp.65–99 (governance section). Used for page_finder and prompt unit tests.

### Unit tests for evaluation metrics (`tests/unit/test_metrics.py`)

Parametrise with known inputs covering all edge cases:
- Both values present → expected score
- Predicted `None`, GT non-null → `failure_mode == "false_negative"`, `score == 0.0`
- Predicted non-null, GT `None` → `failure_mode == "hallucination"`, `score == 0.0`
- Both `None` → `passed == True`, `score == 1.0` (nothing to extract, nothing hallucinated)
- List metrics: empty pred vs non-empty GT; extra items in pred vs GT; exact match

---

## Code Style

- Formatter: `ruff format` (Black-compatible, 100-char line length).
- Linter: `ruff check` — enabled rule sets: `E`, `F`, `I`, `N`, `UP`, `B`, `SIM`.
- Type annotations: required on all public functions and class attributes. Run `mypy src/` with `strict = true`.
- Docstrings: Google style; required on all public classes and functions.
- No `print()` in library code — use `structlog.get_logger()`.

---

## Important Constraints

1. **Never use `pip install` directly.** All package management goes through `uv add` / `uv sync`.
2. **Never hardcode API keys, endpoints, or credentials** anywhere in source files. Read exclusively from env vars / `.env`.
3. **`extra="forbid"` on all Pydantic models.** This prevents silent field-name typos from being accepted.
4. **Temperature must be 0** for all LLM calls to ensure reproducibility.
5. **Null over hallucination.** The prompt must explicitly instruct the LLM to return `null` for missing fields; this is a correctness requirement, not a style preference.
6. **The `sentence-transformers` dependency is optional** (`[eval]` extra). The core `extract` command must work without it; `evaluate` must fail gracefully with an informative error if the extra is not installed.
7. **All file output paths are configurable.** Never write to a hardcoded path — always resolve from `config.output.default_dir` or the `--output-dir` CLI flag.
8. **Log token usage.** Every LLM call must log `{"event": "llm_call", "provider": ..., "model": ..., "input_tokens": ..., "output_tokens": ...}` via `structlog`.

---

## Reference Files

| File | Purpose |
|------|---------|
| `examples/LBG_Board_Governance_2025.xlsx` | Canonical output format — Excel sheet layout, formatting, and field values |
| `tests/fixtures/lbg_ground_truth.json` | Canonical output format — JSON structure and field values |
| `schemas/board_governance.schema.json` | Authoritative JSON Schema — generated from Pydantic models; re-generate with `uv run python -m gov_extract.models.generate_schema` |
| `REQUIREMENTS.md` | Full product requirements |
| `PROJECT_PLAN.md` | Phased implementation plan and design decisions |
