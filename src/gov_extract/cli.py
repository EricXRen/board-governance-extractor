"""Typer CLI entrypoint: extract, evaluate, validate, evaluate-corpus."""

from __future__ import annotations

import shutil
from pathlib import Path

import structlog
import typer
from dotenv import load_dotenv
from rich.console import Console

from gov_extract.config import get_config

load_dotenv()

app = typer.Typer(
    name="gov-extract",
    help="Extract structured board governance data from PDF filings using LLMs.",
    add_completion=False,
)
console = Console()
logger = structlog.get_logger()


def _resolve_inputs(inputs: list[str]) -> list[str]:
    """Expand input paths: a directory → all PDFs inside; other paths/URLs passed through."""
    resolved: list[str] = []
    for inp in inputs:
        p = Path(inp)
        if p.is_dir():
            pdfs = sorted(p.glob("*.pdf"))
            if not pdfs:
                console.print(f"[yellow]Warning: no PDF files found in {p}[/yellow]")
            resolved.extend(str(pdf) for pdf in pdfs)
        else:
            resolved.append(inp)
    return resolved


def _setup_logging(config_path: Path | None = None) -> None:

    import structlog

    cfg = get_config(config_path)

    if cfg.logging.format == "json":
        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.stdlib.add_log_level,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            logger_factory=structlog.stdlib.LoggerFactory(),
        )
    else:
        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="%H:%M:%S"),
                structlog.stdlib.add_log_level,
                structlog.dev.ConsoleRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            logger_factory=structlog.stdlib.LoggerFactory(),
        )


@app.command()
def extract(
    inputs: list[str] = typer.Argument(
        ...,
        metavar="INPUT...",
        help=(
            "One or more PDF paths, HTTPS URLs, or a single folder. "
            "All inputs must be for the same company and are merged into one output."
        ),
    ),
    company: str = typer.Option(..., "--company", "-c", help="Company name"),
    year: str = typer.Option(..., "--year", "-y", help="Fiscal year, e.g. 2025"),
    provider: str | None = typer.Option(None, "--provider", "-p", help="LLM provider"),
    model: str | None = typer.Option(None, "--model", "-m", help="LLM model ID"),
    output_dir: str | None = typer.Option(None, "--output-dir", "-o", help="Output directory"),
    page_hint: int | None = typer.Option(
        None, "--page-hint", help="Approximate governance start page"
    ),
    config_file: str | None = typer.Option(None, "--config", help="Path to config.yaml"),
    filing_type: str = typer.Option("Annual Report", "--filing-type", help="Filing type"),
    fiscal_year_end: str | None = typer.Option(
        None, "--fiscal-year-end", help="ISO-8601 fiscal year end date"
    ),
    ticker: str | None = typer.Option(None, "--ticker", help="Company ticker symbol"),
    report_date: str | None = typer.Option(None, "--report-date", help="Report date (ISO-8601)"),
    eval_id: str | None = typer.Option(
        None,
        "--eval-id",
        help=(
            "Evaluation dataset ID, e.g. 'lbg-fy2025'. "
            "Creates data/dataset/eval_data/<eval-id>/ and copies source PDFs there."
        ),
    ),
) -> None:
    """Extract board governance data from one or more PDF filings into a single output.

    Examples:\n
        gov-extract extract report.pdf --company "LBG" --year 2025\n
        gov-extract extract report1.pdf report2.pdf --company "LBG" --year 2025\n
        gov-extract extract /reports/folder/ --company "LBG" --year 2025 --eval-id lbg-fy2025
    """
    _setup_logging(Path(config_file) if config_file else None)
    cfg = get_config(Path(config_file) if config_file else None)

    resolved_inputs = _resolve_inputs(inputs)
    if not resolved_inputs:
        console.print("[bold red]Error: no PDF files found in the provided input(s).[/bold red]")
        raise typer.Exit(1)

    resolved_provider = provider or cfg.llm.default_provider
    resolved_model = model or cfg.llm.default_model
    resolved_output_dir = Path(output_dir) if output_dir else Path(cfg.output.default_dir)
    resolved_fye = fiscal_year_end or f"{year}-12-31"

    console.print(
        f"[bold cyan]gov-extract[/bold cyan] extracting [green]{company}[/green] ({year})"
    )
    console.print(f"  Provider: {resolved_provider} / {resolved_model}")
    if len(resolved_inputs) == 1:
        console.print(f"  Input:    {resolved_inputs[0]}")
    else:
        console.print(f"  Inputs:   {len(resolved_inputs)} PDF files")

    from gov_extract.export.excel_writer import output_path as excel_path
    from gov_extract.export.excel_writer import write_excel
    from gov_extract.export.json_writer import output_path as json_path
    from gov_extract.export.json_writer import write_json
    from gov_extract.extraction.chunker import chunk_pages
    from gov_extract.extraction.extractor import run_extraction
    from gov_extract.llm.factory import get_provider as _get_provider
    from gov_extract.pdf.extractor import extract_pages_bulk
    from gov_extract.pdf.loader import load_pdf
    from gov_extract.pdf.page_finder import find_governance_pages

    all_chunks = []
    resolved_pdf_paths: list[str] = []

    for idx, input_path in enumerate(resolved_inputs, 1):
        label = f"[{idx}/{len(resolved_inputs)}] " if len(resolved_inputs) > 1 else ""

        with console.status(f"{label}Loading PDF..."):
            pdf_path = load_pdf(input_path, cfg.pdf.cache_dir)
        resolved_pdf_paths.append(str(pdf_path))

        with console.status(f"{label}Extracting page text..."):
            pages = extract_pages_bulk(pdf_path)
        console.print(f"  {label}Pages extracted: {len(pages)}  ({pdf_path.name})")

        with console.status(f"{label}Finding governance pages..."):
            if page_hint:
                from gov_extract.pdf.page_finder import PageRange

                ranges = [PageRange(max(1, page_hint - 2), min(len(pages), page_hint + 80))]
            else:
                ranges = find_governance_pages(pages, cfg.pdf.governance_keywords)

        gov_pages: dict[int, str] = {}
        for r in ranges:
            for p in r.pages():
                if p in pages:
                    gov_pages[p] = pages[p]

        console.print(
            f"  {label}Governance pages: {len(gov_pages)} pages across {len(ranges)} range(s)"
        )

        with console.status(f"{label}Chunking pages..."):
            chunks = chunk_pages(gov_pages, max_tokens=cfg.pdf.max_pages_per_chunk * 600)
        all_chunks.extend(chunks)

    source_pdf_path = " | ".join(resolved_pdf_paths)
    chunking_label = len(all_chunks) if cfg.llm.chunking else 1
    console.print(f"  Extraction: chunks={chunking_label}  rounds={cfg.llm.extraction_rounds}")

    safe_company = company.replace(" ", "")
    markdown_out = (
        resolved_output_dir / f"{safe_company}_{year}_Board_Governance_round1.md"
        if cfg.llm.extraction_rounds == 2
        else None
    )

    with console.status(f"Running extraction with {resolved_provider}..."):
        llm_provider = _get_provider(cfg, resolved_provider, resolved_model)
        doc = run_extraction(
            provider=llm_provider,
            chunks=all_chunks,
            company_name=company,
            filing_type=filing_type,
            fiscal_year_end=resolved_fye,
            source_pdf_path=source_pdf_path,
            provider_name=resolved_provider,
            model_name=resolved_model,
            company_ticker=ticker,
            report_date=report_date,
            chunking=cfg.llm.chunking,
            extraction_rounds=cfg.llm.extraction_rounds,
            max_chunk_workers=cfg.llm.max_chunk_workers,
            markdown_output_path=markdown_out,
        )

    console.print(f"  Directors extracted: [bold green]{len(doc.directors)}[/bold green]")

    with console.status("Writing outputs..."):
        xlsx_out = excel_path(company, year, resolved_output_dir)
        json_out = json_path(company, year, resolved_output_dir)
        write_excel(doc, xlsx_out)
        write_json(doc, json_out)

    console.print("\n[bold green]Done![/bold green]")
    console.print(f"  Excel:    {xlsx_out}")
    console.print(f"  JSON:     {json_out}")
    if markdown_out is not None:
        console.print(f"  Markdown: {markdown_out}")

    if eval_id:
        eval_dir = Path(cfg.output.eval_dataset_dir) / eval_id
        eval_dir.mkdir(parents=True, exist_ok=True)
        for pdf_str in resolved_pdf_paths:
            src = Path(pdf_str)
            dst = eval_dir / src.name
            if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
                shutil.copy2(src, dst)
        console.print(f"  Eval dir: {eval_dir}  ({len(resolved_pdf_paths)} PDF(s) copied)")


@app.command()
def validate(
    json_file: str = typer.Option(..., "--json", "-j", help="Path to JSON file to validate"),
    config_file: str | None = typer.Option(None, "--config", help="Path to config.yaml"),
) -> None:
    """Validate a JSON output file against the board governance schema."""
    _setup_logging(Path(config_file) if config_file else None)

    from gov_extract.extraction.validator import validate_json_file

    path = Path(json_file)
    if not path.exists():
        console.print(f"[bold red]Error:[/bold red] File not found: {path}")
        raise typer.Exit(1)

    try:
        doc = validate_json_file(path)
        n = len(doc.directors)
        name = doc.company.company_name
        console.print(f"[bold green]Valid![/bold green] {n} directors, company: {name}")
    except Exception as e:
        console.print(f"[bold red]Validation failed:[/bold red] {e}")
        raise typer.Exit(1) from e


@app.command()
def evaluate(
    extracted: str = typer.Option(..., "--extracted", "-e", help="Path to extracted JSON"),
    ground_truth: str = typer.Option(..., "--ground-truth", "-g", help="Path to ground-truth JSON"),
    output_dir: str | None = typer.Option(None, "--output-dir", "-o", help="Output directory"),
    thresholds: str | None = typer.Option(None, "--thresholds", help="Path to thresholds YAML"),
    fail_on_regression: bool = typer.Option(
        False, "--fail-on-regression", help="Exit 1 if gate thresholds breached"
    ),
    config_file: str | None = typer.Option(None, "--config", help="Path to config.yaml"),
) -> None:
    """Evaluate extracted JSON against ground-truth JSON."""
    _setup_logging(Path(config_file) if config_file else None)
    cfg = get_config(Path(config_file) if config_file else None)

    from gov_extract.evaluation.evaluator import check_regression_gate
    from gov_extract.evaluation.evaluator import evaluate as _evaluate
    from gov_extract.evaluation.report import write_evaluation_report
    from gov_extract.extraction.validator import validate_json_file

    resolved_output_dir = Path(output_dir) if output_dir else Path(cfg.output.default_dir)

    with console.status("Loading documents..."):
        ext_doc = validate_json_file(Path(extracted))
        gt_doc = validate_json_file(Path(ground_truth))

    field_metrics = cfg.evaluation.field_metrics
    eval_thresholds = {
        "fuzzy_match": cfg.evaluation.thresholds.fuzzy_match,
        "list_f1": cfg.evaluation.thresholds.list_f1,
        "semantic_similarity": cfg.evaluation.thresholds.semantic_similarity,
        "numeric_error_tolerance": cfg.evaluation.thresholds.numeric_error_tolerance,
    }

    judge_config = {"provider": cfg.llm.judge_provider, "model": cfg.llm.judge_model}

    with console.status("Evaluating..."):
        result = _evaluate(ext_doc, gt_doc, field_metrics, eval_thresholds, extracted, ground_truth, judge_config)

    write_evaluation_report(result, resolved_output_dir)

    gate_config = {
        "document_field_pass_rate": cfg.evaluation.regression_gate.document_field_pass_rate,
        "director_perfect_match_rate": cfg.evaluation.regression_gate.director_perfect_match_rate,
        "hallucination_rate": cfg.evaluation.regression_gate.hallucination_rate,
    }
    breaches = check_regression_gate(result, gate_config, fail_on_regression)
    if breaches:
        console.print("[bold yellow]Regression gate breaches:[/bold yellow]")
        for b in breaches:
            console.print(f"  [red]✗[/red] {b}")
        if fail_on_regression:
            raise typer.Exit(1)
    else:
        console.print("[bold green]All regression gates passed.[/bold green]")


@app.command(name="evaluate-corpus")
def evaluate_corpus(
    extracted_dir: str = typer.Option(
        ..., "--extracted-dir", help="Dir with *_extracted.json files"
    ),
    ground_truth_dir: str = typer.Option(
        ..., "--ground-truth-dir", help="Dir with *_ground_truth.json files"
    ),
    output_dir: str | None = typer.Option(None, "--output-dir", "-o", help="Output directory"),
    thresholds: str | None = typer.Option(None, "--thresholds", help="Path to thresholds YAML"),
    config_file: str | None = typer.Option(None, "--config", help="Path to config.yaml"),
) -> None:
    """Evaluate multiple extracted/ground-truth document pairs (corpus-level)."""
    _setup_logging(Path(config_file) if config_file else None)
    cfg = get_config(Path(config_file) if config_file else None)

    from gov_extract.evaluation.evaluator import evaluate_corpus as _eval_corpus
    from gov_extract.evaluation.report import write_evaluation_report
    from gov_extract.extraction.validator import validate_json_file

    resolved_output_dir = Path(output_dir) if output_dir else Path(cfg.output.default_dir)

    ext_files = sorted(Path(extracted_dir).glob("*_extracted.json"))
    if not ext_files:
        console.print("[bold red]No *_extracted.json files found.[/bold red]")
        raise typer.Exit(1)

    field_metrics = cfg.evaluation.field_metrics
    eval_thresholds = {
        "fuzzy_match": cfg.evaluation.thresholds.fuzzy_match,
        "list_f1": cfg.evaluation.thresholds.list_f1,
        "semantic_similarity": cfg.evaluation.thresholds.semantic_similarity,
        "numeric_error_tolerance": cfg.evaluation.thresholds.numeric_error_tolerance,
    }

    pairs = []
    for ext_file in ext_files:
        stem = ext_file.stem.replace("_extracted", "")
        gt_file = Path(ground_truth_dir) / f"{stem}_ground_truth.json"
        if not gt_file.exists():
            console.print(
                f"[yellow]Warning: no ground truth for {ext_file.name}, skipping[/yellow]"
            )
            continue
        ext_doc = validate_json_file(ext_file)
        gt_doc = validate_json_file(gt_file)
        pairs.append((ext_doc, gt_doc, str(ext_file), str(gt_file)))

    judge_config = {"provider": cfg.llm.judge_provider, "model": cfg.llm.judge_model}

    with console.status(f"Evaluating {len(pairs)} document pairs..."):
        corpus_result = _eval_corpus(pairs, field_metrics, eval_thresholds, judge_config)

    write_evaluation_report(corpus_result, resolved_output_dir)
    rate = corpus_result.corpus_field_pass_rate
    perfect = corpus_result.corpus_document_perfect_match_rate
    console.print(f"\nCorpus field pass rate: [bold green]{rate:.1%}[/bold green]")
    console.print(f"Perfect documents: {perfect:.1%}")


if __name__ == "__main__":
    app()
