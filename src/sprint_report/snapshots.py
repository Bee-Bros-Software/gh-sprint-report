"""Persistence for daily board snapshots.

GitHub Projects does not retain the history needed for an accurate burndown,
and moving an unfinished item to the next iteration retroactively rewrites the
previous sprint's totals. Capturing a snapshot each day fixes both problems:
every sprint keeps a record of what it actually looked like on each of its days.

Snapshots are stored one JSON file per day under a directory, named
``YYYY-MM-DD.json``. Re-running on the same day overwrites that day's file, so
the collector is safe to run more than once.

Example:
    >>> import tempfile
    >>> from datetime import date
    >>> from sprint_report.models import Snapshot
    >>> with tempfile.TemporaryDirectory() as tmp:
    ...     store = SnapshotStore(tmp)
    ...     path = store.write(Snapshot(date(2026, 8, 21), "NXT", []))
    ...     len(store.load_all())
    1
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import Snapshot

__all__ = ["SnapshotStore"]


class SnapshotStore:
    """Reads and writes dated board snapshots on the local filesystem.

    Args:
        directory: Directory holding the snapshot files. Created if absent.

    Example:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     SnapshotStore(tmp).load_all()
        []
    """

    def __init__(self, directory: str | Path) -> None:
        """Initialise the store, creating the directory if needed."""
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, snapshot: Snapshot) -> Path:
        """Return the file path a snapshot will be written to.

        Args:
            snapshot: The snapshot to locate.

        Returns:
            The full path, ``<directory>/<captured_on>.json``.

        Example:
            >>> import tempfile
            >>> from datetime import date
            >>> from sprint_report.models import Snapshot
            >>> with tempfile.TemporaryDirectory() as tmp:
            ...     p = SnapshotStore(tmp).path_for(
            ...         Snapshot(date(2026, 8, 21), "NXT", []))
            ...     p.name
            '2026-08-21.json'
        """
        return self.directory / f"{snapshot.captured_on.isoformat()}.json"

    def write(self, snapshot: Snapshot) -> Path:
        """Persist a snapshot, replacing any existing file for that day.

        Args:
            snapshot: The snapshot to write.

        Returns:
            The path written.

        Raises:
            OSError: If the file cannot be written.

        Example:
            >>> import tempfile
            >>> from datetime import date
            >>> from sprint_report.models import Snapshot
            >>> with tempfile.TemporaryDirectory() as tmp:
            ...     p = SnapshotStore(tmp).write(
            ...         Snapshot(date(2026, 8, 21), "NXT", []))
            ...     p.exists()
            True
        """
        target = self.path_for(snapshot)
        target.write_text(
            json.dumps(snapshot.to_json(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return target

    def load_all(self) -> list[Snapshot]:
        """Load every snapshot, oldest first.

        Files that cannot be parsed are skipped rather than aborting the run,
        so one corrupt day does not break reporting.

        Returns:
            All readable snapshots sorted by :attr:`Snapshot.captured_on`.

        Example:
            >>> import tempfile
            >>> with tempfile.TemporaryDirectory() as tmp:
            ...     SnapshotStore(tmp).load_all()
            []
        """
        snapshots: list[Snapshot] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                snapshots.append(Snapshot.from_json(payload))
            except (json.JSONDecodeError, ValueError, KeyError, OSError):
                continue
        return sorted(snapshots, key=lambda snap: snap.captured_on)

    def load_for_iteration(self, iteration: str) -> list[Snapshot]:
        """Load snapshots that contain at least one item in an iteration.

        Args:
            iteration: Iteration title to match.

        Returns:
            Matching snapshots, oldest first.

        Example:
            >>> import tempfile
            >>> with tempfile.TemporaryDirectory() as tmp:
            ...     SnapshotStore(tmp).load_for_iteration("Sprint 1")
            []
        """
        return [
            snapshot
            for snapshot in self.load_all()
            if any(item.iteration == iteration for item in snapshot.items)
        ]
