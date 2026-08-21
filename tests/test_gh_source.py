"""Tests for :mod:`sprint_report.gh_source`.

Uses a trimmed excerpt of a real ``gh project item-list`` export, so the
field-name and shape assumptions are checked against what gh actually emits.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from sprint_report.gh_source import (
    GhError,
    fetch,
    parse_export,
    summarise,
)

EXPORT = {
    "items": [
        {
            "id": "PVTI_a",
            "title": "PHI-access audit log",
            "status": "Done",
            "repository": "https://github.com/acme/widgets",
            "labels": ["security", "sprint-1"],
            "origin": "Planned",
            "sprint": {
                "duration": 14,
                "iterationId": "976e69b1",
                "startDate": "2026-08-10",
                "title": "Sprint 1",
            },
            "content": {
                "number": 48,
                "title": "PHI-access audit log",
                "type": "Issue",
                "url": "https://github.com/acme/widgets/issues/48",
            },
        },
        {
            "id": "PVTI_b",
            "title": "Vault infrastructure",
            "status": "In Progress",
            "points": 5,
            "origin": "Planned",
            "sprint": {
                "duration": 14,
                "iterationId": "976e69b1",
                "startDate": "2026-08-10",
                "title": "Sprint 1",
            },
            "content": {
                "number": 82,
                "title": "Vault infrastructure",
                "url": "https://github.com/acme/widgets/issues/82",
            },
        },
        {
            "id": "PVTI_c",
            "title": "Routes",
            "status": "Todo",
            "content": {
                "number": 21,
                "title": "Routes",
                "url": "https://github.com/acme/widgets/issues/21",
            },
        },
    ],
    "totalCount": 3,
}


class TestParseExport:
    """Mapping the gh JSON shape onto project items."""

    def test_parses_every_item(self):
        """All three rows survive the round trip."""
        assert len(parse_export(EXPORT)) == 3

    def test_uses_issue_number_as_identifier(self):
        """Item IDs are issue numbers, so links and tables read naturally."""
        assert [i.item_id for i in parse_export(EXPORT)] == ["48", "82", "21"]

    def test_reads_iteration_and_dates(self):
        """The sprint field supplies title, start, and duration."""
        item = parse_export(EXPORT)[0]
        assert item.iteration == "Sprint 1"
        assert item.iteration_start == date(2026, 8, 10)
        assert item.iteration_duration == 14
        assert item.iteration_end == date(2026, 8, 23)

    def test_missing_points_stay_none(self):
        """gh omits the key entirely when a field is unset."""
        assert parse_export(EXPORT)[0].points is None
        assert parse_export(EXPORT)[1].points == 5

    def test_status_done_marks_completion(self):
        """gh puts status at the top level, not inside field values."""
        items = parse_export(EXPORT)
        assert items[0].is_complete
        assert not items[1].is_complete

    def test_item_without_iteration(self):
        """A backlog row carries no sprint key at all."""
        assert parse_export(EXPORT)[2].iteration is None

    def test_accepts_a_json_string(self):
        """A pasted export can be passed as text."""
        assert len(parse_export(json.dumps(EXPORT))) == 3

    def test_accepts_a_path(self, tmp_path: Path):
        """A saved export can be passed as a file path."""
        target = tmp_path / "board.json"
        target.write_text(json.dumps(EXPORT), encoding="utf-8")
        assert len(parse_export(target)) == 3

    def test_invalid_json_raises(self):
        """A truncated paste fails with a clear message."""
        with pytest.raises(GhError, match="not valid JSON"):
            parse_export("{not json")

    def test_wrong_shape_raises(self):
        """Some other JSON document is rejected rather than silently empty."""
        with pytest.raises(GhError, match="no 'items' array"):
            parse_export({"data": []})

    def test_field_name_aliases(self):
        """Boards spelling the estimate field differently still parse."""
        for alias in ("points", "pts", "storypoints", "estimate"):
            payload = {"items": [{"id": "1", "title": "t", alias: 8}]}
            assert parse_export(payload)[0].points == 8

    def test_iteration_given_as_bare_string(self):
        """Some boards emit the iteration as a plain title."""
        payload = {"items": [{"id": "1", "title": "t", "sprint": "Sprint 3"}]}
        assert parse_export(payload)[0].iteration == "Sprint 3"

    def test_empty_export(self):
        """A board with no items yields no items, not an error."""
        assert parse_export({"items": []}) == []


class TestFetch:
    """Shelling out to gh."""

    def test_missing_binary_is_explained(self, monkeypatch):
        """An absent gh names the alternative rather than failing obscurely."""
        monkeypatch.setattr("shutil.which", lambda _: None)
        with pytest.raises(GhError, match="--from-export"):
            fetch("acme", 4)

    def test_successful_run_parses_stdout(self, monkeypatch):
        """A zero exit is parsed as an export."""
        monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/gh")
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(
                a[0], 0, stdout=json.dumps(EXPORT), stderr=""
            ),
        )
        assert len(fetch("acme", 4)) == 3

    def test_scope_error_suggests_the_fix(self, monkeypatch):
        """A missing project scope is the most likely first-run failure."""
        monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/gh")
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(
                a[0], 1, stdout="", stderr="missing required scope 'project'"
            ),
        )
        with pytest.raises(GhError, match="gh auth refresh -s project"):
            fetch("acme", 4)

    def test_timeout_is_reported(self, monkeypatch):
        """A hung gh does not hang the report."""
        monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/gh")

        def _timeout(*a, **k):
            raise subprocess.TimeoutExpired(a[0], 120)

        monkeypatch.setattr(subprocess, "run", _timeout)
        with pytest.raises(GhError, match="timed out"):
            fetch("acme", 4)

    def test_passes_owner_and_limit(self, monkeypatch):
        """The command is built with the org, number, and a raised limit."""
        monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/gh")
        seen: list[list[str]] = []

        def _run(cmd, **k):
            seen.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, json.dumps(EXPORT), "")

        monkeypatch.setattr(subprocess, "run", _run)
        fetch("acme", 4, limit=250)
        assert "--owner" in seen[0] and "acme" in seen[0]
        assert "250" in seen[0]


class TestSummarise:
    """The one-line run log."""

    def test_counts_sprinted_items(self):
        """The summary distinguishes board size from sprint size."""
        assert summarise(parse_export(EXPORT)) == "3 item(s), 2 in an iteration"
