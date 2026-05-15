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
├── REQUIREMENTS.md
├── PROJECT_PLAN.md
├── .env.example
├── config.yaml
├── schemas/
│   └── board_governance.schema.json   # JSON Schema Draft 2020-12
├── src/gov_extract/
│   ├── cli.py                         # Typer app; commands: extract, evaluate, validate, evaluate-corpus
│   ├── config.py                      # Pydantic Settings v2
│   ├── models/
│   │   ├── document.py                # BoardGovernanceDocument (top-level model)
│   │   ├── director.py                # Director + BiographicalDetails + BoardRoleDetails + AttendanceDetails
│   │   ├── board_summary.py           # BoardSummary (aggregate board-level statistics)
│   │   └── metadata.py                # CompanyMetadata
│   ├── pdf/
│   │   ├── loader.py                  # load_pdf(path_or_url) -> Path
│   │   ├── extractor.py               # extract_pages(pdf_path) -> dict[int, str]
│   │   └── page_finder.py             # find_governance_pages(pages, keywords) -> list[PageRange]
│   ├── llm/
│   │   ├── base.py                    # LLMProvider Protocol
│   │   ├── anthropic_provider.py
│   │   ├── openai_provider.py         # Also covers DeepSeek; handles reasoning_effort
│   │   ├── azure_provider.py          # Subclasses OpenAIProvider
│   │   └── factory.py                 # get_provider(config) -> LLMProvider
│   ├── extraction/
│   │   ├── prompts.py                 # All prompt templates (director + board summary + markdown rounds)
│   │   ├── chunker.py                 # chunk_pages(pages, max_tokens) -> list[TextChunk]
│   │   ├── extractor.py               # run_extraction(provider, chunks, ...) -> BoardGovernanceDocument
│   │   └── validator.py               # validate_json(data) -> BoardGovernanceDocument
│   ├── export/
│   │   ├── excel_writer.py            # write_excel(doc, path) — five sheets
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
class CurrentBoard(BaseModel):
    summary: BoardSummary = Field(default_factory=BoardSummary)
    directors: list[Director] = []

class BoardGovernanceDocument(BaseModel):
    company: CompanyMetadata
    current_board: CurrentBoard = Field(default_factory=CurrentBoard)
    director_election: DirectorElection | None = None
```

`BoardGovernanceDocument` has two parallel sections, each with the same shape (summary + list):
- `current_board` — `CurrentBoard(summary, directors)`
- `director_election` — `DirectorElection(summary, candidates)`

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

### BoardSummary (`board_summary.py`)

Aggregate governance statistics for the full board. Fields are populated from two sources (priority order): (1) explicitly stated values extracted from the filing, (2) values computed from the Director list.

```python
class BoardSummary(BaseModel):
    ceo_chair_separated: bool | None = None
    voting_standard: Literal["Majority", "Plurality"] | None = None
    board_evaluation: bool | None = None   # True if process + outcomes + actions all mentioned
    board_size: int | None = None
    num_executive_directors: int | None = None
    num_non_executive_directors: int | None = None
    num_independent_directors: int | None = None
    pct_women: float | None = None        # 0–100; computed from directors.biographical.gender
    pct_independent: float | None = None  # 0–100
    avg_director_age: float | None = None
    avg_tenure_years: float | None = None
    notes: str | None = None
```

`voting_standard` and `board_evaluation` can only come from the filing text; there is no computation fallback for either. `pct_women` is computed from `director.biographical.gender` (case-insensitive `"Female"` match), using the full director count as the denominator; only computed when at least one director has a known gender. All remaining fields have computation fallbacks in `_compute_board_summary()` in `extractor.py`.

**Important:** Directors are accessed via `doc.current_board.directors`; `full_name` via `director.biographical.full_name`. When merging partial extraction results across chunks, match directors by `biographical.full_name` using fuzzy matching (threshold 90).

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

    def extract_text(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str: ...  # unconstrained free text; used by two-round markdown extraction
```

### Adding a New Provider

1. Create `src/gov_extract/llm/my_provider.py` implementing the `LLMProvider` protocol (all three methods).
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

**Anthropic:** Use tool use (function calling) to enforce structured output. Define a tool with the Pydantic model's JSON schema as input schema. Temperature must be 0. `extract_text()` uses a plain `messages.create` call with no tool use.

**OpenAI / DeepSeek:**
- For models supporting `response_format`: use `client.beta.chat.completions.parse(response_format=BoardGovernanceDocument)`.
- For older deployments: use `response_format={"type": "json_object"}` and parse manually.
- DeepSeek: set `base_url` from `OPENAI_BASE_URL` env var; API key from `OPENAI_API_KEY`.
- `extract_text()` uses `chat.completions.create` with no `response_format`.

**Reasoning models (OpenAI o1/o3/o4/gpt-5 series):**
- These models use `reasoning_effort` (`"low"`, `"medium"`, `"high"`) instead of `temperature`.
- Auto-detection: `_model_uses_reasoning_effort(model)` checks if the model name starts with `o1`, `o3`, `o4`, or `gpt-5`.
- When detected, `reasoning_effort="medium"` is used by default; override via `config.yaml`.
- When `reasoning_effort` is set (either auto-detected or explicit), it is passed to **all three** call methods (`extract`, `extract_raw_json`, `extract_text`); `temperature` is not sent.
- The resolved parameters are cached as `self.reasoning_or_temperature: dict` at init time.

**Azure OpenAI:**
- Subclass `OpenAIProvider`. Override `__init__` to use `openai.AzureOpenAI(azure_endpoint=..., api_version=..., api_key=...)`.
- The deployment name (not the model name) is passed as `model=` to the API.
- Applies the same `reasoning_effort` auto-detection as `OpenAIProvider`, using the deployment name.
- Required env vars: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_DEPLOYMENT`.

---

## Extraction Pipeline

```
PDF path/URL
    → pdf/loader.py          → local PDF path (cached)
    → pdf/extractor.py       → dict[page_num, text]
    → pdf/page_finder.py     → list[PageRange]  (governance pages only)
    → extraction/chunker.py  → list[TextChunk]  (chunks ≤ max_tokens)
    → extraction/extractor.run_extraction()
         [dispatch by chunking + extraction_rounds]

         extraction_rounds=1, chunking=True (default):
             for each chunk → llm.extract(system_prompt, user_prompt, DirectorList)
             → partial list[Director]
             → _deduplicate_directors() (fuzzy merge on full_name)

         extraction_rounds=1, chunking=False:
             concatenate all chunks → single llm.extract() call

         extraction_rounds=2, chunking=True:
             for each chunk → llm.extract_text(markdown_system_prompt, ...)
             → combine all markdown sections
             → save combined markdown to {output_dir}/{Company}_{Year}_Board_Governance_round1.md
             → single llm.extract(structured_from_markdown_system_prompt, combined_markdown)

         extraction_rounds=2, chunking=False:
             concatenate all chunks → single llm.extract_text() call → markdown
             → save combined markdown
             → single llm.extract(structured_from_markdown_system_prompt, markdown)

         [board summary — always single pass, regardless of chunking]
             full governance text (or combined markdown if rounds=2)
             → llm.extract(board_summary_system_prompt, ..., BoardSummary)
             → _compute_board_summary() fills any None fields from Director list

         → attach CompanyMetadata
    → extraction/validator.py → BoardGovernanceDocument (validated)
    → export/excel_writer.py  → .xlsx  (five sheets)
    → export/json_writer.py   → .json
```

### Prompt Functions (`extraction/prompts.py`)

| Function | Used by | Returns |
|----------|---------|---------|
| `system_prompt()` | Round-1 structured extraction | Director JSON schema + instructions |
| `user_prompt(chunk_text, ...)` | Round-1 structured extraction | Chunk text with company context |
| `markdown_system_prompt()` | Two-round extraction, round 1 | Free-text markdown instructions |
| `markdown_user_prompt(chunk_text, ...)` | Two-round extraction, round 1 | Chunk text with context |
| `structured_from_markdown_system_prompt()` | Two-round extraction, round 2 | Director JSON schema + convert-from-markdown instructions |
| `structured_from_markdown_user_prompt(markdown, ...)` | Two-round extraction, round 2 | Combined markdown with context |
| `board_summary_system_prompt()` | Board summary extraction | BoardSummary JSON schema + instructions |
| `board_summary_user_prompt(text, ..., is_markdown)` | Board summary extraction | Full governance text or markdown with context |

### Key Extraction Functions (`extraction/extractor.py`)

| Function | Purpose |
|----------|---------|
| `run_extraction(...)` | Main entry point; dispatches all four strategy combinations |
| `_extract_chunk(provider, chunk, ...)` | Single structured extraction call for one chunk |
| `_extract_chunk_markdown(provider, chunk, ...)` | Free-text markdown extraction for one chunk (round 1) |
| `_structured_from_markdown(provider, markdown, ...)` | Convert combined markdown to Directors (round 2) |
| `_extract_board_summary(provider, text, ...)` | Single LLM call for BoardSummary; always full-text |
| `_compute_board_summary(summary, directors)` | Fill None fields from Director list |
| `_deduplicate_directors(director_lists)` | Fuzzy-merge Directors across chunks |

### Prompt Guidelines

**System prompts** must contain:
- Role: "You are a governance data analyst extracting structured information from corporate filings."
- Instruction: "Extract only what is explicitly stated. Return `null` for any field not present in the text. Do not infer, guess, or hallucinate values."
- Schema: Embed the relevant JSON schema as a code block.

**Null over hallucination** is a correctness requirement, not a style preference. The prompt must explicitly instruct the LLM to return `null` for missing fields.

---

## Excel Output Format

Five sheets in this order:

| Sheet | Purpose |
|-------|---------|
| `Board Summary` | Two-column metric/value table of all `BoardSummary` fields |
| `Board Overview` | Master table: all directors, all key fields |
| `Biographical Details` | Name, age band, nationality, expertise, career, qualifications, external directorships |
| `Committee Memberships` | Director × committee matrix — `C` (chair), `M` (member), `–` (not a member) |
| `Meeting Attendance` | Board + per-committee attendance; attendance % with traffic-light colours |

**Formatting constants** (match reference file exactly):
```python
HDR_BG    = "1B3A6B"   # header row fill
HDR_FG    = "FFFFFF"   # header row text
EXEC_BG   = "FFF3CD"   # executive director row tint
CHAIR_BG  = "E8EAF6"   # board chair row tint
ALT_BG    = "F2F7FC"   # alternating NED row tint
ATT_GREEN = "C8E6C9"   # attendance 100%
ATT_YELLOW= "FFF9C4"   # attendance 80–99%
ATT_RED   = "FFCDD2"   # attendance <80%
FONT_NAME = "Arial"
```

---

## Evaluation Harness

Evaluation operates at three levels: **field → director → document**, with optional **corpus-level** aggregation across multiple documents. Every evaluation run produces `evaluation_report.json`, `evaluation_report.xlsx`, and a rich stdout summary.

### FieldResult dataclass (`evaluation/metrics.py`)

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

**failure_mode rules:**
- `"false_negative"` — predicted is `None`/`[]`, ground truth is non-null/non-empty. Score = 0.
- `"hallucination"` — predicted is non-null/non-empty, ground truth is `None`/`[]`. Score = 0.
- `"below_threshold"` — both present, score < threshold. Score = computed value.
- `None` — pass.

### Metric function signatures (`evaluation/metrics.py`)

```python
def exact_match(pred: str | None, gt: str | None) -> float: ...
def fuzzy_match(pred: str | None, gt: str | None, threshold: float = 90.0) -> float: ...
def date_match(pred: str | None, gt: str | None) -> dict[str, float]: ...
def numeric_error(pred: float | None, gt: float | None, tolerance: float = 0.05) -> dict[str, float]: ...
def list_f1(pred: list, gt: list) -> dict[str, float]: ...
def semantic_similarity(pred: str | None, gt: str | None, threshold: float = 0.80) -> float: ...
```

The sentence-transformer model is loaded lazily and cached as a module-level singleton. Import only inside the function body, guarded by a `try/except` that raises a clear `RuntimeError` explaining how to install the `eval` extra.

### Metric dispatch by field path

Configured in `config.yaml` under `evaluation.field_metrics`. See `config.yaml` for the full mapping. Key entries:

```yaml
evaluation:
  field_metrics:
    "biographical.full_name":            exact_match
    "biographical.career_summary":       llm_semantic_similarity
    "board_role.committee_memberships":  list_f1
    "attendance.board_attendance_pct":   numeric_error
```

### Aggregate dataclasses (`evaluation/evaluator.py`)

```python
@dataclass
class DirectorResult:
    director_name: str
    field_results: list[FieldResult]
    field_pass_rate: float
    perfect_match: bool
    false_negative_count: int
    hallucination_count: int
    matched: bool

@dataclass
class DocumentResult:
    company_name: str
    extracted_path: str
    ground_truth_path: str
    director_results: list[DirectorResult]
    document_field_pass_rate: float
    document_perfect_match: bool
    director_perfect_match_rate: float
    per_field_pass_rate: dict[str, float]
    per_field_type_pass_rate: dict[str, float]
    false_negative_rate: float
    hallucination_rate: float

@dataclass
class CorpusResult:
    document_results: list[DocumentResult]
    corpus_field_pass_rate: float
    corpus_document_perfect_match_rate: float
    corpus_per_field_pass_rate: dict[str, float]
    corpus_hallucination_rate: float
    corpus_false_negative_rate: float
```

### Director matching

Match extracted directors to ground-truth directors using `rapidfuzz.fuzz.token_sort_ratio` on `biographical.full_name` (threshold 90). Greedy best-match assignment (not one-to-many). Log unmatched directors at WARNING level.

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
  judge_provider: openai
  judge_model: gpt-4o-mini
  temperature: 0
  reasoning_effort: null       # null = auto-detect; "low" | "medium" | "high" to override
  chunking: true               # true = chunk pages; false = single pass over all pages
  extraction_rounds: 1         # 1 = direct structured; 2 = markdown then structured
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

- `test_models.py` — valid/invalid Pydantic model construction; JSON schema round-trip; includes BoardSummary.
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
4. **Temperature must be 0** for all LLM calls to ensure reproducibility. For reasoning models that use `reasoning_effort`, the `temperature` parameter must not be sent at all.
5. **Null over hallucination.** The prompt must explicitly instruct the LLM to return `null` for missing fields; this is a correctness requirement, not a style preference.
6. **The `sentence-transformers` dependency is optional** (`[eval]` extra). The core `extract` command must work without it; `evaluate` must fail gracefully with an informative error if the extra is not installed.
7. **All file output paths are configurable.** Never write to a hardcoded path — always resolve from `config.output.default_dir` or the `--output-dir` CLI flag.
8. **Log token usage.** Every LLM call must log `{"event": "llm_call", "provider": ..., "model": ..., "input_tokens": ..., "output_tokens": ...}` via `structlog`.
9. **Board summary extraction is always single-pass.** Do not chunk the board summary LLM call regardless of the `chunking` setting. It sees the full governance text (rounds=1) or combined markdown (rounds=2).

---

## Reference Files

| File | Purpose |
|------|---------|
| `examples/LBG_Board_Governance_2025.xlsx` | Canonical output format — Excel sheet layout, formatting, and field values |
| `tests/fixtures/lbg_ground_truth.json` | Canonical output format — JSON structure and field values |
| `schemas/board_governance.schema.json` | Authoritative JSON Schema — generated from Pydantic models; re-generate with `uv run python -m gov_extract.models.generate_schema` |
| `REQUIREMENTS.md` | Full product requirements |
| `PROJECT_PLAN.md` | Phased implementation plan and design decisions |
