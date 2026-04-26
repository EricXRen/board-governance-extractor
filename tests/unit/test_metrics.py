"""Unit tests for evaluation metric functions."""

from __future__ import annotations

from gov_extract.evaluation.metrics import (
    date_match,
    evaluate_field,
    exact_match,
    fuzzy_match,
    list_f1,
    numeric_error,
)


class TestExactMatch:
    def test_identical(self) -> None:
        assert exact_match("foo", "foo") == 1.0

    def test_case_insensitive(self) -> None:
        assert exact_match("FOO", "foo") == 1.0

    def test_strip_whitespace(self) -> None:
        assert exact_match("  foo  ", "foo") == 1.0

    def test_different(self) -> None:
        assert exact_match("foo", "bar") == 0.0

    def test_both_none(self) -> None:
        assert exact_match(None, None) == 1.0

    def test_pred_none(self) -> None:
        assert exact_match(None, "foo") == 0.0

    def test_gt_none(self) -> None:
        assert exact_match("foo", None) == 0.0


class TestFuzzyMatch:
    def test_identical(self) -> None:
        assert fuzzy_match("hello world", "hello world") == 1.0

    def test_both_none(self) -> None:
        assert fuzzy_match(None, None) == 1.0

    def test_pred_none(self) -> None:
        assert fuzzy_match(None, "foo") == 0.0

    def test_gt_none(self) -> None:
        assert fuzzy_match("foo", None) == 0.0

    def test_high_similarity(self) -> None:
        # These should match above 90
        score = fuzzy_match("John Smith", "John A Smith", threshold=90.0)
        assert score > 0.0

    def test_below_threshold(self) -> None:
        score = fuzzy_match("apple", "orange", threshold=90.0)
        assert score == 0.0


class TestDateMatch:
    def test_exact_match(self) -> None:
        result = date_match("2020-04-01", "2020-04-01")
        assert result["exact"] == 1.0
        assert result["year_only"] == 1.0

    def test_year_only_match(self) -> None:
        result = date_match("2020-04-01", "2020-06-15")
        assert result["exact"] == 0.0
        assert result["year_only"] == 1.0

    def test_no_match(self) -> None:
        result = date_match("2019-01-01", "2020-01-01")
        assert result["exact"] == 0.0
        assert result["year_only"] == 0.0

    def test_both_none(self) -> None:
        result = date_match(None, None)
        assert result["exact"] == 1.0

    def test_pred_none(self) -> None:
        result = date_match(None, "2020-01-01")
        assert result["exact"] == 0.0


class TestNumericError:
    def test_identical(self) -> None:
        result = numeric_error(10.0, 10.0)
        assert result["pass"] == 1.0
        assert result["absolute_error"] == 0.0

    def test_within_tolerance(self) -> None:
        result = numeric_error(10.2, 10.0, tolerance=0.05)
        assert result["pass"] == 1.0

    def test_outside_tolerance(self) -> None:
        result = numeric_error(11.0, 10.0, tolerance=0.05)
        assert result["pass"] == 0.0

    def test_both_none(self) -> None:
        result = numeric_error(None, None)
        assert result["pass"] == 1.0

    def test_pred_none(self) -> None:
        result = numeric_error(None, 10.0)
        assert result["pass"] == 0.0

    def test_gt_zero(self) -> None:
        result = numeric_error(0.0, 0.0)
        assert result["pass"] == 1.0


class TestListF1:
    def test_exact_match(self) -> None:
        result = list_f1(["a", "b", "c"], ["a", "b", "c"])
        assert result["f1"] == 1.0

    def test_both_empty(self) -> None:
        result = list_f1([], [])
        assert result["f1"] == 1.0

    def test_pred_empty_gt_nonempty(self) -> None:
        result = list_f1([], ["a", "b"])
        assert result["f1"] == 0.0

    def test_pred_nonempty_gt_empty(self) -> None:
        result = list_f1(["a"], [])
        assert result["f1"] == 0.0

    def test_partial_overlap(self) -> None:
        result = list_f1(["a", "b", "c"], ["a", "b", "d"])
        assert 0 < result["f1"] < 1.0

    def test_order_insensitive(self) -> None:
        r1 = list_f1(["a", "b", "c"], ["c", "b", "a"])
        r2 = list_f1(["a", "b", "c"], ["a", "b", "c"])
        assert r1["f1"] == r2["f1"]

    def test_case_insensitive(self) -> None:
        result = list_f1(["Finance", "Strategy"], ["finance", "strategy"])
        assert result["f1"] == 1.0


class TestEvaluateField:
    THRESHOLDS = {
        "fuzzy_match": 90.0,
        "list_f1": 0.90,
        "semantic_similarity": 0.80,
        "numeric_error_tolerance": 0.05,
    }

    def test_false_negative(self) -> None:
        result = evaluate_field(
            "biographical.full_name", None, "John Smith", "exact_match", self.THRESHOLDS
        )
        assert result.failure_mode == "false_negative"
        assert result.score == 0.0
        assert not result.passed

    def test_hallucination(self) -> None:
        result = evaluate_field(
            "biographical.full_name", "John Smith", None, "exact_match", self.THRESHOLDS
        )
        assert result.failure_mode == "hallucination"
        assert result.score == 0.0
        assert not result.passed

    def test_both_none_passes(self) -> None:
        result = evaluate_field("biographical.age", None, None, "numeric_error", self.THRESHOLDS)
        assert result.passed is True
        assert result.score == 1.0
        assert result.failure_mode is None

    def test_exact_match_pass(self) -> None:
        result = evaluate_field(
            "board_role.designation", "Chair", "Chair", "exact_match", self.THRESHOLDS
        )
        assert result.passed is True

    def test_below_threshold(self) -> None:
        result = evaluate_field(
            "biographical.full_name", "apple", "orange", "exact_match", self.THRESHOLDS
        )
        assert result.failure_mode == "below_threshold"
        assert not result.passed

    def test_list_false_negative(self) -> None:
        result = evaluate_field(
            "board_role.committee_memberships", [], ["Audit", "Risk"], "list_f1", self.THRESHOLDS
        )
        assert result.failure_mode == "false_negative"

    def test_numeric_error_field(self) -> None:
        result = evaluate_field(
            "attendance.board_meetings_attended", 10, 10, "numeric_error", self.THRESHOLDS
        )
        assert result.passed is True
