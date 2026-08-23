"""Read a project board through the ``gh`` CLI.

An alternative to :mod:`sprint_report.client` that shells out to
``gh project item-list`` instead of calling the GraphQL API directly. This
removes the fine-grained PAT from local use entirely — ``gh`` is already
authenticated on a developer machine.

``gh`` needs the ``project`` scope, which is not granted by default::

    gh auth refresh -s project

The JSON ``gh`` emits differs from the GraphQL shape: custom fields are
flattened onto the item as lowercased keys, and ``status`` sits at the top
level rather than inside ``fieldValues``. This module absorbs that difference
so the rest of the pipeline sees the same :class:`ProjectItem` either way.

Example:
    >>> items = fetch("acme", 4)  # doctest: +SKIP
    >>> len(items)  # doctest: +SKIP
    51
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .models import ProjectItem, _parse_date

__all__ = [
    "fetch",
    "fetch_issues",
    "fetch_project_title",
    "parse_export",
    "GhError",
    "FIELD_ALIASES",
]

#: Accepted key spellings for each logical field. ``gh`` lowercases custom
#: field names and strips punctuation, so a board field called "Pts",
#: "Points", or "Story Points" arrives differently depending on the board.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "points": ("points", "pts", "storypoints", "story points", "estimate"),
    "origin": ("origin", "worktype", "work type"),
    "iteration": ("sprint", "iteration", "cycle"),
    "status": ("status",),
}

#: Default page size. ``gh`` caps at 30 without an explicit limit.
DEFAULT_LIMIT = 500


class GhError(RuntimeError):
    """Raised when the ``gh`` CLI is unavailable or returns a failure.

    Example:
        >>> raise GhError("gh not found")
        Traceback (most recent call last):
        ...
        sprint_report.gh_source.GhError: gh not found
    """


def _first(row: dict[str, Any], logical: str) -> Any:
    """Return a field's value under whichever alias the board uses.

    Args:
        row: One item from the ``gh`` export.
        logical: A key of :data:`FIELD_ALIASES`.

    Returns:
        The value, or ``None`` when no alias is present.

    Example:
        >>> _first({"pts": 5}, "points")
        5
    """
    for alias in FIELD_ALIASES[logical]:
        if alias in row:
            return row[alias]
        squashed = alias.replace(" ", "")
        if squashed in row:
            return row[squashed]
    return None


def _to_item(row: dict[str, Any]) -> ProjectItem | None:
    """Convert one exported row into a :class:`ProjectItem`.

    Args:
        row: One element of the export's ``items`` array.

    Returns:
        The parsed item, or ``None`` for a row carrying no content.

    Example:
        >>> _to_item({"id": "1", "title": "t"}).title
        't'
    """
    content = row.get("content") or {}
    if not content and not row.get("title"):
        return None

    iteration = _first(row, "iteration") or {}
    if isinstance(iteration, str):
        iteration = {"title": iteration}

    points = _first(row, "points")
    status = str(_first(row, "status") or "")
    number = content.get("number")
    identifier = str(number) if number is not None else str(row.get("id", ""))

    return ProjectItem(
        item_id=identifier,
        title=str(content.get("title") or row.get("title") or ""),
        url=str(content.get("url", "")),
        status=status,
        iteration=iteration.get("title"),
        iteration_start=_parse_date(iteration.get("startDate")),
        iteration_duration=iteration.get("duration"),
        points=float(points) if isinstance(points, (int, float)) else None,
        origin=_first(row, "origin"),
        closed=status.strip().lower() == "done",
        milestone=(content.get("milestone") or {}).get("title")
        if isinstance(content.get("milestone"), dict)
        else content.get("milestone"),
        repository=str(row.get("repository") or content.get("repository") or ""),
    )


def parse_export(payload: dict[str, Any] | str | Path) -> list[ProjectItem]:
    """Parse a ``gh project item-list --format json`` export.

    Accepts the decoded object, a JSON string, or a path to a file — so the
    same function serves both the shell-out path and a pasted export.

    Args:
        payload: The export as a dict, a JSON string, or a file path.

    Returns:
        Every readable item.

    Raises:
        GhError: If the payload is not valid JSON or has no ``items`` array.

    Example:
        >>> parse_export({"items": [{"id": "1", "title": "t"}]})[0].title
        't'
    """
    if isinstance(payload, Path):
        payload = payload.read_text(encoding="utf-8")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise GhError(f"Export is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or "items" not in payload:
        raise GhError("Export has no 'items' array — is this a gh project export?")

    items: list[ProjectItem] = []
    for row in payload.get("items") or []:
        parsed = _to_item(row)
        if parsed is not None:
            items.append(parsed)
    return items


def fetch(
    org: str,
    number: int,
    limit: int = DEFAULT_LIMIT,
    gh_path: str | None = None,
) -> list[ProjectItem]:
    """Fetch a board by shelling out to ``gh``.

    Args:
        org: Organization login, e.g. ``"acme"``.
        number: Project board number.
        limit: Maximum items to request.
        gh_path: Explicit path to the ``gh`` binary; resolved from ``PATH``
            when omitted.

    Returns:
        Every item on the board.

    Raises:
        GhError: If ``gh`` is missing, unauthenticated, lacks the ``project``
            scope, or returns a non-zero exit.

    Example:
        >>> fetch("acme", 4)  # doctest: +SKIP
        [ProjectItem(...), ...]
    """
    binary = gh_path or shutil.which("gh")
    if not binary:
        raise GhError(
            "The gh CLI was not found on PATH. Install it, or pass an export "
            "with --from-export."
        )

    command = [
        binary,
        "project",
        "item-list",
        str(number),
        "--owner",
        org,
        "--format",
        "json",
        "--limit",
        str(limit),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=120, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise GhError("gh timed out after 120s") from exc
    except OSError as exc:
        raise GhError(f"Could not run gh: {exc}") from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        if "scope" in stderr.lower() or "project" in stderr.lower():
            stderr += "\n\nThe gh token may lack the 'project' scope. Run:\n"
            stderr += "    gh auth refresh -s project"
        raise GhError(f"gh exited {result.returncode}: {stderr[:500]}")

    return parse_export(result.stdout)


def summarise(items: Iterable[ProjectItem]) -> str:
    """Describe a fetched board in one line, for run logs.

    Args:
        items: The parsed items.

    Returns:
        A short human-readable summary.

    Example:
        >>> summarise([ProjectItem(item_id="1", title="t", iteration="S1")])
        '1 item(s), 1 in an iteration'
    """
    materialised = list(items)
    sprinted = sum(1 for item in materialised if item.iteration)
    return f"{len(materialised)} item(s), {sprinted} in an iteration"


def fetch_issues(
    repo: str,
    since: str,
    limit: int = 500,
    gh_path: str | None = None,
) -> list[dict[str, Any]]:
    """List issues in a repository updated since a date.

    Used to find work that happened outside the project board entirely — an
    issue nobody added to the board is invisible to every board-derived
    report, which is exactly the gap worth surfacing.

    Args:
        repo: ``owner/name`` of the repository.
        since: ISO date; issues updated on or after this are returned.
        limit: Maximum issues to request.
        gh_path: Explicit path to the ``gh`` binary.

    Returns:
        Raw issue dictionaries carrying ``number``, ``title``, ``url``,
        ``state``, ``updatedAt``, and ``assignees``.

    Raises:
        GhError: If ``gh`` is missing or the call fails.

    Example:
        >>> fetch_issues("acme/widgets", "2026-08-10")  # doctest: +SKIP
        [{'number': 21, ...}]
    """
    binary = gh_path or shutil.which("gh")
    if not binary:
        raise GhError("The gh CLI was not found on PATH.")

    command = [
        binary,
        "issue",
        "list",
        "--repo",
        repo,
        "--state",
        "all",
        "--limit",
        str(limit),
        "--search",
        f"updated:>={since}",
        "--json",
        "number,title,url,state,updatedAt,assignees",
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=120, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise GhError("gh issue list timed out after 120s") from exc
    except OSError as exc:
        raise GhError(f"Could not run gh: {exc}") from exc

    if result.returncode != 0:
        raise GhError(
            f"gh issue list exited {result.returncode}: "
            f"{(result.stderr or '').strip()[:400]}"
        )

    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise GhError(f"gh issue list returned invalid JSON: {exc}") from exc
    return list(payload)


def fetch_project_title(
    org: str, number: int, gh_path: str | None = None
) -> str:
    """Read a board's display title.

    ``gh project item-list`` does not carry the board name, so without this
    the deck falls back to the organisation slug — which is lowercase and
    reads poorly on a title slide.

    Args:
        org: Organization login.
        number: Project board number.
        gh_path: Explicit path to the ``gh`` binary.

    Returns:
        The board title, or an empty string if it cannot be read. A missing
        title is cosmetic, so this never raises.

    Example:
        >>> fetch_project_title("acme", 4)  # doctest: +SKIP
        'Delivery'
    """
    binary = gh_path or shutil.which("gh")
    if not binary:
        return ""
    try:
        result = subprocess.run(
            [binary, "project", "view", str(number), "--owner", org,
             "--format", "json"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            return ""
        return str(json.loads(result.stdout or "{}").get("title", ""))
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
        return ""
