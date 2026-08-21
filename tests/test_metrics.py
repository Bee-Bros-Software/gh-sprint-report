"""Unit tests for :mod:`sprint_report.metrics`."""

from __future__ import annotations

from datetime import date

import pytest

from sprint_report.metrics import (
    burndown,
    carryover_items,
    forecast_sprints,
    iteration_metrics,
    iteration_titles,
    milestone_remaining,
    next_business_days,
    rolling_average,
    velocity_series,
)


class TestIterationMetrics:
    """Aggregation for a single iteration."""

    def test_totals_committed_and_completed(self, board_items):
        """Committed sums all points; completed sums only finished items."""
        metrics = iteration_metrics(board_items, "Sprint 14")
        assert metrics.committed_points == 16.0
        assert metrics.completed_points == 11.0

    def test_unestimated_items_counted_but_score_zero(self, board_items):
        """An item with no estimate is counted but adds no points."""
        metrics = iteration_metrics(board_items, "Sprint 14")
        assert metrics.unestimated_items == 1
        assert metrics.total_items == 4

    def test_origin_split(self, board_items):
        """Points are partitioned across planned, unplanned, and carryover."""
        metrics = iteration_metrics(board_items, "Sprint 13")
        assert metrics.planned_points == 8.0
        assert metrics.unplanned_points == 5.0
        assert metrics.carryover_points == 3.0

    def test_missing_origin_treated_as_planned(self):
        """An unset Origin field defaults to planned rather than dropping out."""
        from sprint_report.models import ProjectItem

        item = ProjectItem(item_id="x", title="t", iteration="S1", points=5, origin=None)
        assert iteration_metrics([item], "S1").planned_points == 5.0

    def test_unknown_iteration_yields_zeros(self, board_items):
        """Reporting on an absent iteration returns an empty metric set."""
        metrics = iteration_metrics(board_items, "Sprint 99")
        assert metrics.committed_points == 0.0
        assert metrics.total_items == 0

    def test_predictability_and_share(self, board_items):
        """Derived percentages follow from the point totals."""
        metrics = iteration_metrics(board_items, "Sprint 14")
        assert metrics.predictability == pytest.approx(68.8, abs=0.1)
        assert metrics.unplanned_share == pytest.approx(31.2, abs=0.1)

    def test_predictability_zero_when_nothing_committed(self):
        """Dividing by an empty commitment does not raise."""
        assert iteration_metrics([], "S1").predictability == 0.0


class TestIterationOrdering:
    """Chronological ordering of iterations."""

    def test_orders_by_start_date(self, board_items):
        """Iterations sort by start date, not alphabetically."""
        assert iteration_titles(board_items) == [
            "Sprint 12",
            "Sprint 13",
            "Sprint 14",
        ]

    def test_ignores_items_without_iteration(self, board_items):
        """Backlog items with no iteration are excluded."""
        from sprint_report.models import ProjectItem

        loose = ProjectItem(item_id="z", title="Backlog item", points=5)
        assert iteration_titles([*board_items, loose]) == [
            "Sprint 12",
            "Sprint 13",
            "Sprint 14",
        ]

    def test_empty_board(self):
        """An empty board yields no iterations."""
        assert iteration_titles([]) == []


class TestVelocitySeries:
    """Per-sprint series construction."""

    def test_one_entry_per_iteration(self, board_items):
        """Every iteration produces one metrics object."""
        assert len(velocity_series(board_items)) == 3

    def test_limit_keeps_most_recent(self, board_items):
        """A limit trims from the front, keeping recent sprints."""
        series = velocity_series(board_items, limit=2)
        assert [metric.iteration for metric in series] == [
            "Sprint 13",
            "Sprint 14",
        ]


class TestRollingAverage:
    """Trailing-window averaging."""

    def test_averages_trailing_window(self):
        """Only the last ``window`` values contribute."""
        assert rolling_average([10, 20, 30, 40], window=3) == 30.0

    def test_short_series_uses_all_values(self):
        """A series shorter than the window averages what exists."""
        assert rolling_average([10, 20], window=3) == 15.0

    def test_empty_series_is_zero(self):
        """An empty series averages to zero rather than raising."""
        assert rolling_average([]) == 0.0

    def test_non_positive_window_rejected(self):
        """A zero or negative window is a programming error."""
        with pytest.raises(ValueError):
            rolling_average([1, 2], window=0)


class TestBurndown:
    """Burndown curve construction from snapshots."""

    def test_one_point_per_snapshot_day(self, snapshot_series):
        """Each snapshot covering the sprint yields one curve point."""
        curve = burndown(snapshot_series, "Sprint 14")
        assert len(curve) == 4

    def test_remaining_decreases_as_work_completes(self, snapshot_series):
        """Completing items lowers the remaining figure."""
        curve = burndown(snapshot_series, "Sprint 14")
        assert curve[0].remaining == 16.0
        assert curve[-1].remaining == 5.0

    def test_ideal_line_starts_at_opening_scope(self, snapshot_series):
        """The ideal line anchors to scope at the first snapshot."""
        curve = burndown(snapshot_series, "Sprint 14")
        assert curve[0].ideal == 16.0
        assert curve[-1].ideal < curve[0].ideal

    def test_no_snapshots_returns_empty(self):
        """Absent history produces an empty curve, not an error."""
        assert burndown([], "Sprint 14") == []

    def test_iteration_absent_from_snapshots(self, snapshot_series):
        """Snapshots that never mention the iteration are ignored."""
        assert burndown(snapshot_series, "Sprint 99") == []


class TestForecast:
    """Sprint-count projection."""

    def test_divides_remaining_by_velocity(self):
        """A straightforward division, rounded to one decimal."""
        assert forecast_sprints(60, 25) == 2.4

    def test_zero_velocity_has_no_forecast(self):
        """Without velocity there is no meaningful projection."""
        assert forecast_sprints(60, 0) is None

    def test_negative_velocity_has_no_forecast(self):
        """Negative velocity is nonsensical and yields no projection."""
        assert forecast_sprints(60, -5) is None


class TestCarryover:
    """Identification of work rolling forward."""

    def test_lists_only_incomplete_items(self, board_items):
        """Finished items never carry over."""
        rolling = carryover_items(board_items, "Sprint 14")
        assert {item.item_id for item in rolling} == {"8", "9"}

    def test_sorted_heaviest_first(self, board_items):
        """Larger estimates lead so the biggest risks are visible first."""
        rolling = carryover_items(board_items, "Sprint 14")
        assert rolling[0].effective_points >= rolling[-1].effective_points


class TestMilestoneRemaining:
    """Milestone-scoped outstanding work."""

    def test_sums_incomplete_milestone_points(self, board_items):
        """Only open items on the milestone count."""
        assert milestone_remaining(board_items, "v2.0") == 5.0

    def test_unknown_milestone_is_zero(self, board_items):
        """An unrecognised milestone contributes nothing."""
        assert milestone_remaining(board_items, "v9.9") == 0.0


class TestBusinessDays:
    """Weekday generation."""

    def test_skips_weekend(self):
        """Saturday and Sunday are excluded."""
        days = next_business_days(date(2026, 8, 21), 2)
        assert days == [date(2026, 8, 21), date(2026, 8, 24)]

    def test_zero_count_returns_empty(self):
        """Requesting no days returns an empty list."""
        assert next_business_days(date(2026, 8, 21), 0) == []

    def test_negative_count_rejected(self):
        """A negative count is a programming error."""
        with pytest.raises(ValueError):
            next_business_days(date(2026, 8, 21), -1)
