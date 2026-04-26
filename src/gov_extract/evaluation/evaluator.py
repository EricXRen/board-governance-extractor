"""Director × field evaluation loop and aggregate metric computation."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

import structlog

from gov_extract.evaluation.metrics import FieldResult, evaluate_field
from gov_extract.models.director import Director
from gov_extract.models.document import BoardGovernanceDocument

logger = structlog.get_logger()

_FUZZY_THRESHOLD = 90.0


@dataclass
class DirectorResult:
    """Evaluation results for a single director."""

    director_name: str
    field_results: list[FieldResult]
    field_pass_rate: float
    perfect_match: bool
    false_negative_count: int
    hallucination_count: int
    matched: bool


@dataclass
class DocumentResult:
    """Evaluation results for a full document."""

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
    """Evaluation results across multiple documents."""

    document_results: list[DocumentResult]
    corpus_field_pass_rate: float
    corpus_document_perfect_match_rate: float
    corpus_per_field_pass_rate: dict[str, float]
    corpus_hallucination_rate: float
    corpus_false_negative_rate: float


def _fuzzy_ratio(a: str, b: str) -> float:
    try:
        from rapidfuzz import fuzz

        return float(fuzz.token_sort_ratio(a, b))
    except ImportError:
        a_l, b_l = a.lower().strip(), b.lower().strip()
        if a_l == b_l:
            return 100.0
        common = sum(min(a_l.count(c), b_l.count(c)) for c in set(b_l))
        return 100.0 * 2 * common / (len(a_l) + len(b_l) + 1)


def _match_directors(
    extracted: list[Director], ground_truth: list[Director]
) -> list[tuple[Director | None, Director | None]]:
    """Greedily match extracted directors to ground-truth directors by name.

    Returns:
        List of (extracted, gt) pairs. None on either side means unmatched.
    """
    unmatched_ext = list(extracted)
    unmatched_gt = list(ground_truth)
    pairs: list[tuple[Director | None, Director | None]] = []

    while unmatched_ext and unmatched_gt:
        best_score = 0.0
        best_ei = 0
        best_gi = 0

        for ei, e in enumerate(unmatched_ext):
            for gi, g in enumerate(unmatched_gt):
                score = _fuzzy_ratio(e.biographical.full_name, g.biographical.full_name)
                if score > best_score:
                    best_score = score
                    best_ei = ei
                    best_gi = gi

        if best_score >= _FUZZY_THRESHOLD:
            pairs.append((unmatched_ext.pop(best_ei), unmatched_gt.pop(best_gi)))
        else:
            # No match above threshold — pop the unmatched extracted director
            pairs.append((unmatched_ext.pop(best_ei), None))

    # Remaining unmatched
    for e in unmatched_ext:
        pairs.append((e, None))
    for g in unmatched_gt:
        pairs.append((None, g))

    return pairs


def _get_field_value(obj: Any, path: str) -> Any:
    """Extract a value from a nested object using dot-notation path.

    Args:
        obj: Object or dict to traverse.
        path: Dot-notation path, e.g. "biographical.full_name".

    Returns:
        The value at the path, or None if not found.
    """
    parts = path.split(".")
    current: Any = obj
    for part in parts:
        if current is None:
            return None
        current = current.get(part) if isinstance(current, dict) else getattr(current, part, None)
    return current


def _evaluate_director_pair(
    extracted: Director | None,
    gt: Director | None,
    field_metrics: dict[str, str],
    thresholds: dict[str, float],
) -> DirectorResult:
    """Evaluate all fields for a matched director pair.

    Args:
        extracted: Extracted director (None if false negative).
        gt: Ground-truth director (None if hallucination).
        field_metrics: Mapping of field_path → metric_name.
        thresholds: Metric thresholds.

    Returns:
        DirectorResult with all field evaluations.
    """
    name = (extracted or gt).biographical.full_name  # type: ignore[union-attr]
    matched = extracted is not None and gt is not None

    field_results: list[FieldResult] = []

    if not matched:
        # Unmatched: score all fields as 0
        failure = "false_negative" if extracted is None else "hallucination"
        source = gt if extracted is None else extracted
        if source is None:
            return DirectorResult(
                director_name=name,
                field_results=[],
                field_pass_rate=0.0,
                perfect_match=False,
                false_negative_count=0,
                hallucination_count=0,
                matched=False,
            )
        for fp in field_metrics:
            val = _get_field_value(source, fp)
            pred_val = None if extracted is None else val
            gt_val = None if gt is None else val
            fr = FieldResult(
                field_path=fp,
                metric_used=field_metrics[fp],
                predicted_value=pred_val,
                ground_truth_value=gt_val,
                score=0.0,
                passed=False,
                failure_mode=failure,
            )
            field_results.append(fr)
    else:
        for fp, metric in field_metrics.items():
            pred_val = _get_field_value(extracted, fp)
            gt_val = _get_field_value(gt, fp)
            fr = evaluate_field(fp, pred_val, gt_val, metric, thresholds)
            field_results.append(fr)

    total = len(field_results)
    passed_count = sum(1 for fr in field_results if fr.passed)
    fn_count = sum(1 for fr in field_results if fr.failure_mode == "false_negative")
    hall_count = sum(1 for fr in field_results if fr.failure_mode == "hallucination")

    return DirectorResult(
        director_name=name,
        field_results=field_results,
        field_pass_rate=passed_count / total if total > 0 else 1.0,
        perfect_match=passed_count == total,
        false_negative_count=fn_count,
        hallucination_count=hall_count,
        matched=matched,
    )


def evaluate(
    extracted_doc: BoardGovernanceDocument,
    gt_doc: BoardGovernanceDocument,
    field_metrics: dict[str, str],
    thresholds: dict[str, float],
    extracted_path: str = "",
    gt_path: str = "",
) -> DocumentResult:
    """Run the full evaluation of an extracted document against ground truth.

    Args:
        extracted_doc: LLM-extracted document.
        gt_doc: Manually-annotated ground-truth document.
        field_metrics: Mapping of field_path → metric_name from config.
        thresholds: Metric thresholds from config.
        extracted_path: Path to the extracted JSON (for reporting).
        gt_path: Path to the ground-truth JSON (for reporting).

    Returns:
        DocumentResult with all metrics.
    """
    pairs = _match_directors(extracted_doc.directors, gt_doc.directors)

    director_results: list[DirectorResult] = []
    for ext, gt in pairs:
        dr = _evaluate_director_pair(ext, gt, field_metrics, thresholds)
        director_results.append(dr)

        if ext is None:
            logger.warning("director_false_negative", name=gt.biographical.full_name if gt else "?")  # type: ignore[union-attr]
        elif gt is None:
            logger.warning("director_hallucination", name=ext.biographical.full_name)

    # Aggregate metrics
    all_field_results = [fr for dr in director_results for fr in dr.field_results]
    total_fields = len(all_field_results)
    passed_fields = sum(1 for fr in all_field_results if fr.passed)
    fn_fields = sum(1 for fr in all_field_results if fr.failure_mode == "false_negative")
    hall_fields = sum(1 for fr in all_field_results if fr.failure_mode == "hallucination")

    doc_pass_rate = passed_fields / total_fields if total_fields > 0 else 1.0

    matched_directors = [dr for dr in director_results if dr.matched]
    total_directors = len(matched_directors) + sum(1 for dr in director_results if not dr.matched)
    perfect_directors = sum(1 for dr in matched_directors if dr.perfect_match)
    perfect_match_rate = perfect_directors / total_directors if total_directors > 0 else 1.0
    doc_perfect = all(dr.perfect_match for dr in director_results)

    # Per-field pass rates
    per_field: dict[str, list[bool]] = {}
    for fr in all_field_results:
        per_field.setdefault(fr.field_path, []).append(fr.passed)
    per_field_pass_rate = {fp: sum(v) / len(v) for fp, v in per_field.items()}

    # Per-field-type pass rates
    type_buckets: dict[str, list[bool]] = {}
    for fp, passed_list in per_field.items():
        category = fp.split(".")[0]
        type_buckets.setdefault(category, []).extend(passed_list)
    per_field_type = {cat: sum(v) / len(v) for cat, v in type_buckets.items()}

    # Error rates
    expected_non_null = sum(
        1
        for fr in all_field_results
        if fr.ground_truth_value is not None and fr.ground_truth_value != []
    )
    fn_rate = fn_fields / expected_non_null if expected_non_null > 0 else 0.0

    extracted_non_null = sum(
        1 for fr in all_field_results if fr.predicted_value is not None and fr.predicted_value != []
    )
    hall_rate = hall_fields / extracted_non_null if extracted_non_null > 0 else 0.0

    return DocumentResult(
        company_name=extracted_doc.company.company_name,
        extracted_path=extracted_path,
        ground_truth_path=gt_path,
        director_results=director_results,
        document_field_pass_rate=doc_pass_rate,
        document_perfect_match=doc_perfect,
        director_perfect_match_rate=perfect_match_rate,
        per_field_pass_rate=per_field_pass_rate,
        per_field_type_pass_rate=per_field_type,
        false_negative_rate=fn_rate,
        hallucination_rate=hall_rate,
    )


def check_regression_gate(
    result: DocumentResult,
    gate_config: dict[str, float],
    fail_on_regression: bool = False,
) -> list[str]:
    """Check if any regression gate thresholds are breached.

    Args:
        result: Computed DocumentResult.
        gate_config: Threshold dict from config.evaluation.regression_gate.
        fail_on_regression: If True, call sys.exit(1) on breach.

    Returns:
        List of breach descriptions (empty if all thresholds pass).
    """
    breaches: list[str] = []

    min_pass_rate = gate_config.get("document_field_pass_rate", 0.90)
    if result.document_field_pass_rate < min_pass_rate:
        breaches.append(
            f"document_field_pass_rate {result.document_field_pass_rate:.3f} < {min_pass_rate}"
        )

    min_perfect_rate = gate_config.get("director_perfect_match_rate", 0.50)
    if result.director_perfect_match_rate < min_perfect_rate:
        r = result.director_perfect_match_rate
        breaches.append(f"director_perfect_match_rate {r:.3f} < {min_perfect_rate}")

    max_hall_rate = gate_config.get("hallucination_rate", 0.05)
    if result.hallucination_rate > max_hall_rate:
        breaches.append(f"hallucination_rate {result.hallucination_rate:.3f} > {max_hall_rate}")

    if breaches and fail_on_regression:
        logger.error("regression_gate_breached", breaches=breaches)
        sys.exit(1)

    return breaches


def evaluate_corpus(
    document_pairs: list[tuple[BoardGovernanceDocument, BoardGovernanceDocument, str, str]],
    field_metrics: dict[str, str],
    thresholds: dict[str, float],
) -> CorpusResult:
    """Evaluate multiple (extracted, ground-truth) document pairs.

    Args:
        document_pairs: List of (extracted, gt, extracted_path, gt_path) tuples.
        field_metrics: Metric mapping from config.
        thresholds: Threshold mapping from config.

    Returns:
        CorpusResult with pooled metrics.
    """
    doc_results: list[DocumentResult] = []
    for ext, gt, ext_path, gt_path in document_pairs:
        dr = evaluate(ext, gt, field_metrics, thresholds, ext_path, gt_path)
        doc_results.append(dr)

    if not doc_results:
        return CorpusResult(
            document_results=[],
            corpus_field_pass_rate=0.0,
            corpus_document_perfect_match_rate=0.0,
            corpus_per_field_pass_rate={},
            corpus_hallucination_rate=0.0,
            corpus_false_negative_rate=0.0,
        )

    corpus_pass_rate = sum(d.document_field_pass_rate for d in doc_results) / len(doc_results)
    perfect_docs = sum(1 for d in doc_results if d.document_perfect_match)
    perfect_rate = perfect_docs / len(doc_results)
    corpus_hall_rate = sum(d.hallucination_rate for d in doc_results) / len(doc_results)
    corpus_fn_rate = sum(d.false_negative_rate for d in doc_results) / len(doc_results)

    # Pool per-field pass rates
    all_field_buckets: dict[str, list[float]] = {}
    for dr in doc_results:
        for fp, rate in dr.per_field_pass_rate.items():
            all_field_buckets.setdefault(fp, []).append(rate)
    corpus_per_field = {fp: sum(v) / len(v) for fp, v in all_field_buckets.items()}

    return CorpusResult(
        document_results=doc_results,
        corpus_field_pass_rate=corpus_pass_rate,
        corpus_document_perfect_match_rate=perfect_rate,
        corpus_per_field_pass_rate=corpus_per_field,
        corpus_hallucination_rate=corpus_hall_rate,
        corpus_false_negative_rate=corpus_fn_rate,
    )
