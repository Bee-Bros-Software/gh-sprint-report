"""Shared pytest fixtures.

Provides a small synthetic board spanning three iterations, plus matching
snapshots, so metric and deck tests run without network access.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

import pytest

from sprint_report.models import ProjectItem, Snapshot

#: Start date of the sprint under test.
SPRINT_START = date(2026, 8, 10)


def make_item(
    ident: str,
    iteration: str,
    points: float | None,
    *,
    done: bool = False,
    origin: str = "Planned",
    start: date = SPRINT_START,
    milestone: str | None = None,
) -> ProjectItem:
    """Build a project item for tests.

    Args:
        ident: Unique item identifier.
        iteration: Iteration title.
        points: Estimate, or ``None`` for unestimated.
        done: Whether the item is complete.
        origin: Origin field value.
        start: Iteration start date.
        milestone: Optional milestone title.

    Returns:
        A configured :class:`~sprint_report.models.ProjectItem`.

    Example:
        >>> make_item("1", "Sprint 1", 5).points
        5
    """
    return ProjectItem(
        item_id=ident,
        title=f"Item {ident}",
        url=f"https://github.com/acme/repo/issues/{ident}",
        status="Done" if done else "In Progress",
        iteration=iteration,
        iteration_start=start,
        iteration_duration=14,
        points=points,
        origin=origin,
        closed=done,
        milestone=milestone,
    )


@pytest.fixture()
def board_items() -> list[ProjectItem]:
    """A three-sprint board with mixed origins and completion states.

    Returns:
        Ten items spanning Sprint 12, 13, and 14.
    """
    s12 = SPRINT_START - timedelta(days=28)
    s13 = SPRINT_START - timedelta(days=14)
    return [
        make_item("1", "Sprint 12", 5, done=True, start=s12),
        make_item("2", "Sprint 12", 8, done=True, start=s12),
        make_item("3", "Sprint 12", 3, start=s12),
        make_item("4", "Sprint 13", 8, done=True, start=s13),
        make_item("5", "Sprint 13", 5, done=True, start=s13, origin="Unplanned"),
        make_item("6", "Sprint 13", 3, start=s13, origin="Carryover"),
        make_item("7", "Sprint 14", 8, done=True, milestone="v2.0"),
        make_item("8", "Sprint 14", 5, origin="Unplanned", milestone="v2.0"),
        make_item("9", "Sprint 14", None, milestone="v2.0"),
        make_item("10", "Sprint 14", 3, done=True),
    ]


@pytest.fixture()
def snapshot_series(board_items: Sequence[ProjectItem]) -> list[Snapshot]:
    """Four days of snapshots for Sprint 14 with a shrinking remainder.

    Args:
        board_items: The synthetic board fixture.

    Returns:
        Snapshots for four consecutive days.
    """
    series: list[Snapshot] = []
    for offset, completed_ids in enumerate([set(), {"10"}, {"10"}, {"10", "7"}]):
        items: list[ProjectItem] = []
        for item in board_items:
            if item.iteration != "Sprint 14":
                items.append(item)
                continue
            done = item.item_id in completed_ids
            items.append(
                ProjectItem(
                    item_id=item.item_id,
                    title=item.title,
                    status="Done" if done else "In Progress",
                    iteration=item.iteration,
                    iteration_start=item.iteration_start,
                    iteration_duration=item.iteration_duration,
                    points=item.points,
                    origin=item.origin,
                    closed=done,
                    milestone=item.milestone,
                )
            )
        series.append(
            Snapshot(SPRINT_START + timedelta(days=offset), "Test Board", items)
        )
    return series
