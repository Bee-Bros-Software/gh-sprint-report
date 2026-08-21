"""Domain models for GitHub Projects sprint reporting.

This module defines the immutable data structures that flow through the
reporting pipeline: :class:`ProjectItem` (one row of a GitHub Project board),
:class:`Snapshot` (the state of a whole board on a given day),
:class:`SprintMetrics` (aggregates for a single iteration), and
:class:`BurndownPoint` (one day on a burndown curve).

All models are plain dataclasses with explicit JSON round-tripping so that
snapshots written by one version of the tool remain readable by the next.

Example:
    >>> item = ProjectItem(
    ...     item_id="PVTI_1",
    ...     title="Wire audit log export",
    ...     url="https://github.com/resolve/nxt/issues/12",
    ...     status="Done",
    ...     iteration="Sprint 14",
    ...     iteration_start=date(2026, 8, 10),
    ...     iteration_duration=14,
    ...     points=5.0,
    ...     origin="Planned",
    ...     closed=True,
    ... )
    >>> item.is_complete
    True
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any

__all__ = [
    "ProjectItem",
    "Snapshot",
    "SprintMetrics",
    "BurndownPoint",
    "DONE_STATUSES",
]

#: Status values that count as finished work when no ``closed`` flag is set.
DONE_STATUSES: frozenset[str] = frozenset({"done", "closed", "shipped", "complete"})


def _parse_date(value: str | None) -> date | None:
    """Parse an ISO-8601 date string, tolerating ``None`` and datetimes.

    Args:
        value: An ISO-8601 date or datetime string, or ``None``.

    Returns:
        The parsed :class:`datetime.date`, or ``None`` when ``value`` is falsy.

    Raises:
        ValueError: If ``value`` is a non-empty string that cannot be parsed.

    Example:
        >>> _parse_date("2026-08-10")
        datetime.date(2026, 8, 10)
        >>> _parse_date(None) is None
        True
    """
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Unparseable date: {value!r}") from exc


@dataclass(frozen=True)
class ProjectItem:
    """A single item on a GitHub Project board at a point in time.

    Attributes:
        item_id: The stable ``ProjectV2Item`` node ID.
        title: Issue, pull request, or draft title.
        url: Web URL of the underlying issue or PR; empty for draft items.
        status: Value of the board's ``Status`` field, e.g. ``"In Progress"``.
        iteration: Title of the iteration the item is assigned to, if any.
        iteration_start: First day of that iteration.
        iteration_duration: Length of the iteration in days.
        points: Numeric estimate read from the configured points field.
        origin: Value of the ``Origin`` field: ``Planned``, ``Unplanned``, or
            ``Carryover``.
        closed: Whether the underlying issue or PR is closed.
        closed_at: When the item was closed, if it has been.
        milestone: Milestone title, used as the project/release grouping.
        repository: ``owner/name`` of the item's repository.

    Example:
        >>> ProjectItem(item_id="a", title="t", points=3.0).points
        3.0
    """

    item_id: str
    title: str
    url: str = ""
    status: str = ""
    iteration: str | None = None
    iteration_start: date | None = None
    iteration_duration: int | None = None
    points: float | None = None
    origin: str | None = None
    closed: bool = False
    closed_at: date | None = None
    milestone: str | None = None
    repository: str = ""

    @property
    def is_complete(self) -> bool:
        """Whether this item counts as finished.

        An item is complete if its underlying issue is closed *or* its board
        status is one of :data:`DONE_STATUSES`. Checking both means the report
        stays correct whether the team closes issues or only moves cards.

        Returns:
            ``True`` when the item should count toward completed points.

        Example:
            >>> ProjectItem(item_id="a", title="t", status="Done").is_complete
            True
        """
        return self.closed or self.status.strip().lower() in DONE_STATUSES

    @property
    def effective_points(self) -> float:
        """Points for this item, treating an unset estimate as zero.

        Returns:
            The item's estimate, or ``0.0`` when no estimate has been set.

        Example:
            >>> ProjectItem(item_id="a", title="t").effective_points
            0.0
        """
        return float(self.points) if self.points is not None else 0.0

    @property
    def iteration_end(self) -> date | None:
        """Last day of the item's iteration.

        Returns:
            The inclusive final day of the iteration, or ``None`` when the item
            has no iteration or no known duration.

        Example:
            >>> from datetime import date
            >>> ProjectItem(
            ...     item_id="a", title="t", iteration="S1",
            ...     iteration_start=date(2026, 8, 10), iteration_duration=14,
            ... ).iteration_end
            datetime.date(2026, 8, 23)
        """
        if self.iteration_start is None or self.iteration_duration is None:
            return None
        from datetime import timedelta

        return self.iteration_start + timedelta(days=self.iteration_duration - 1)

    def to_json(self) -> dict[str, Any]:
        """Serialise the item to a JSON-compatible dictionary.

        Returns:
            A dict with ``date`` fields rendered as ISO-8601 strings.

        Example:
            >>> ProjectItem(item_id="a", title="t").to_json()["item_id"]
            'a'
        """
        payload = asdict(self)
        for key in ("iteration_start", "closed_at"):
            value = payload[key]
            payload[key] = value.isoformat() if value else None
        return payload

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> ProjectItem:
        """Rebuild an item from :meth:`to_json` output.

        Args:
            payload: A dictionary previously produced by :meth:`to_json`.

        Returns:
            The reconstructed :class:`ProjectItem`.

        Raises:
            KeyError: If ``payload`` is missing required keys.

        Example:
            >>> ProjectItem.from_json({"item_id": "a", "title": "t"}).title
            't'
        """
        data = dict(payload)
        data["iteration_start"] = _parse_date(data.get("iteration_start"))
        data["closed_at"] = _parse_date(data.get("closed_at"))
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass(frozen=True)
class Snapshot:
    """The full state of a project board on one calendar day.

    Attributes:
        captured_on: The day this snapshot represents.
        project_title: Board title, recorded for provenance.
        items: Every item on the board at capture time.

    Example:
        >>> from datetime import date
        >>> Snapshot(date(2026, 8, 21), "NXT", []).item_count
        0
    """

    captured_on: date
    project_title: str
    items: Sequence[ProjectItem] = field(default_factory=tuple)

    @property
    def item_count(self) -> int:
        """Number of items captured.

        Returns:
            The length of :attr:`items`.

        Example:
            >>> from datetime import date
            >>> Snapshot(date(2026, 8, 21), "NXT", []).item_count
            0
        """
        return len(self.items)

    def for_iteration(self, iteration: str) -> list[ProjectItem]:
        """Filter the snapshot down to one iteration.

        Args:
            iteration: The iteration title to match exactly.

        Returns:
            Every item assigned to that iteration.

        Example:
            >>> from datetime import date
            >>> snap = Snapshot(date(2026, 8, 21), "NXT", [
            ...     ProjectItem(item_id="a", title="t", iteration="S1"),
            ... ])
            >>> len(snap.for_iteration("S1"))
            1
        """
        return [item for item in self.items if item.iteration == iteration]

    def to_json(self) -> dict[str, Any]:
        """Serialise the snapshot to a JSON-compatible dictionary.

        Returns:
            A dict suitable for :func:`json.dump`.

        Example:
            >>> from datetime import date
            >>> Snapshot(date(2026, 8, 21), "NXT", []).to_json()["captured_on"]
            '2026-08-21'
        """
        return {
            "captured_on": self.captured_on.isoformat(),
            "project_title": self.project_title,
            "items": [item.to_json() for item in self.items],
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Snapshot:
        """Rebuild a snapshot from :meth:`to_json` output.

        Args:
            payload: A dictionary previously produced by :meth:`to_json`.

        Returns:
            The reconstructed :class:`Snapshot`.

        Raises:
            ValueError: If ``captured_on`` is missing or unparseable.

        Example:
            >>> Snapshot.from_json(
            ...     {"captured_on": "2026-08-21", "project_title": "NXT",
            ...      "items": []}
            ... ).project_title
            'NXT'
        """
        captured = _parse_date(payload.get("captured_on"))
        if captured is None:
            raise ValueError("Snapshot payload is missing 'captured_on'")
        return cls(
            captured_on=captured,
            project_title=payload.get("project_title", ""),
            items=[ProjectItem.from_json(raw) for raw in payload.get("items", [])],
        )


@dataclass(frozen=True)
class BurndownPoint:
    """One day on a sprint burndown curve.

    Attributes:
        day: The calendar day.
        remaining: Points still incomplete at end of day.
        ideal: Points that would remain under a linear ideal burn.

    Example:
        >>> from datetime import date
        >>> BurndownPoint(date(2026, 8, 10), 40.0, 40.0).remaining
        40.0
    """

    day: date
    remaining: float
    ideal: float


@dataclass(frozen=True)
class SprintMetrics:
    """Aggregate figures for a single iteration.

    Attributes:
        iteration: Iteration title.
        start: First day of the iteration.
        end: Last day of the iteration.
        committed_points: Total points assigned to the iteration.
        completed_points: Points on items that are complete.
        planned_points: Points where ``Origin`` is ``Planned``.
        unplanned_points: Points where ``Origin`` is ``Unplanned``.
        carryover_points: Points where ``Origin`` is ``Carryover``.
        unestimated_items: Count of items with no estimate set.
        total_items: Count of items in the iteration.
        completed_items: Count of complete items.

    Example:
        >>> SprintMetrics("S1", None, None, 40.0, 34.0).predictability
        85.0
    """

    iteration: str
    start: date | None = None
    end: date | None = None
    committed_points: float = 0.0
    completed_points: float = 0.0
    planned_points: float = 0.0
    unplanned_points: float = 0.0
    carryover_points: float = 0.0
    unestimated_items: int = 0
    total_items: int = 0
    completed_items: int = 0

    @property
    def predictability(self) -> float:
        """Completed points as a percentage of committed points.

        Returns:
            The ratio as a percentage rounded to one decimal, or ``0.0`` when
            nothing was committed.

        Example:
            >>> SprintMetrics("S1", None, None, 50.0, 40.0).predictability
            80.0
        """
        if self.committed_points <= 0:
            return 0.0
        return round(self.completed_points / self.committed_points * 100, 1)

    @property
    def unplanned_share(self) -> float:
        """Unplanned points as a percentage of committed points.

        Returns:
            The interrupt load as a percentage rounded to one decimal.

        Example:
            >>> SprintMetrics("S1", None, None, 40.0, 0.0,
            ...               unplanned_points=10.0).unplanned_share
            25.0
        """
        if self.committed_points <= 0:
            return 0.0
        return round(self.unplanned_points / self.committed_points * 100, 1)

    @property
    def remaining_points(self) -> float:
        """Points still outstanding in the iteration.

        Returns:
            Committed minus completed points, floored at zero.

        Example:
            >>> SprintMetrics("S1", None, None, 40.0, 34.0).remaining_points
            6.0
        """
        return max(self.committed_points - self.completed_points, 0.0)


def sum_points(items: Iterable[ProjectItem]) -> float:
    """Total the estimates across a collection of items.

    Args:
        items: Any iterable of project items.

    Returns:
        The sum of :attr:`ProjectItem.effective_points`.

    Example:
        >>> sum_points([ProjectItem(item_id="a", title="t", points=3.0)])
        3.0
    """
    return float(sum(item.effective_points for item in items))


def utc_today() -> date:
    """Return today's date in UTC.

    Kept as a named function so tests can monkeypatch the clock.

    Returns:
        The current UTC date.

    Example:
        >>> isinstance(utc_today(), date)
        True
    """
    return datetime.now(UTC).date()
