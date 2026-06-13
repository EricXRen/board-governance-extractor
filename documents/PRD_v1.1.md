# Product Requirements Document — v1.1

**Product:** Board Governance Extractor (`gov-extract`)
**Release:** v1.1
**Status:** Approved
**Date:** 2026-06-14

---

## Background

v1.0 ships a working extraction pipeline (PDF → LLM → structured JSON + Excel) with an evaluation harness. Two themes emerged from early user feedback:

1. **Accuracy / recall** — users want to trial alternative extraction approaches to improve quality, particularly for long filings or unusual layouts.
2. **Auditability** — users want to trace each extracted director record back to its source location in the original PDF so they can verify or dispute values without manually searching the document.

These two themes are addressed by the two features in this release.

---

## Feature 1 — LangExtract Integration

### Problem

The current pipeline uses raw LLM calls constrained by a Pydantic JSON schema. This works well but has known weaknesses:

- Long documents chunked across many LLM calls may lose context at chunk boundaries.
- The structured-output constraint can reduce recall.
- There is no automatic grounding — we cannot tell whether a value came from the document or was hallucinated.

[LangExtract](https://github.com/google/langextract) is a Google-developed open-source library that uses few-shot examples (rather than a rigid JSON schema) and runs multiple extraction passes over document segments, combining results while filtering hallucinations via character-level grounding (`char_interval`).

### Goal

Add LangExtract as an **optional alternative extraction backend** selectable via `config.yaml`. The existing Pydantic-schema pipeline remains the default and is unchanged.

### Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Default LLM provider | OpenAI / DeepSeek | Best supported by LangExtract; matches existing user credentials |
| Gemini / Anthropic support | Out of scope for v1.1 | Can be added later; OpenAI covers the primary use case |
| Few-shot examples | Committed to repo | Easier to maintain; ensures consistent behaviour across users |
| Examples location | `src/gov_extract/extraction/langextract_examples.py` | Consistent with module layout |

### Scope

**In scope:**
- New config option `llm.extraction_backend: langextract` (default: `pydantic_schema`)
- New module `src/gov_extract/extraction/langextract_extractor.py`:
  - Accepts page text (post PDF parsing — LangExtract does not process PDFs directly)
  - Defines committed `ExampleData` few-shot examples for `Director` and `BoardSummary`
  - Runs LangExtract extraction and maps `Extraction` objects → `Director` Pydantic models
  - Preserves `char_interval` provenance data for Feature 2
- Provider support: OpenAI and DeepSeek (via OpenAI-compatible API)
- Extend the evaluation harness to compare both backends on the same document

**Out of scope:**
- Replacing the existing `pydantic_schema` backend
- Gemini / Anthropic / Ollama / Vertex AI support in v1.1
- Per-company customisable few-shot examples (v1.2+)

### Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC1 | `llm.extraction_backend: langextract` in `config.yaml` routes extraction through the new module; all other CLI flags unchanged |
| AC2 | LBG integration test with LangExtract backend achieves `document_field_pass_rate >= 0.85` |
| AC3 | `langextract` is an optional dependency (`[langextract]` extra); missing package gives a clear error; does not break the core `extract` command |
| AC4 | Output from LangExtract backend validates against the existing JSON Schema |
| AC5 | Unit tests cover the `Extraction` → `Director` mapping layer |

---

## Feature 2 — Source References for Extracted Director Records

### Problem

Users receiving extracted JSON or Excel files have no way to verify individual values without manually searching the PDF. This is high friction for governance analysts who must confirm values before downstream use.

### Goal

Every extracted director record carries an optional **source reference** indicating where in the original document the director information was found. Source references appear in a dedicated Excel sheet and in the JSON output.

### Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Granularity | Director-level (one ref per director) | Simpler model and UX; field-level can be v1.2+ |
| Excel placement | Separate `Source References` sheet | Keeps main sheets clean; analysts can cross-reference |
| Inline display | Not shown in main sheets for v1.1 | Avoids cluttering Board Overview / Biographical Details |

### Data Model

New optional field added to `Director`:

```python
class SourceReference(BaseModel):
    page_number: int | None = None      # 1-indexed PDF page
    char_start: int | None = None       # char offset in page text (LangExtract path)
    char_end: int | None = None
    quoted_text: str | None = None      # verbatim excerpt ≤ 200 chars

class Director(BaseModel):
    biographical: BiographicalDetails
    board_role: BoardRoleDetails
    attendance: AttendanceDetails
    source_ref: SourceReference | None = None   # NEW — additive, backward-compatible
```

### Two Populating Strategies

Both strategies must work independently so users get source references regardless of which extraction backend they choose.

**LangExtract path:**
- `char_interval` from LangExtract → `char_start` / `char_end` + `quoted_text`
- `page_number` derived from chunk-to-page offset mapping

**Pydantic-schema path:**
- Extend the existing LLM prompt to request one short verbatim quote per director (director-level granularity = minimal prompt overhead)
- Populate `quoted_text` and `page_number` where the model can determine them

### Excel — `Source References` Sheet (new 6th sheet)

Columns: `Director` | `Page` | `Char Start` | `Char End` | `Quoted Text`

One row per director that has a non-null `source_ref`. Sheet is omitted if no source references are populated.

### Scope

**In scope:**
- `SourceReference` Pydantic model in `src/gov_extract/models/director.py`
- `source_ref` field on `Director` (optional, default `None`)
- LangExtract path: populate from `char_interval`
- Pydantic-schema path: prompt extension requesting one verbatim quote + page number per director
- `Source References` Excel sheet in `src/gov_extract/export/excel_writer.py`
- JSON output: `source_ref` included when populated, `null` otherwise (backward-compatible)
- JSON Schema regenerated to include `source_ref`

**Out of scope:**
- Field-level source references (v1.2+)
- PDF hyperlinks / click-to-navigate in Excel (v1.2+)
- Source references for `BoardSummary` aggregate fields (computed, not extracted)
- Confidence scores

### Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC1 | `source_ref` present in JSON output when populated; `null` when not; no schema breakage for existing consumers |
| AC2 | `Source References` Excel sheet present and non-empty when any director has a source ref |
| AC3 | LangExtract path: `char_start`/`char_end` populated for ≥ 90% of extracted directors |
| AC4 | Pydantic-schema path: `quoted_text` verified verbatim in source text for ≥ 80% of directors on LBG |
| AC5 | All v1.0 tests continue to pass |

---

## Release Summary

| Feature | Priority | Complexity | Dependency |
|---------|----------|------------|------------|
| LangExtract backend | High | High | New optional dep (`langextract`) |
| Source refs — LangExtract path | High | Medium | Requires Feature 1 |
| Source refs — Pydantic-schema path | Medium | Low | Independent of Feature 1 |

**Recommended implementation order:** Source references (pydantic-schema path) first — low effort, independent, immediately useful. Then LangExtract backend with its source ref path as the larger piece of work.

---

## Out of Scope for v1.1

- Field-level source references
- PDF hyperlinks or click-to-navigate in Excel
- Confidence scores per extracted field
- Gemini / Anthropic / Vertex AI support for LangExtract
- Per-company few-shot example customisation
- UI or web interface

---

## Success Metrics

| Metric | Target |
|--------|--------|
| LangExtract extraction accuracy (LBG) | `document_field_pass_rate >= 0.85` |
| Source ref coverage — LangExtract path | ≥ 90% of directors populated |
| Source ref accuracy — Pydantic-schema path | ≥ 80% quoted text verified verbatim |
| No regression on existing pipeline | All v1.0 tests pass |
