r"""Command line interface.

Two commands:

``snapshot``
    Capture the current board state to the snapshot directory. Intended to run
    daily on a schedule so burndown history accumulates.

``report``
    Generate the sprint review deck for an iteration.

Example:
    .. code-block:: console

        $ sprint-report snapshot --org your-org --project 4
        $ sprint-report report --org your-org --project 4 \\
              --iteration current --output review.pptx
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from .client import FieldMapping, GitHubApiError, ProjectsClient
from .deck import DeckBuilder
from .gh_source import GhError, fetch_issues, parse_export
from .gh_source import fetch as gh_fetch
from .graph import GraphError, GraphUploader
from .metrics import (
    burndown,
    carryover_items,
    iteration_metrics,
    iteration_titles,
    milestone_remaining,
    velocity_series,
)
from .models import ProjectItem, Snapshot, SprintMetrics, utc_today
from .snapshots import SnapshotStore
from .workbook import OffSprintIssue, build_workbook

__all__ = ["main", "build_parser"]

#: Environment variable read for the API token when ``--token`` is omitted.
TOKEN_ENV_VAR = "GITHUB_PROJECTS_TOKEN"

#: Environment variables holding Entra ID app-registration credentials.
GRAPH_TENANT_ENV_VAR = "GRAPH_TENANT_ID"
GRAPH_CLIENT_ENV_VAR = "GRAPH_CLIENT_ID"
GRAPH_SECRET_ENV_VAR = "GRAPH_CLIENT_SECRET"


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser.

    Returns:
        A configured :class:`argparse.ArgumentParser`.

    Example:
        >>> build_parser().prog
        'sprint-report'
    """
    parser = argparse.ArgumentParser(
        prog="sprint-report",
        description="Sprint reporting for GitHub Projects boards.",
    )
    parser.add_argument(
        "--token",
        default=None,
        help=f"GitHub token with Projects read access. Defaults to ${TOKEN_ENV_VAR}.",
    )
    parser.add_argument(
        "--org", default=None, help="GitHub organization login."
    )
    parser.add_argument(
        "--project", default=None, type=int, help="Project board number."
    )
    parser.add_argument(
        "--snapshots",
        default="snapshots",
        help="Directory holding daily snapshots (default: ./snapshots).",
    )
    parser.add_argument(
        "--source",
        choices=("gh", "api"),
        default="gh",
        help=(
            "Where to read the board. 'gh' shells out to the gh CLI and needs "
            "no token (default). 'api' calls the GraphQL API and needs "
            f"${TOKEN_ENV_VAR} — used by the scheduled workflow."
        ),
    )
    parser.add_argument(
        "--from-export",
        default=None,
        help=(
            "Read the board from a saved 'gh project item-list --format json' "
            "file instead of calling out. Overrides --source."
        ),
    )
    parser.add_argument("--points-field", default="Pts", help="Numeric estimate field.")
    parser.add_argument("--origin-field", default="Origin", help="Work origin field.")
    parser.add_argument("--status-field", default="Status", help="Status field.")
    parser.add_argument("--iteration-field", default="Sprint", help="Iteration field.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("snapshot", help="Capture today's board state.")

    report = subparsers.add_parser("report", help="Generate the sprint review deck.")
    report.add_argument(
        "--iteration",
        default="current",
        help="Iteration title, or 'current' for the latest (default: current).",
    )
    report.add_argument(
        "--output",
        default="sprint-review.pptx",
        help="Output .pptx path (default: ./sprint-review.pptx).",
    )
    report.add_argument(
        "--history",
        type=int,
        default=6,
        help="How many prior sprints to chart (default: 6).",
    )
    report.add_argument(
        "--subtitle", default="", help="Optional subtitle for the title slide."
    )
    report.add_argument(
        "--mode",
        choices=("review", "midsprint", "auto"),
        default="auto",
        help=(
            "Deck flavour. 'auto' picks midsprint when today falls inside the "
            "iteration and review when it does not (default: auto)."
        ),
    )
    report.add_argument(
        "--xlsx",
        default=None,
        help=(
            "Also write a follow-up workbook: unestimated sprint items, and "
            "issues worked on outside the sprint."
        ),
    )
    report.add_argument(
        "--issues-repo",
        action="append",
        default=None,
        metavar="OWNER/NAME",
        help=(
            "Repository to scan for issues worked on but never added to the "
            "board. Repeatable. Defaults to the repositories already on the "
            "board."
        ),
    )
    report.add_argument(
        "--summary-json",
        default=None,
        help=(
            "Also write the computed figures to this path as JSON, for "
            "downstream narration or alerting."
        ),
    )

    upload = report.add_argument_group(
        "upload",
        "Deliver the deck to SharePoint or OneDrive via Microsoft Graph. "
        "Credentials come from $GRAPH_TENANT_ID, $GRAPH_CLIENT_ID, and "
        "$GRAPH_CLIENT_SECRET.",
    )
    upload.add_argument(
        "--sharepoint-host",
        default=None,
        help="SharePoint hostname, e.g. contoso.sharepoint.com.",
    )
    upload.add_argument(
        "--sharepoint-site",
        default=None,
        help="Server-relative site path, e.g. /sites/Engineering.",
    )
    upload.add_argument(
        "--onedrive-user",
        default=None,
        help="UPN of the OneDrive owner. Mutually exclusive with SharePoint.",
    )
    upload.add_argument(
        "--upload-folder",
        default="Sprint Reviews",
        help="Destination folder (default: 'Sprint Reviews').",
    )
    upload.add_argument(
        "--upload-name",
        default=None,
        help="Remote filename. Defaults to '<iteration> Review.pptx'.",
    )
    return parser


def _resolve_token(explicit: str | None) -> str:
    """Resolve the API token from the flag or environment.

    Args:
        explicit: Value passed via ``--token``, if any.

    Returns:
        The token string.

    Raises:
        SystemExit: If no token is available.

    Example:
        >>> _resolve_token("abc")
        'abc'
    """
    token = explicit or os.environ.get(TOKEN_ENV_VAR, "")
    if not token:
        raise SystemExit(
            f"No token supplied. Pass --token or set ${TOKEN_ENV_VAR}. "
            "Note that the Actions GITHUB_TOKEN lacks Projects scope."
        )
    return token


def _make_client(args: argparse.Namespace) -> ProjectsClient:
    """Build a configured API client from parsed arguments.

    Args:
        args: Parsed command line arguments.

    Returns:
        A ready :class:`ProjectsClient`.

    Raises:
        SystemExit: If no token is available.
    """
    return ProjectsClient(
        token=_resolve_token(args.token),
        fields=FieldMapping(
            points=args.points_field,
            origin=args.origin_field,
            status=args.status_field,
            iteration=args.iteration_field,
        ),
    )


def _pick_iteration(items: Sequence[ProjectItem], requested: str) -> str:
    """Choose which iteration to report on.

    Args:
        items: All board items.
        requested: An iteration title, or ``"current"``.

    Returns:
        The resolved iteration title.

    Raises:
        SystemExit: If the board has no iterations, or the requested one is
            not present.

    Example:
        >>> _pick_iteration(
        ...     [ProjectItem(item_id="a", title="t", iteration="S1")], "S1")
        'S1'
    """
    titles = iteration_titles(items)
    if not titles:
        raise SystemExit("No iterations found on this board.")
    if requested.lower() != "current":
        if requested not in titles:
            raise SystemExit(
                f"Iteration {requested!r} not found. Available: {', '.join(titles)}"
            )
        return requested

    today = utc_today()
    for title in titles:
        scoped = [item for item in items if item.iteration == title]
        start = next((i.iteration_start for i in scoped if i.iteration_start), None)
        end = next((i.iteration_end for i in scoped if i.iteration_end), None)
        if start and end and start <= today <= end:
            return title
    return titles[-1]


def _run_snapshot(args: argparse.Namespace) -> int:
    """Execute the ``snapshot`` command.

    Args:
        args: Parsed command line arguments.

    Returns:
        A process exit code.
    """
    title, items = _load_board(args)

    store = SnapshotStore(args.snapshots)
    path = store.write(Snapshot(utc_today(), title, items))
    print(f"Captured {len(items)} item(s) from {title!r} to {path}")
    return 0


def _make_uploader() -> GraphUploader:
    """Build a Graph uploader from environment credentials.

    Returns:
        A configured :class:`GraphUploader`.

    Raises:
        SystemExit: If any credential is missing from the environment.

    Example:
        >>> _make_uploader()  # doctest: +SKIP
        <sprint_report.graph.GraphUploader object at ...>
    """
    tenant = os.environ.get(GRAPH_TENANT_ENV_VAR, "")
    client = os.environ.get(GRAPH_CLIENT_ENV_VAR, "")
    secret = os.environ.get(GRAPH_SECRET_ENV_VAR, "")
    missing = [
        name
        for name, value in (
            (GRAPH_TENANT_ENV_VAR, tenant),
            (GRAPH_CLIENT_ENV_VAR, client),
            (GRAPH_SECRET_ENV_VAR, secret),
        )
        if not value
    ]
    if missing:
        raise SystemExit(
            "Upload requested but these environment variables are unset: "
            + ", ".join(missing)
        )
    return GraphUploader(tenant, client, secret)


def _deliver(args: argparse.Namespace, output: Path, iteration: str) -> None:
    """Upload the deck when a destination was requested.

    Args:
        args: Parsed command line arguments.
        output: The generated deck.
        iteration: Iteration title, used for the default remote filename.

    Raises:
        SystemExit: If both SharePoint and OneDrive destinations are given, or
            SharePoint is only half-specified, or credentials are missing.
    """
    wants_sharepoint = bool(args.sharepoint_host or args.sharepoint_site)
    wants_onedrive = bool(args.onedrive_user)

    if not wants_sharepoint and not wants_onedrive:
        return
    if wants_sharepoint and wants_onedrive:
        raise SystemExit(
            "Choose either --sharepoint-host/--sharepoint-site or "
            "--onedrive-user, not both."
        )
    if wants_sharepoint and not (args.sharepoint_host and args.sharepoint_site):
        raise SystemExit(
            "--sharepoint-host and --sharepoint-site must be given together."
        )

    remote_name = args.upload_name or f"{iteration} Review.pptx"
    uploader = _make_uploader()
    if wants_sharepoint:
        url = uploader.upload_to_site(
            args.sharepoint_host,
            args.sharepoint_site,
            args.upload_folder,
            output,
            remote_name,
        )
    else:
        url = uploader.upload_to_onedrive(
            args.onedrive_user, args.upload_folder, output, remote_name
        )
    print(f"Uploaded to {url or remote_name}")


def _load_board(args: argparse.Namespace) -> tuple[str, list[ProjectItem]]:
    """Read the board through whichever source was selected.

    Args:
        args: Parsed command line arguments.

    Returns:
        A tuple of board title and items. The title is empty for the ``gh``
        and export paths, which do not carry it.

    Raises:
        SystemExit: If required identifiers are missing for the chosen source.
        GhError: If the ``gh`` CLI fails.
        GitHubApiError: If the GraphQL API fails.

    Example:
        >>> _load_board(argparse.Namespace(  # doctest: +SKIP
        ...     from_export="board.json", source="gh"))
        ('', [...])
    """
    if args.from_export:
        return "", parse_export(Path(args.from_export))

    if not args.org or args.project is None:
        raise SystemExit(
            "--org and --project are required unless --from-export is given."
        )

    if args.source == "gh":
        return "", gh_fetch(args.org, args.project)

    client = _make_client(args)
    project_id = client.resolve_project_id(args.org, args.project)
    return client.fetch_items(project_id)


def _resolve_mode(requested: str, current: SprintMetrics) -> str:
    """Decide whether this is a mid-sprint check or an end-of-sprint review.

    Args:
        requested: The ``--mode`` value: ``review``, ``midsprint``, or ``auto``.
        current: Metrics for the sprint being reported on.

    Returns:
        Either ``"review"`` or ``"midsprint"``.

    Example:
        >>> _resolve_mode("review", SprintMetrics("S1"))
        'review'
    """
    if requested != "auto":
        return requested
    if current.start and current.end and current.start <= utc_today() <= current.end:
        return "midsprint"
    return "review"


def _summary_payload(
    current: SprintMetrics,
    mode: str,
    unestimated: Sequence[ProjectItem],
    unsprinted: Sequence[ProjectItem],
    carryover: Sequence[ProjectItem],
    has_burndown: bool,
) -> dict[str, object]:
    """Assemble the machine-readable summary of a report run.

    The deck is for humans; this is for whatever narrates or alerts on the
    run. It deliberately includes the data-quality counts, because a
    points-based figure computed over a half-estimated board is misleading
    and the consumer needs enough to say so.

    Args:
        current: Metrics for the sprint reported on.
        mode: Resolved deck mode.
        unestimated: Sprint items carrying no estimate.
        unsprinted: Board items outside every iteration.
        carryover: Incomplete items in the sprint.
        has_burndown: Whether snapshot history covered the sprint.

    Returns:
        A JSON-serialisable dictionary.

    Example:
        >>> _summary_payload(
        ...     SprintMetrics("S1"), "review", [], [], [], False
        ... )["iteration"]
        'S1'
    """
    estimate_coverage = (
        round((current.total_items - len(unestimated)) / current.total_items * 100, 1)
        if current.total_items
        else 0.0
    )
    return {
        "iteration": current.iteration,
        "mode": mode,
        "start": current.start.isoformat() if current.start else None,
        "end": current.end.isoformat() if current.end else None,
        "items": {
            "total": current.total_items,
            "complete": current.completed_items,
            "percent_complete": (
                round(current.completed_items / current.total_items * 100, 1)
                if current.total_items
                else 0.0
            ),
        },
        "points": {
            "committed": current.committed_points,
            "completed": current.completed_points,
            "remaining": current.remaining_points,
            "predictability_percent": current.predictability,
            "unplanned_percent": current.unplanned_share,
            "planned": current.planned_points,
            "unplanned": current.unplanned_points,
            "carryover": current.carryover_points,
        },
        "data_quality": {
            "unestimated_items": len(unestimated),
            "estimate_coverage_percent": estimate_coverage,
            "unsprinted_items": len(unsprinted),
            "origin_field_used": current.unplanned_points > 0
            or current.carryover_points > 0,
            "burndown_available": has_burndown,
        },
        "open_items": [
            {
                "id": item.item_id,
                "title": item.title,
                "points": item.effective_points,
                "status": item.status,
                "url": item.url,
            }
            for item in carryover
        ],
        "unestimated": [
            {"id": item.item_id, "title": item.title, "url": item.url}
            for item in unestimated
        ],
        "unsprinted": [
            {"id": item.item_id, "title": item.title, "status": item.status,
             "url": item.url}
            for item in unsprinted
        ],
    }


def _off_sprint_issues(
    args: argparse.Namespace,
    items: Sequence[ProjectItem],
    current: SprintMetrics,
) -> list[OffSprintIssue]:
    """Find work that happened outside the sprint.

    Two populations, both invisible to a board-derived report: items on the
    board carrying no iteration, and issues in the repositories that are not
    on the board at all. The second requires a repository query, which is
    skipped when ``gh`` is unavailable rather than failing the run.

    Args:
        args: Parsed command line arguments.
        items: Every board item.
        current: Metrics for the sprint, used for the date window.

    Returns:
        Off-sprint issues, board members first.

    Example:
        >>> _off_sprint_issues(  # doctest: +SKIP
        ...     args, items, metrics)
        [OffSprintIssue(...)]
    """
    records: list[OffSprintIssue] = []
    on_board_numbers: set[str] = {item.item_id for item in items}

    for item in items:
        if item.iteration is not None:
            continue
        if item.status.strip().lower() in ("", "todo", "backlog"):
            continue
        records.append(
            OffSprintIssue(
                number=item.item_id,
                title=item.title,
                url=item.url,
                state="closed" if item.is_complete else "open",
                updated="",
                assignees="",
                on_board=True,
            )
        )

    if not current.start:
        return records

    repos = args.issues_repo or sorted(
        {item.repository for item in items if item.repository}
    )
    since = current.start.isoformat()
    for repo in repos:
        slug = repo.replace("https://github.com/", "").strip("/")
        if slug.count("/") != 1:
            continue
        try:
            issues = fetch_issues(slug, since)
        except GhError as exc:
            print(f"Skipping {slug}: {exc}", file=sys.stderr)
            continue
        for issue in issues:
            number = str(issue.get("number", ""))
            if number in on_board_numbers:
                continue
            assignees = ", ".join(
                a.get("login", "") for a in issue.get("assignees") or []
            )
            records.append(
                OffSprintIssue(
                    number=number,
                    title=str(issue.get("title", "")),
                    url=str(issue.get("url", "")),
                    state=str(issue.get("state", "")).lower(),
                    updated=str(issue.get("updatedAt", ""))[:10],
                    assignees=assignees,
                    on_board=False,
                )
            )

    return records


def _run_report(args: argparse.Namespace) -> int:
    """Execute the ``report`` command.

    Args:
        args: Parsed command line arguments.

    Returns:
        A process exit code.
    """
    title, items = _load_board(args)

    iteration = _pick_iteration(items, args.iteration)
    current = iteration_metrics(items, iteration)

    series = velocity_series(items, limit=args.history + 1)
    history = [metric for metric in series if metric.iteration != iteration]

    store = SnapshotStore(args.snapshots)
    curve = burndown(store.load_all(), iteration)

    milestones = sorted({item.milestone for item in items if item.milestone})
    forecasts = [
        (name, milestone_remaining(items, name))
        for name in milestones
        if milestone_remaining(items, name) > 0
    ]

    mode = _resolve_mode(args.mode, current)
    sprint_items = [item for item in items if item.iteration == iteration]
    unestimated = [item for item in sprint_items if item.points is None]
    unsprinted = [item for item in items if item.iteration is None]
    open_items = carryover_items(items, iteration)

    output = DeckBuilder(
        project_title=title or args.org or "Sprint", subtitle=args.subtitle, mode=mode
    ).build(
        current=current,
        history=history,
        burndown_points=curve,
        carryover=open_items,
        output_path=Path(args.output),
        milestone_forecasts=forecasts,
        unestimated=unestimated,
        unsprinted=unsprinted,
    )
    print(f"Wrote {output}")

    if args.xlsx:
        off_sprint = _off_sprint_issues(args, items, current)
        workbook_path = build_workbook(
            Path(args.xlsx), iteration, unestimated, off_sprint
        )
        print(f"Wrote {workbook_path}")

    if args.summary_json:
        payload = _summary_payload(
            current, mode, unestimated, unsprinted, open_items, bool(curve)
        )
        summary_path = Path(args.summary_json)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(f"Wrote {summary_path}")
    _deliver(args, output, iteration)
    if not curve:
        print(
            "Note: no snapshots cover this sprint, so the burndown slide is "
            "empty. Run 'snapshot' daily to build history.",
            file=sys.stderr,
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Argument list; defaults to :data:`sys.argv` when ``None``.

    Returns:
        A process exit code: ``0`` on success, ``1`` on an API failure.

    Example:
        >>> main(["--help"])  # doctest: +SKIP
        0
    """
    args = build_parser().parse_args(argv)
    try:
        if args.command == "snapshot":
            return _run_snapshot(args)
        return _run_report(args)
    except GitHubApiError as exc:
        print(f"GitHub API error: {exc}", file=sys.stderr)
        return 1
    except GraphError as exc:
        print(f"Microsoft Graph error: {exc}", file=sys.stderr)
        return 1
    except GhError as exc:
        print(f"gh CLI error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
