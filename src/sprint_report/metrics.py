"""Sprint metric computations.

Every function here is pure: it takes items or snapshots and returns numbers.
That keeps the reporting logic fully unit-testable without touching the network
or the filesystem.

The metrics implemented are the ones worth putting in front of a sprint review:

* **Velocity** — points completed per iteration, plus a rolling average.
* **Predictability** — completed as a percentage of committed.
* **Work mix** — planned vs unplanned vs carryover.
* **Burndown** — remaining points per day against a linear ideal.
* **Forecast** — sprints remaining for a milestone at current velocity.

Example:
    >>> from sprint_report.models import ProjectItem
    >>> items = [
    ...     ProjectItem(item_id="a", title="x", iteration="S1", points=5,
    ...                 status="Done", origin="Planned"),
    ...     ProjectItem(item_id="b", title="y", iteration="S1", points=3,
    ...                 origin="Unplanned"),
    ... ]
    >>> metrics = iteration_metrics(items, "S1")
    >>> metrics.committed_points, metrics.completed_points
    (8.0, 5.0)
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, timedelta

from .models import (
    BurndownPoint,
    ProjectItem,
    Snapshot,
    SprintMetrics,
    sum_points,
)

__all__ = [
    "iteration_metrics",
    "iteration_titles",
    "velocity_series",
    "rolling_average",
    "burndown",
    "forecast_sprints",
    "carryover_items",
]

#: Origin field value marking work pulled in after sprint start.
ORIGIN_UNPLANNED = "unplanned"
#: Origin field value marking work rolled over from a previous sprint.
ORIGIN_CARRYOVER = "carryover"
#: Origin field value marking work committed at planning.
ORIGIN_PLANNED = "planned"


def _origin(item: ProjectItem) -> str:
    """Normalise an item's origin value for comparison.

    Args:
        item: The item to inspect.

    Returns:
        The lowercased origin, defaulting to ``"planned"`` when unset.

    Example:
        >>> _origin(ProjectItem(item_id="a", title="t"))
        'planned'
    """
    return (item.origin or ORIGIN_PLANNED).strip().lower()


def iteration_metrics(items: Iterable[ProjectItem], iteration: str) -> SprintMetrics:
    """Compute aggregate metrics for one iteration.

    Args:
        items: All board items; those outside ``iteration`` are ignored.
        iteration: The iteration title to report on.

    Returns:
        A populated :class:`SprintMetrics`.

    Example:
        >>> iteration_metrics([], "S1").committed_points
        0.0
    """
    scoped = [item for item in items if item.iteration == iteration]
    completed = [item for item in scoped if item.is_complete]

    start = next((i.iteration_start for i in scoped if i.iteration_start), None)
    end = next((i.iteration_end for i in scoped if i.iteration_end), None)

    return SprintMetrics(
        iteration=iteration,
        start=start,
        end=end,
        committed_points=sum_points(scoped),
        completed_points=sum_points(completed),
        planned_points=sum_points(i for i in scoped if _origin(i) == ORIGIN_PLANNED),
        unplanned_points=sum_points(i for i in scoped if _origin(i) == ORIGIN_UNPLANNED),
        carryover_points=sum_points(i for i in scoped if _origin(i) == ORIGIN_CARRYOVER),
        unestimated_items=sum(1 for i in scoped if i.points is None),
        total_items=len(scoped),
        completed_items=len(completed),
    )


def iteration_titles(items: Iterable[ProjectItem]) -> list[str]:
    """List every iteration present, ordered by start date.

    Iterations without a start date sort last, alphabetically.

    Args:
        items: Board items to scan.

    Returns:
        Unique iteration titles in chronological order.

    Example:
        >>> iteration_titles([])
        []
    """
    starts: dict[str, date | None] = {}
    for item in items:
        if not item.iteration:
            continue
        if item.iteration not in starts or starts[item.iteration] is None:
            starts[item.iteration] = item.iteration_start
    return sorted(
        starts,
        key=lambda title: (starts[title] is None, starts[title] or date.max, title),
    )


def velocity_series(
    items: Iterable[ProjectItem], limit: int | None = None
) -> list[SprintMetrics]:
    """Compute metrics for every iteration, chronologically.

    Args:
        items: All board items.
        limit: If given, return only the most recent ``limit`` iterations.

    Returns:
        A list of :class:`SprintMetrics`, oldest first.

    Example:
        >>> velocity_series([])
        []
    """
    materialised = list(items)
    series = [
        iteration_metrics(materialised, title) for title in iteration_titles(materialised)
    ]
    if limit is not None and limit > 0:
        return series[-limit:]
    return series


def rolling_average(values: Sequence[float], window: int = 3) -> float:
    """Average the last ``window`` values.

    Args:
        values: Ordered numeric series, oldest first.
        window: How many trailing values to include.

    Returns:
        The mean of the trailing window, rounded to one decimal, or ``0.0``
        for an empty series.

    Raises:
        ValueError: If ``window`` is not positive.

    Example:
        >>> rolling_average([10, 20, 30, 40], window=3)
        30.0
    """
    if window <= 0:
        raise ValueError("window must be a positive integer")
    if not values:
        return 0.0
    tail = list(values)[-window:]
    return round(sum(tail) / len(tail), 1)


def burndown(snapshots: Sequence[Snapshot], iteration: str) -> list[BurndownPoint]:
    """Build a burndown curve for one iteration from daily snapshots.

    The ideal line runs linearly from the iteration's committed total on day
    one to zero on the final day, using the scope as it stood at the first
    snapshot. Because remaining points are read from each day's snapshot,
    mid-sprint scope changes show up as the actual line moving against a fixed
    ideal — which is the point of the chart.

    Args:
        snapshots: Daily snapshots, in any order.
        iteration: The iteration title to chart.

    Returns:
        One :class:`BurndownPoint` per snapshot day that contains the
        iteration, oldest first. Empty when no snapshot covers it.

    Example:
        >>> burndown([], "S1")
        []
    """
    relevant = sorted(
        (
            snap
            for snap in snapshots
            if any(item.iteration == iteration for item in snap.items)
        ),
        key=lambda snap: snap.captured_on,
    )
    if not relevant:
        return []

    opening_scope = sum_points(relevant[0].for_iteration(iteration))
    start, end = _iteration_bounds(relevant, iteration)
    total_days = (
        max((end - start).days, 1) if start and end else max(len(relevant) - 1, 1)
    )

    points: list[BurndownPoint] = []
    for snapshot in relevant:
        scoped = snapshot.for_iteration(iteration)
        remaining = sum_points(item for item in scoped if not item.is_complete)
        elapsed = (
            (snapshot.captured_on - start).days if start else relevant.index(snapshot)
        )
        ratio = min(max(elapsed / total_days, 0.0), 1.0)
        points.append(
            BurndownPoint(
                day=snapshot.captured_on,
                remaining=round(remaining, 1),
                ideal=round(opening_scope * (1 - ratio), 1),
            )
        )
    return points


def _iteration_bounds(
    snapshots: Sequence[Snapshot], iteration: str
) -> tuple[date | None, date | None]:
    """Find the start and end dates of an iteration across snapshots.

    Args:
        snapshots: Snapshots to scan.
        iteration: Iteration title to match.

    Returns:
        A ``(start, end)`` tuple; either element may be ``None`` when the
        iteration field carried no dates.

    Example:
        >>> _iteration_bounds([], "S1")
        (None, None)
    """
    for snapshot in snapshots:
        for item in snapshot.for_iteration(iteration):
            if item.iteration_start and item.iteration_end:
                return item.iteration_start, item.iteration_end
    return None, None


def forecast_sprints(remaining_points: float, velocity: float) -> float | None:
    """Estimate how many sprints remain at a given velocity.

    Args:
        remaining_points: Outstanding points for the scope being forecast.
        velocity: Average points completed per sprint.

    Returns:
        Sprints required, rounded up to one decimal, or ``None`` when velocity
        is zero or negative and no forecast is possible.

    Example:
        >>> forecast_sprints(60, 25)
        2.4
    """
    if velocity <= 0:
        return None
    return round(remaining_points / velocity, 1)


def carryover_items(items: Iterable[ProjectItem], iteration: str) -> list[ProjectItem]:
    """List incomplete items in an iteration, i.e. what will roll forward.

    Args:
        items: All board items.
        iteration: The iteration being closed out.

    Returns:
        Incomplete items, heaviest estimate first.

    Example:
        >>> carryover_items([], "S1")
        []
    """
    scoped = [
        item for item in items if item.iteration == iteration and not item.is_complete
    ]
    return sorted(scoped, key=lambda item: item.effective_points, reverse=True)


def milestone_remaining(items: Iterable[ProjectItem], milestone: str) -> float:
    """Total outstanding points for a milestone.

    Args:
        items: All board items.
        milestone: Milestone title to scope to.

    Returns:
        Points on incomplete items carrying that milestone.

    Example:
        >>> milestone_remaining([], "v2.0")
        0.0
    """
    return sum_points(
        item for item in items if item.milestone == milestone and not item.is_complete
    )


def next_business_days(start: date, count: int) -> list[date]:
    """Generate ``count`` consecutive weekdays from ``start`` inclusive.

    Useful when projecting an ideal line across working days only.

    Args:
        start: First day to consider.
        count: How many weekdays to return.

    Returns:
        A list of dates excluding Saturdays and Sundays.

    Raises:
        ValueError: If ``count`` is negative.

    Example:
        >>> next_business_days(date(2026, 8, 21), 2)
        [datetime.date(2026, 8, 21), datetime.date(2026, 8, 24)]
    """
    if count < 0:
        raise ValueError("count must be non-negative")
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days
