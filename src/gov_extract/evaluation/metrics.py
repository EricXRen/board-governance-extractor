"""Field-level metric functions and FieldResult dataclass."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_MODEL: Any = None  # Lazy singleton for sentence-transformers


@dataclass
class FieldResult:
    """Result of comparing a single field between extracted and ground-truth data."""

    field_path: str
    metric_used: str
    predicted_value: Any
    ground_truth_value: Any
    score: float
    passed: bool
    failure_mode: str | None  # "false_negative" | "hallucination" | "below_threshold" | None


def _is_empty(value: Any) -> bool:
    """Return True if the value is considered absent (None or empty list)."""
    if value is None:
        return True
    return bool(isinstance(value, list) and len(value) == 0)


def exact_match(pred: str | None, gt: str | None) -> float:
    """Normalise both strings and return 1.0 if identical, else 0.0.

    Args:
        pred: Predicted string value.
        gt: Ground-truth string value.

    Returns:
        1.0 for match, 0.0 otherwise.
    """
    if pred is None and gt is None:
        return 1.0
    if pred is None or gt is None:
        return 0.0
    return 1.0 if pred.strip().lower() == gt.strip().lower() else 0.0


def fuzzy_match(pred: str | None, gt: str | None, threshold: float = 90.0) -> float:
    """Compute token_sort_ratio fuzzy match between two strings.

    Args:
        pred: Predicted string value.
        gt: Ground-truth string value.
        threshold: Minimum ratio to return a non-zero score.

    Returns:
        Ratio / 100 if >= threshold, else 0.0. Returns 1.0 if both are None.
    """
    if pred is None and gt is None:
        return 1.0
    if pred is None or gt is None:
        return 0.0
    try:
        from rapidfuzz import fuzz

        ratio = fuzz.token_sort_ratio(pred, gt)
    except ImportError:
        # Basic fallback
        p_lower = pred.strip().lower()
        g_lower = gt.strip().lower()
        if p_lower == g_lower:
            ratio = 100.0
        else:
            common = sum(min(p_lower.count(c), g_lower.count(c)) for c in set(g_lower))
            ratio = 100.0 * 2 * common / (len(p_lower) + len(g_lower))

    return ratio / 100.0 if ratio >= threshold else 0.0


def date_match(pred: str | None, gt: str | None) -> dict[str, float]:
    """Compare ISO-8601 date strings at exact and year-only levels.

    Args:
        pred: Predicted ISO-8601 date string.
        gt: Ground-truth ISO-8601 date string.

    Returns:
        Dict with "exact" and "year_only" scores (0.0 or 1.0 each).
    """
    if pred is None and gt is None:
        return {"exact": 1.0, "year_only": 1.0}
    if pred is None or gt is None:
        return {"exact": 0.0, "year_only": 0.0}

    exact = 1.0 if pred.strip() == gt.strip() else 0.0

    try:
        pred_year = pred.strip()[:4]
        gt_year = gt.strip()[:4]
        year_only = 1.0 if pred_year == gt_year else 0.0
    except Exception:
        year_only = 0.0

    return {"exact": exact, "year_only": year_only}


def numeric_error(
    pred: float | None, gt: float | None, tolerance: float = 0.05
) -> dict[str, float]:
    """Compute absolute and relative error for numeric values.

    Args:
        pred: Predicted numeric value.
        gt: Ground-truth numeric value.
        tolerance: Maximum relative error for a passing result.

    Returns:
        Dict with "absolute_error", "relative_error", and "pass" (0.0 or 1.0).
    """
    if pred is None and gt is None:
        return {"absolute_error": 0.0, "relative_error": 0.0, "pass": 1.0}
    if pred is None or gt is None:
        return {"absolute_error": float("inf"), "relative_error": float("inf"), "pass": 0.0}

    abs_err = abs(float(pred) - float(gt))
    rel_err = abs_err / abs(float(gt)) if gt != 0 else abs(float(pred))

    passed = 1.0 if rel_err <= tolerance else 0.0
    return {"absolute_error": abs_err, "relative_error": rel_err, "pass": passed}


def list_f1(pred: list[Any], gt: list[Any]) -> dict[str, float]:
    """Compute set-based precision, recall, and F1 for lists of strings.

    Args:
        pred: Predicted list of items.
        gt: Ground-truth list of items.

    Returns:
        Dict with "precision", "recall", and "f1" scores.
    """
    if not pred and not gt:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}

    pred_set = {str(x).strip().lower() for x in pred}
    gt_set = {str(x).strip().lower() for x in gt}

    if not pred_set and gt_set:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    if pred_set and not gt_set:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    tp = len(pred_set & gt_set)
    precision = tp / len(pred_set) if pred_set else 0.0
    recall = tp / len(gt_set) if gt_set else 0.0

    f1 = 2 * precision * recall / (precision + recall) if precision + recall > 0 else 0.0

    return {"precision": precision, "recall": recall, "f1": f1}


def semantic_similarity(pred: str | None, gt: str | None, threshold: float = 0.80) -> float:
    """Compute cosine similarity between two text strings using sentence-transformers.

    Args:
        pred: Predicted text.
        gt: Ground-truth text.
        threshold: Minimum similarity for a passing result.

    Returns:
        Cosine similarity score in [0.0, 1.0]. Returns 1.0 if both are None.

    Raises:
        RuntimeError: If sentence-transformers is not installed.
    """
    global _MODEL

    if pred is None and gt is None:
        return 1.0
    if pred is None or gt is None:
        return 0.0

    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is required for semantic similarity evaluation. "
            "Install it with: uv sync --extra eval"
        ) from exc

    if _MODEL is None:
        _MODEL = SentenceTransformer("all-MiniLM-L6-v2")

    embeddings = _MODEL.encode([pred, gt])
    pred_emb = embeddings[0]
    gt_emb = embeddings[1]

    # Cosine similarity
    norm = np.linalg.norm(pred_emb) * np.linalg.norm(gt_emb)
    if norm == 0:
        return 0.0

    similarity = float(np.dot(pred_emb, gt_emb) / norm)
    return max(0.0, min(1.0, similarity))


def evaluate_field(
    field_path: str,
    pred: Any,
    gt: Any,
    metric_name: str,
    thresholds: dict[str, float],
) -> FieldResult:
    """Evaluate a single field and return a FieldResult.

    Args:
        field_path: Dot-notation path, e.g. "biographical.full_name".
        pred: Predicted value (may be None or []).
        gt: Ground-truth value (may be None or []).
        metric_name: One of: exact_match, fuzzy_match, date_match,
            numeric_error, list_f1, semantic_similarity.
        thresholds: Dict of threshold values per metric name.

    Returns:
        FieldResult with score, pass/fail, and failure mode.
    """
    pred_empty = _is_empty(pred)
    gt_empty = _is_empty(gt)

    # Both absent — trivially passing
    if pred_empty and gt_empty:
        return FieldResult(
            field_path=field_path,
            metric_used=metric_name,
            predicted_value=pred,
            ground_truth_value=gt,
            score=1.0,
            passed=True,
            failure_mode=None,
        )

    # False negative: missing extraction
    if pred_empty and not gt_empty:
        return FieldResult(
            field_path=field_path,
            metric_used=metric_name,
            predicted_value=pred,
            ground_truth_value=gt,
            score=0.0,
            passed=False,
            failure_mode="false_negative",
        )

    # Hallucination: invented value
    if not pred_empty and gt_empty:
        return FieldResult(
            field_path=field_path,
            metric_used=metric_name,
            predicted_value=pred,
            ground_truth_value=gt,
            score=0.0,
            passed=False,
            failure_mode="hallucination",
        )

    # Both present — compute metric
    score: float
    passed: bool

    if metric_name == "exact_match":
        score = exact_match(pred, gt)
        passed = score == 1.0

    elif metric_name == "fuzzy_match":
        threshold = thresholds.get("fuzzy_match", 90.0)
        score = fuzzy_match(pred, gt, threshold)
        passed = score > 0.0

    elif metric_name == "date_match":
        result = date_match(pred, gt)
        score = result["exact"]
        passed = score == 1.0

    elif metric_name == "numeric_error":
        tolerance = thresholds.get("numeric_error_tolerance", 0.05)
        result_d = numeric_error(pred, gt, tolerance)
        score = result_d["pass"]
        passed = result_d["pass"] == 1.0

    elif metric_name == "list_f1":
        threshold = thresholds.get("list_f1", 0.90)
        result_l = list_f1(pred or [], gt or [])
        score = result_l["f1"]
        passed = score >= threshold

    elif metric_name == "semantic_similarity":
        threshold = thresholds.get("semantic_similarity", 0.80)
        score = semantic_similarity(pred, gt, threshold)
        passed = score >= threshold

    else:
        score = exact_match(str(pred), str(gt))
        passed = score == 1.0

    failure_mode = None if passed else "below_threshold"

    return FieldResult(
        field_path=field_path,
        metric_used=metric_name,
        predicted_value=pred,
        ground_truth_value=gt,
        score=score,
        passed=passed,
        failure_mode=failure_mode,
    )
