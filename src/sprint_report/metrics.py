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
from dataclasses import dataclass
from datetime import date, timedelta

from .models import (
    BurndownPoint,
    ProjectItem,
    Snapshot,
    SprintMetrics,
    sum_points,
    utc_today,
)

__all__ = [
    "iteration_metrics",
    "iteration_titles",
    "velocity_series",
    "rolling_average",
    "burndown",
    "forecast_sprints",
    "carryover_items",
    "prior_iterations",
    "burndown_from_closures",
    "throughput",
    "velocity_by_closure",
    "scope_changes",
    "ScopeChange",
]

#: Origin field value marking work pulled in after sprint start.
ORIGIN_UNPLANNED = "unplanned"
#: Origin field value marking work that rolled IN from a previous sprint.
#: This describes provenance, not destination — work leaving for the next
#: sprint is simply incomplete, and is reported by :func:`carryover_items`.
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
                # Scope is read per day, so a burnup built from snapshots
                # shows mid-sprint growth as the scope line rising.
                scope=round(sum_points(scoped), 1),
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


def prior_iterations(
    items: Iterable[ProjectItem],
    iteration: str,
    limit: int | None = None,
) -> list[SprintMetrics]:
    """Metrics for the sprints that ran *before* a given iteration.

    A GitHub iteration field is generated forward, so a board almost always
    carries several future sprints. Those must never appear in a trend: an
    unstarted sprint has zero completed points, which reads as a collapse in
    velocity and drags any rolling average toward zero.

    Iterations with no start date cannot be placed on the timeline and are
    excluded rather than guessed at.

    Args:
        items: All board items.
        iteration: The iteration being reported on.
        limit: If given, keep only the most recent ``limit`` prior sprints.

    Returns:
        Metrics for strictly earlier iterations, oldest first.

    Example:
        >>> prior_iterations([], "Sprint 1")
        []
    """
    materialised = list(items)
    current = iteration_metrics(materialised, iteration)
    if current.start is None:
        return []

    earlier: list[SprintMetrics] = []
    for title in iteration_titles(materialised):
        if title == iteration:
            continue
        metrics = iteration_metrics(materialised, title)
        if metrics.start is None or metrics.start >= current.start:
            continue
        earlier.append(metrics)

    earlier.sort(key=lambda metric: metric.start or date.min)
    if limit is not None and limit > 0:
        return earlier[-limit:]
    return earlier


def burndown_from_closures(
    items: Iterable[ProjectItem],
    iteration: str,
    today: date | None = None,
) -> list[BurndownPoint]:
    """Reconstruct a burndown from the dates items were closed.

    Snapshots are the accurate source, because they record scope as it stood
    on each day. This is the fallback when no snapshots exist: GitHub retains
    a ``closedAt`` timestamp on every closed issue, and remaining work on a
    given day is the sprint's scope minus everything closed by then.

    The known inaccuracy is scope: an item added on day five is counted from
    day one, because nothing records when it joined the sprint. The curve
    therefore starts at final scope rather than opening scope, which
    understates mid-sprint growth. Snapshots fix this; nothing else can.

    Items completed by board status alone — moved to Done without the issue
    being closed — carry no timestamp and are treated as closed on the final
    day, since the only certain fact is that they are done now.

    Args:
        items: All board items.
        iteration: The iteration to chart.
        today: Override for the current date, for testing.

    Returns:
        One :class:`BurndownPoint` per day from sprint start to the earlier of
        today and the sprint end. Empty when the iteration has no dates or no
        estimated work.

    Example:
        >>> burndown_from_closures([], "Sprint 1")
        []
    """
    scoped = [item for item in items if item.iteration == iteration]
    if not scoped:
        return []

    start = next((i.iteration_start for i in scoped if i.iteration_start), None)
    end = next((i.iteration_end for i in scoped if i.iteration_end), None)
    if start is None or end is None:
        return []

    total = sum_points(scoped)
    if total <= 0:
        return []

    current = today or utc_today()
    last_day = min(end, current)
    if last_day < start:
        return []

    # Points closing on each day. An item done on the board but with no
    # closure timestamp is attributed to the last day in view: it is finished
    # now, and guessing an earlier date would invent history.
    closed_on: dict[date, float] = {}
    for item in scoped:
        if not item.is_complete:
            continue
        when = item.closed_at or last_day
        when = max(start, min(when, last_day))
        closed_on[when] = closed_on.get(when, 0.0) + item.effective_points

    span = max((end - start).days, 1)
    points: list[BurndownPoint] = []
    burned = 0.0
    day = start
    while day <= last_day:
        burned += closed_on.get(day, 0.0)
        elapsed = (day - start).days
        points.append(
            BurndownPoint(
                day=day,
                remaining=round(total - burned, 1),
                ideal=round(total * (1 - min(elapsed / span, 1.0)), 1),
                # Closure dates cannot say when an item joined the sprint, so
                # scope is flat here. Snapshots are what make it move.
                scope=round(total, 1),
            )
        )
        day += timedelta(days=1)
    return points


def throughput(
    items: Iterable[ProjectItem], start: date, end: date
) -> float:
    """Points closed within a date window, whoever they were assigned to.

    Args:
        items: Any collection of project items.
        start: First day of the window, inclusive.
        end: Last day of the window, inclusive.

    Returns:
        The sum of estimates on items closed inside the window.

    Raises:
        ValueError: If ``end`` precedes ``start``.

    Example:
        >>> throughput([], date(2026, 8, 10), date(2026, 8, 23))
        0.0
    """
    if end < start:
        raise ValueError("end must not precede start")
    return float(
        sum(
            item.effective_points
            for item in items
            if item.closed_at and start <= item.closed_at <= end
        )
    )


def velocity_by_closure(items: Iterable[ProjectItem]) -> dict[str, float]:
    """Velocity per sprint, measured by when work actually closed.

    This is a different question from :attr:`SprintMetrics.completed_points`,
    which asks "how much of what this sprint was assigned is now done".
    Throughput asks "how much closed during this sprint's dates", and the
    distinction matters for two reasons.

    It is **stable**. Moving an unfinished item into the next iteration
    retroactively removes its points from the sprint that failed to finish
    it, so assignment-based velocity for a past sprint changes after the
    fact. A closure date does not move.

    It is **complete**. Work closed during a sprint but never assigned to it
    still consumed the team's capacity, and belongs in a throughput figure.

    Items with no closure date are excluded rather than guessed at, so a board
    where completion is tracked only by Status yields zeros here.

    Args:
        items: All board items.

    Returns:
        A mapping of iteration title to points closed within its dates,
        ordered chronologically. Iterations without dates are omitted.

    Example:
        >>> velocity_by_closure([])
        {}
    """
    materialised = list(items)
    windows: dict[str, tuple[date, date]] = {}
    for title in iteration_titles(materialised):
        scoped = [i for i in materialised if i.iteration == title]
        start = next((i.iteration_start for i in scoped if i.iteration_start), None)
        end = next((i.iteration_end for i in scoped if i.iteration_end), None)
        if start and end:
            windows[title] = (start, end)

    return {
        title: throughput(materialised, start, end)
        for title, (start, end) in windows.items()
    }


@dataclass(frozen=True)
class ScopeChange:
    """Items entering or leaving a sprint on one day.

    Attributes:
        day: The day the change was first observed.
        added: Items present that were absent the previous day.
        removed: Items absent that were present the previous day.

    Example:
        >>> from datetime import date
        >>> ScopeChange(date(2026, 8, 12), [], []).net_points
        0.0
    """

    day: date
    added: Sequence[ProjectItem]
    removed: Sequence[ProjectItem]

    @property
    def added_points(self) -> float:
        """Points that entered the sprint.

        Returns:
            The sum of estimates on added items.

        Example:
            >>> from datetime import date
            >>> ScopeChange(date(2026, 8, 12), [], []).added_points
            0.0
        """
        return sum_points(self.added)

    @property
    def removed_points(self) -> float:
        """Points that left the sprint.

        Returns:
            The sum of estimates on removed items.

        Example:
            >>> from datetime import date
            >>> ScopeChange(date(2026, 8, 12), [], []).removed_points
            0.0
        """
        return sum_points(self.removed)

    @property
    def net_points(self) -> float:
        """Net change in committed points.

        Returns:
            Added minus removed.

        Example:
            >>> from datetime import date
            >>> ScopeChange(date(2026, 8, 12), [], []).net_points
            0.0
        """
        return self.added_points - self.removed_points


def scope_changes(
    snapshots: Sequence[Snapshot], iteration: str
) -> list[ScopeChange]:
    """Find items that entered or left a sprint, day by day.

    GitHub keeps no history of iteration-field changes, so this is derived by
    diffing consecutive snapshots. It is therefore only as granular as the
    collector's schedule: two changes on the same day net out, and a day with
    no snapshot is attributed to the next one.

    Args:
        snapshots: Daily snapshots, in any order.
        iteration: The iteration to examine.

    Returns:
        One :class:`ScopeChange` per day where membership changed, oldest
        first. Days with no change are omitted.

    Example:
        >>> scope_changes([], "Sprint 1")
        []
    """
    relevant = sorted(snapshots, key=lambda snap: snap.captured_on)
    if len(relevant) < 2:
        return []

    changes: list[ScopeChange] = []
    previous = {i.item_id: i for i in relevant[0].for_iteration(iteration)}

    for snapshot in relevant[1:]:
        current = {i.item_id: i for i in snapshot.for_iteration(iteration)}
        added = [item for key, item in current.items() if key not in previous]
        removed = [item for key, item in previous.items() if key not in current]
        if added or removed:
            changes.append(
                ScopeChange(day=snapshot.captured_on, added=added, removed=removed)
            )
        previous = current

    return changes
