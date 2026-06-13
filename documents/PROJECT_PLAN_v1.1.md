# Board Governance Extractor v1.1 — Project Plan

## Overview

| Attribute | Value |
|-----------|-------|
| Release | v1.1 |
| PRD | `documents/PRD_v1.1.md` |
| Features | LangExtract backend + Source references |
| Implementation order | Phase 1 (source refs, pydantic path) → Phase 2 (LangExtract backend + source refs) |

---

## Spike Findings

Key facts from the LangExtract API spike that shape this plan:

- **Install:** `uv add "langextract[openai]"` (optional `[langextract]` extra in our project)
- **OpenAI routing:** Automatic for `gpt-*` model IDs. DeepSeek requires explicit `ModelConfig(provider="openai", provider_kwargs={"base_url": ...})`
- **Core call:** `lx.extract(text, prompt_description, examples, model_id) → AnnotatedDocument`
- **Output is flat:** `Extraction(extraction_class, extraction_text, attributes: dict[str, str|list[str]], char_interval)` — no nested objects
- **char_interval:** `CharInterval(start_pos, end_pos)` — byte offsets into original text; `None` means hallucination (value not found in source)
- **Multi-pass:** Each pass is an independent full extraction; results deduplicated by non-overlapping `char_interval`
- **Mapping layer is manual:** LangExtract does not map to nested Pydantic models — we must group/map `Extraction` objects to `Director` ourselves

**Key design decision:** Design the few-shot examples so that **each director produces exactly one `Extraction`** (with all fields as attributes), avoiding the grouping problem entirely. This makes the mapping layer straightforward: one `Extraction` → one `Director`.

---

## Phase 1 — Source References (Pydantic-schema path)

**Goal:** Every extracted director carries an optional source reference (page + quoted text) using the existing LLM pipeline. No new dependencies.

**Recommended first** — independent of LangExtract, low risk, immediately useful.

### 1.1 — Add `SourceReference` model

**File:** `src/gov_extract/models/director.py`

Add before the `Director` class:

```python
class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_number: int | None = None
    char_start: int | None = None     # populated by LangExtract path only
    char_end: int | None = None       # populated by LangExtract path only
    quoted_text: str | None = None    # verbatim excerpt ≤ 200 chars
```

Add to `Director`:

```python
class Director(BaseModel):
    biographical: BiographicalDetails
    board_role: BoardRoleDetails
    attendance: AttendanceDetails
    source_ref: SourceReference | None = None   # additive, backward-compatible
```

### 1.2 — Update extraction prompt

**File:** `src/gov_extract/extraction/prompts.py`

Extend the existing director extraction system prompt to instruct the LLM:

> "For each director, populate `source_ref` with the `page_number` (if determinable from the text) and a `quoted_text` field containing a verbatim excerpt of ≤ 200 characters from the source text that most clearly identifies this director's name and role. If you cannot determine the page number, set it to `null`."

The `source_ref` field is already in the JSON schema (after step 1.1 + schema regen), so structured-output providers will populate it automatically.

### 1.3 — Regenerate JSON schema

```bash
uv run python -m gov_extract.models.generate_schema
```

This is the only schema change in Phase 1 — additive, backward-compatible.

### 1.4 — Add `Source References` Excel sheet

**File:** `src/gov_extract/export/excel_writer.py`

Add a 6th sheet after the existing five. Written only if at least one director has a non-null `source_ref`.

Columns: `Director` | `Page` | `Char Start` | `Char End` | `Quoted Text`

Formatting: same navy header as other sheets; no traffic-light colouring; `Quoted Text` column width 60.

### 1.5 — Unit tests

- `tests/unit/test_models.py` — `SourceReference` valid/invalid construction; `Director` with and without `source_ref`
- `tests/unit/test_validator.py` — `lbg_ground_truth.json` still passes after schema regen (no source_ref required)

### 1.6 — Update `CLAUDE.md`

Add `SourceReference` to the Data Models section. Update Excel sheet count from 5 to 6.

---

## Phase 2 — LangExtract Backend

**Goal:** Add `langextract` as an optional alternative extraction backend. When enabled, extractions are grounded via `char_interval` and `source_ref` is populated automatically.

### 2.1 — Add optional dependency

**File:** `pyproject.toml`

```toml
[project.optional-dependencies]
langextract = [
    "langextract[openai]>=0.1",
]
```

Install with:

```bash
uv sync --extra langextract
```

### 2.2 — Add config option

**File:** `src/gov_extract/config.py` — add to `LLMConfig`:

```python
extraction_backend: str = "pydantic_schema"   # "pydantic_schema" | "langextract"
```

**File:** `config.yaml`:

```yaml
llm:
  extraction_backend: pydantic_schema   # pydantic_schema | langextract
```

### 2.3 — Commit few-shot examples

**File:** `src/gov_extract/extraction/langextract_examples.py`

Define `DIRECTOR_EXAMPLES: list[ExampleData]` — 2–3 annotated director examples based on the LBG ground truth. Design principle: **one `Extraction` per director**, with all fields as attributes.

Example structure:

```python
import langextract as lx

DIRECTOR_EXAMPLES = [
    lx.data.ExampleData(
        text=(
            "Robin Budenberg CBE  Chair  Appointed January 2020\n"
            "Robin joined the Board as Chair in January 2020 ...\n"
            "Board attendance: 12/12 (100%)\n"
            "Committee: Nominations (Chair)\n"
        ),
        extractions=[
            lx.data.Extraction(
                extraction_class="director",
                extraction_text="Robin Budenberg CBE",
                attributes={
                    "full_name": "Robin Budenberg CBE",
                    "designation": "Chair",
                    "board_role": "Chair",
                    "independence_status": "Chair (independent on appointment)",
                    "year_joined_board": "2020",
                    "board_meetings_attended": "12",
                    "board_meetings_scheduled": "12",
                    "board_attendance_pct": "100.0",
                    "committee_memberships": ["Nominations"],
                    "committee_chair_of": ["Nominations"],
                    "career_summary": "Robin joined the Board as Chair in January 2020 ...",
                },
            )
        ],
    ),
    # 2 more examples ...
]

PROMPT_DESCRIPTION = (
    "Extract each director as a single extraction with extraction_class='director'. "
    "Use the director's full name (including post-nominals) as extraction_text. "
    "Populate all available attributes. Use null for missing fields. "
    "Do not invent or infer values not explicitly stated in the text."
)
```

### 2.4 — LangExtract extractor module

**File:** `src/gov_extract/extraction/langextract_extractor.py`

Key functions:

```python
def _get_langextract_model(cfg: LLMConfig) -> ModelConfig | str:
    """Return model_id string (OpenAI) or ModelConfig (DeepSeek/custom)."""
    ...

def _extraction_to_director(extraction: Extraction) -> Director | None:
    """Map a single flat Extraction with attributes → Director Pydantic model.
    Returns None if extraction_class != 'director' or full_name missing."""
    ...

def run_langextract_extraction(
    pages: dict[int, str],
    cfg: LLMConfig,
    company_name: str,
) -> list[Director]:
    """Run LangExtract over all governance pages; return mapped Directors."""
    ...
```

**`_extraction_to_director` mapping logic:**
- `extraction_text` → `biographical.full_name`
- `attributes["designation"]` → `board_role.designation` (validated against Literal)
- `attributes["committee_memberships"]` (list) → `board_role.committee_memberships`
- Numeric fields: `int(attributes["year_joined_board"])` with try/except
- `char_interval` → `source_ref.char_start`, `source_ref.char_end`, `source_ref.quoted_text`
- `page_number` derived from which page's text the char offset falls in

**Provider dispatch:**

```python
if cfg.default_provider in ("openai",) and "gpt-" in cfg.default_model:
    model = cfg.default_model          # auto-routed by LangExtract
else:
    model = ModelConfig(
        model_id=cfg.default_model,
        provider="openai",
        provider_kwargs={"base_url": os.environ.get("OPENAI_BASE_URL"), "api_key": ...},
    )
```

**Graceful fallback if not installed:**

```python
try:
    import langextract as lx
except ImportError as exc:
    raise RuntimeError(
        "langextract is required for extraction_backend='langextract'. "
        "Install it with: uv sync --extra langextract"
    ) from exc
```

### 2.5 — Wire into extraction dispatch

**File:** `src/gov_extract/extraction/extractor.py`

Add to `run_extraction()`:

```python
if cfg.llm.extraction_backend == "langextract":
    from gov_extract.extraction.langextract_extractor import run_langextract_extraction
    directors = run_langextract_extraction(gov_pages, cfg.llm, company_name)
    # board summary still uses existing single-pass pydantic-schema call
else:
    # existing pydantic_schema path unchanged
    ...
```

Board summary extraction is **always pydantic-schema** regardless of backend (as per PRD).

### 2.6 — Unit tests

- `tests/unit/test_langextract_extractor.py` — mock `lx.extract`; test `_extraction_to_director` with valid/partial/null attributes; test char_interval → source_ref mapping; test graceful ImportError

### 2.7 — Update `CLAUDE.md` and `README.md`

- Document `extraction_backend` config option
- Add `[langextract]` extra to installation section
- Add DeepSeek `ModelConfig` usage note

---

## File Change Summary

| File | Change |
|------|--------|
| `src/gov_extract/models/director.py` | Add `SourceReference`; add `source_ref` to `Director` |
| `src/gov_extract/extraction/prompts.py` | Prompt extension for `source_ref` (pydantic path) |
| `src/gov_extract/export/excel_writer.py` | Add `Source References` 6th sheet |
| `src/gov_extract/extraction/langextract_examples.py` | New — committed few-shot examples |
| `src/gov_extract/extraction/langextract_extractor.py` | New — LangExtract backend |
| `src/gov_extract/extraction/extractor.py` | Dispatch on `extraction_backend` |
| `src/gov_extract/config.py` | Add `extraction_backend` to `LLMConfig` |
| `config.yaml` | Add `extraction_backend: pydantic_schema` |
| `pyproject.toml` | Add `[langextract]` optional dependency |
| `schemas/board_governance.schema.json` | Regenerate (SourceReference added) |
| `CLAUDE.md` | Data model + config + install docs |
| `README.md` | Installation + config reference |

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| One `Extraction` per director | Eliminates the grouping problem; flat attributes map 1-to-1 to Pydantic fields |
| Board summary always pydantic-schema | LangExtract is not designed for aggregate statistics; keeps complexity contained |
| Source refs on pydantic path via prompted quotes | Director-level granularity = single quote per director = minimal prompt overhead |
| `char_start`/`char_end` only on LangExtract path | Pydantic path has no character offsets; these fields remain `null` |
| LangExtract as additive optional extra | Does not affect users who don't install it; zero risk to existing pipeline |

---

## Verification

```bash
# Phase 1 verification
uv run pytest tests/unit/ -v                              # all tests pass
uv run gov-extract extract report.pdf --company "X" --year 2025
# → outputs/X_2025_Board_Governance.json has source_ref fields
# → outputs/X_2025_Board_Governance.xlsx has Source References sheet

# Phase 2 verification
uv sync --extra langextract
uv run gov-extract extract report.pdf --company "X" --year 2025
# (with extraction_backend: langextract in config.yaml)
# → source_ref.char_start / char_end populated
uv run gov-extract evaluate \
  --extracted outputs/X_2025_Board_Governance.json \
  --ground-truth tests/fixtures/lbg_ground_truth.json
# → document_field_pass_rate >= 0.85
```
