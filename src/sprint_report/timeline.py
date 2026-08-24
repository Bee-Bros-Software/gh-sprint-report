"""Issue timeline events, for history GitHub does retain.

Projects v2 exposes no changelog for custom field values, but the issue
timeline does carry ``ProjectV2ItemStatusChangedEvent`` with both the previous
and new status, and ``AddedToProjectV2Event`` for board membership. Both are
available retroactively, which means cycle time and time-in-state can be
computed for work that finished long before any collector was running.

Example:
    >>> events = fetch_status_events("acme/widgets")  # doctest: +SKIP
    >>> events["82"].started  # doctest: +SKIP
    datetime.date(2026, 8, 14)
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .gh_source import GhError
from .models import _parse_date

__all__ = [
    "IssueHistory",
    "StatusEvent",
    "fetch_status_events",
    "WORKING_STATUSES",
    "DONE_STATUSES",
]

#: Statuses that mean work is actively underway. The first transition into any
#: of these is treated as the moment work started, which is a truer basis for
#: cycle time than issue creation — creation includes however long the item sat
#: in a backlog, which is queue time, not work.
WORKING_STATUSES: frozenset[str] = frozenset(
    {"in progress", "in review", "review", "doing", "started", "active"}
)

#: Statuses that mean work has finished.
DONE_STATUSES: frozenset[str] = frozenset({"done", "closed", "shipped", "complete"})

_QUERY = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    issues(first: 50, after: $after, states: [OPEN, CLOSED]) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        createdAt
        closedAt
        timelineItems(
          first: 100,
          itemTypes: [
            PROJECT_V2_ITEM_STATUS_CHANGED_EVENT,
            ADDED_TO_PROJECT_V2_EVENT
          ]
        ) {
          nodes {
            __typename
            ... on ProjectV2ItemStatusChangedEvent {
              createdAt
              previousStatus
              status
            }
            ... on AddedToProjectV2Event { createdAt }
          }
        }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class StatusEvent:
    """One status transition on an issue.

    Attributes:
        when: The day the transition happened.
        previous: Status before the change; empty on the first transition.
        current: Status after the change.

    Example:
        >>> StatusEvent(date(2026, 8, 14), "Todo", "In Progress").current
        'In Progress'
    """

    when: date
    previous: str
    current: str


@dataclass(frozen=True)
class IssueHistory:
    """What the timeline knows about one issue.

    Attributes:
        number: Issue number, as a string, matching ``ProjectItem.item_id``.
        created: When the issue was opened.
        closed: When it was closed, if it has been.
        added_to_board: When it first joined a project board.
        events: Status transitions, oldest first.

    Example:
        >>> IssueHistory("82", date(2026, 8, 1)).cycle_days is None
        True
    """

    number: str
    created: date | None = None
    closed: date | None = None
    added_to_board: date | None = None
    events: Sequence[StatusEvent] = field(default_factory=tuple)

    @property
    def started(self) -> date | None:
        """When work actually began.

        Returns:
            The day of the first transition into a working status, or
            ``None`` if the issue never entered one.

        Example:
            >>> IssueHistory("1").started is None
            True
        """
        for event in self.events:
            if event.current.strip().lower() in WORKING_STATUSES:
                return event.when
        return None

    @property
    def finished(self) -> date | None:
        """When work finished.

        Prefers the issue's closure date, falling back to the first
        transition into a done status for work closed on the board only.

        Returns:
            The finishing day, or ``None`` if still open.

        Example:
            >>> IssueHistory("1").finished is None
            True
        """
        if self.closed:
            return self.closed
        for event in self.events:
            if event.current.strip().lower() in DONE_STATUSES:
                return event.when
        return None

    @property
    def cycle_days(self) -> int | None:
        """Days from work starting to work finishing.

        Deliberately excludes time spent in a backlog: that is queue time,
        and mixing it into cycle time makes a fast team with a big backlog
        look slow.

        Returns:
            Whole days, minimum zero, or ``None`` when either end is unknown.

        Example:
            >>> IssueHistory("1").cycle_days is None
            True
        """
        start, end = self.started, self.finished
        if start is None or end is None:
            return None
        return max((end - start).days, 0)

    @property
    def lead_days(self) -> int | None:
        """Days from the issue being opened to being finished.

        Returns:
            Whole days, or ``None`` when either end is unknown.

        Example:
            >>> IssueHistory("1").lead_days is None
            True
        """
        if self.created is None or self.finished is None:
            return None
        return max((self.finished - self.created).days, 0)


def _parse_issue(node: dict[str, Any]) -> IssueHistory:
    """Convert one issue node into an :class:`IssueHistory`.

    Args:
        node: An element of the ``issues.nodes`` array.

    Returns:
        The parsed history.

    Example:
        >>> _parse_issue({"number": 1}).number
        '1'
    """
    events: list[StatusEvent] = []
    added: date | None = None

    for raw in (node.get("timelineItems") or {}).get("nodes") or []:
        when = _parse_date(raw.get("createdAt"))
        if when is None:
            continue
        if raw.get("__typename") == "AddedToProjectV2Event":
            if added is None or when < added:
                added = when
        elif raw.get("__typename") == "ProjectV2ItemStatusChangedEvent":
            events.append(
                StatusEvent(
                    when=when,
                    previous=str(raw.get("previousStatus") or ""),
                    current=str(raw.get("status") or ""),
                )
            )

    events.sort(key=lambda event: event.when)
    return IssueHistory(
        number=str(node.get("number", "")),
        created=_parse_date(node.get("createdAt")),
        closed=_parse_date(node.get("closedAt")),
        added_to_board=added,
        events=events,
    )


def fetch_status_events(
    repo: str, gh_path: str | None = None, max_pages: int = 20
) -> dict[str, IssueHistory]:
    """Fetch timeline history for every issue in a repository.

    Args:
        repo: ``owner/name`` of the repository.
        gh_path: Explicit path to the ``gh`` binary.
        max_pages: Safety limit on pagination.

    Returns:
        A mapping of issue number to :class:`IssueHistory`.

    Raises:
        GhError: If ``gh`` is missing, the query fails, or the repository
            slug is malformed.

    Example:
        >>> fetch_status_events("acme/widgets")  # doctest: +SKIP
        {'82': IssueHistory(...)}
    """
    if repo.count("/") != 1:
        raise GhError(f"Expected owner/name, got {repo!r}")
    owner, name = repo.split("/")

    binary = gh_path or shutil.which("gh")
    if not binary:
        raise GhError("The gh CLI was not found on PATH.")

    histories: dict[str, IssueHistory] = {}
    cursor: str | None = None
    for _ in range(max_pages):
        command = [
            binary, "api", "graphql",
            "-f", f"query={_QUERY}",
            "-F", f"owner={owner}",
            "-F", f"name={name}",
        ]
        if cursor:
            command += ["-F", f"after={cursor}"]

        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=180, check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise GhError("gh api graphql timed out") from exc
        except OSError as exc:
            raise GhError(f"Could not run gh: {exc}") from exc

        if result.returncode != 0:
            raise GhError(
                f"gh api graphql exited {result.returncode}: "
                f"{(result.stderr or '').strip()[:400]}"
            )

        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise GhError(f"gh returned invalid JSON: {exc}") from exc

        issues = (
            ((payload.get("data") or {}).get("repository") or {}).get("issues") or {}
        )
        for node in issues.get("nodes") or []:
            history = _parse_issue(node)
            if history.number:
                histories[history.number] = history

        page = issues.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        cursor = page.get("endCursor")

    return histories
