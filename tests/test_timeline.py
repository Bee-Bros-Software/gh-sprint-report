"""Tests for timeline history and cycle time."""

from __future__ import annotations

import json
import subprocess
from datetime import date

import pytest

from sprint_report.gh_source import GhError
from sprint_report.metrics import cycle_time_summary
from sprint_report.models import ProjectItem
from sprint_report.timeline import (
    IssueHistory,
    StatusEvent,
    fetch_status_events,
)


def history(number, created=None, closed=None, events=()):
    """Build an issue history.

    Args:
        number: Issue number.
        created: Creation date.
        closed: Closure date.
        events: Status transitions.

    Returns:
        A configured :class:`IssueHistory`.
    """
    return IssueHistory(
        number=str(number), created=created, closed=closed, events=list(events)
    )


class TestIssueHistory:
    """Derived dates on a single issue."""

    def test_started_is_first_working_transition(self):
        """Backlog time is queue time and must not count as cycle time."""
        item = history(
            1,
            created=date(2026, 7, 1),
            events=[
                StatusEvent(date(2026, 8, 10), "", "Todo"),
                StatusEvent(date(2026, 8, 14), "Todo", "In Progress"),
                StatusEvent(date(2026, 8, 18), "In Progress", "In Review"),
            ],
        )
        assert item.started == date(2026, 8, 14)

    def test_started_none_without_a_working_status(self):
        """An item that jumped straight to Done cannot be measured."""
        item = history(1, events=[StatusEvent(date(2026, 8, 10), "", "Done")])
        assert item.started is None

    def test_finished_prefers_closure(self):
        """The issue closing is the most reliable end point."""
        item = history(
            1,
            closed=date(2026, 8, 20),
            events=[StatusEvent(date(2026, 8, 14), "Todo", "In Progress")],
        )
        assert item.finished == date(2026, 8, 20)

    def test_finished_falls_back_to_done_status(self):
        """Work closed on the board only still has an end."""
        item = history(
            1,
            events=[
                StatusEvent(date(2026, 8, 14), "Todo", "In Progress"),
                StatusEvent(date(2026, 8, 19), "In Progress", "Done"),
            ],
        )
        assert item.finished == date(2026, 8, 19)

    def test_cycle_days(self):
        """Days between starting and finishing."""
        item = history(
            1,
            closed=date(2026, 8, 20),
            events=[StatusEvent(date(2026, 8, 14), "Todo", "In Progress")],
        )
        assert item.cycle_days == 6

    def test_cycle_days_none_when_open(self):
        """Unfinished work has no cycle time yet."""
        item = history(
            1, events=[StatusEvent(date(2026, 8, 14), "Todo", "In Progress")]
        )
        assert item.cycle_days is None

    def test_lead_time_includes_backlog(self):
        """Lead time is the other question: how long since it was raised."""
        item = history(
            1,
            created=date(2026, 7, 1),
            closed=date(2026, 8, 20),
            events=[StatusEvent(date(2026, 8, 14), "Todo", "In Progress")],
        )
        assert item.lead_days == 50
        assert item.cycle_days == 6

    def test_same_day_start_and_finish(self):
        """Work done in a day is zero, not negative."""
        item = history(
            1,
            closed=date(2026, 8, 14),
            events=[StatusEvent(date(2026, 8, 14), "Todo", "In Progress")],
        )
        assert item.cycle_days == 0


class TestFetch:
    """Parsing the GraphQL response."""

    PAYLOAD = {
        "data": {
            "repository": {
                "issues": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {
                            "number": 53,
                            "createdAt": "2026-08-01T09:00:00Z",
                            "closedAt": "2026-08-20T17:00:00Z",
                            "timelineItems": {
                                "nodes": [
                                    {
                                        "__typename": "AddedToProjectV2Event",
                                        "createdAt": "2026-08-10T11:54:03Z",
                                    },
                                    {
                                        "__typename": (
                                            "ProjectV2ItemStatusChangedEvent"
                                        ),
                                        "createdAt": "2026-08-10T11:54:04Z",
                                        "previousStatus": "",
                                        "status": "Todo",
                                    },
                                    {
                                        "__typename": (
                                            "ProjectV2ItemStatusChangedEvent"
                                        ),
                                        "createdAt": "2026-08-14T10:00:00Z",
                                        "previousStatus": "Todo",
                                        "status": "In Progress",
                                    },
                                ]
                            },
                        }
                    ],
                }
            }
        }
    }

    def _run(self, monkeypatch, payload):
        """Stub the gh call.

        Args:
            monkeypatch: pytest monkeypatch fixture.
            payload: Response body to return.
        """
        monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/gh")
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(
                a[0], 0, json.dumps(payload), ""
            ),
        )

    def test_parses_events(self, monkeypatch):
        """Status transitions and board membership both come through."""
        self._run(monkeypatch, self.PAYLOAD)
        result = fetch_status_events("acme/widgets")
        item = result["53"]
        assert item.added_to_board == date(2026, 8, 10)
        assert item.started == date(2026, 8, 14)
        assert item.closed == date(2026, 8, 20)
        assert item.cycle_days == 6

    def test_events_are_ordered(self, monkeypatch):
        """Transitions sort oldest first regardless of response order."""
        self._run(monkeypatch, self.PAYLOAD)
        events = fetch_status_events("acme/widgets")["53"].events
        assert [e.current for e in events] == ["Todo", "In Progress"]

    def test_bad_slug_rejected(self):
        """A malformed repository name fails before any call."""
        with pytest.raises(GhError, match="owner/name"):
            fetch_status_events("widgets")

    def test_missing_binary(self, monkeypatch):
        """No gh means no timeline."""
        monkeypatch.setattr("shutil.which", lambda _: None)
        with pytest.raises(GhError, match="not found"):
            fetch_status_events("acme/widgets")

    def test_failure_raises(self, monkeypatch):
        """A non-zero exit is reported."""
        monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/gh")
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "denied"),
        )
        with pytest.raises(GhError, match="denied"):
            fetch_status_events("acme/widgets")

    def test_empty_repository(self, monkeypatch):
        """No issues means no history, not an error."""
        self._run(
            monkeypatch,
            {"data": {"repository": {"issues": {"pageInfo": {}, "nodes": []}}}},
        )
        assert fetch_status_events("acme/widgets") == {}


class TestCycleTimeSummary:
    """Aggregation across a sprint."""

    def _items(self):
        """Three sprint items.

        Returns:
            Project items in Sprint 1.
        """
        return [
            ProjectItem(
                item_id=str(i), title=f"Item {i}", iteration="Sprint 1",
                status="Done", closed=True, points=5,
            )
            for i in (1, 2, 3)
        ]

    def _histories(self, days):
        """Build histories with given cycle lengths.

        Args:
            days: Mapping of item id to cycle length.

        Returns:
            A histories dict.
        """
        return {
            key: history(
                key,
                closed=date(2026, 8, 10) + __import__("datetime").timedelta(days=value),
                events=[StatusEvent(date(2026, 8, 10), "Todo", "In Progress")],
            )
            for key, value in days.items()
        }

    def test_median_of_odd_count(self):
        """The middle value, not the mean."""
        summary = cycle_time_summary(
            self._items(), self._histories({"1": 2, "2": 4, "3": 30})
        )
        assert summary["median"] == 4
        assert summary["count"] == 3

    def test_median_of_even_count(self):
        """Two middle values average."""
        items = self._items()[:2]
        summary = cycle_time_summary(items, self._histories({"1": 2, "2": 6}))
        assert summary["median"] == 4

    def test_longest_first(self):
        """The tail is where the process problem lives."""
        summary = cycle_time_summary(
            self._items(), self._histories({"1": 2, "2": 4, "3": 30})
        )
        assert summary["longest"][0][1] == 30

    def test_unmeasured_completed_items_counted(self):
        """Work that skipped In Progress is reported, not silently dropped."""
        summary = cycle_time_summary(self._items(), {})
        assert summary["count"] == 0
        assert summary["unmeasured"] == 3

    def test_iteration_filter(self):
        """Only the sprint under review is summarised."""
        items = self._items()
        other = ProjectItem(
            item_id="9", title="t", iteration="Sprint 2", status="Done", closed=True
        )
        summary = cycle_time_summary(
            [*items, other], self._histories({"1": 2, "9": 40}), "Sprint 1"
        )
        assert summary["count"] == 1

    def test_empty_input(self):
        """Nothing to summarise."""
        assert cycle_time_summary([], {})["median"] is None
