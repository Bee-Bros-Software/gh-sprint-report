# gh-sprint-report

Sprint reports from a GitHub Projects board — a PowerPoint review deck and a
follow-up workbook, generated from the command line.

GitHub Projects has no burndown chart, no velocity chart, and no predictability
metric, and there is no way to configure around those gaps. This pulls the
board data out and builds the reports itself.

## What you get

**A review deck** (`.pptx`) with native, editable charts:

| Slide | Shows |
|---|---|
| Sprint at a glance | Completed points, predictability, unplanned share, rolling average |
| Burndown | Remaining points per day against a linear ideal |
| Delivery trend | Committed against completed per sprint — bar height is velocity, filled portion is predictability |
| Work mix | Both directions — where the work came from (planned, unplanned, carried in) and where it ended up (completed, rolling forward) |
| Rolling forward | Incomplete work moving to the next sprint, heaviest first |
| Forecast | Sprints remaining per milestone at current velocity |
| Unestimated items | Sprint items with no estimate, linked |
| Not in a sprint | Board items outside every iteration, linked |

Slides with nothing to say are omitted — a trend chart with one data point is
left out rather than shipped as a single bar in an empty plot.

**A follow-up workbook** (`.xlsx`), which is the actionable half:

- `Unestimated` — sprint items with no estimate. Each counts as zero points,
  so completed-point figures understate delivery until they are filled in.
- `Off Sprint` — work that appears in no report: board items with activity but
  no iteration, plus issues updated during the sprint that were never added to
  the board at all.

**A run summary** (`--summary-json`) carrying the figures plus data-quality
counts, so downstream tooling can tell when a number should not be trusted.

## Install

**Binary** — no Python needed. Download for your platform from
[Releases](../../releases).

```bash
chmod +x sprint-report-macos-arm64
xattr -d com.apple.quarantine sprint-report-macos-arm64   # macOS only, once
```

The macOS binaries are unsigned, so Gatekeeper blocks them until the
quarantine flag is cleared.

**pipx**

```bash
pipx install gh-sprint-report
```

## Setup

The default source is the GitHub CLI, which needs the `project` scope — not
granted by default:

```bash
gh auth refresh -s project
```

That is the whole setup. No personal access token.

## Use

```bash
sprint-report --org your-org --project 4 report \
  --iteration current \
  --output "Sprint Review.pptx" \
  --xlsx "Follow-ups.xlsx"
```

`--iteration current` picks the sprint spanning today, falling back to the
most recent. The deck flavour follows: a sprint still in flight gets a
mid-sprint check, a closed one gets a review.

### Daily snapshots

Burndown needs history, and GitHub keeps none. Worse, moving an unfinished
item to the next iteration retroactively removes its points from the sprint
that failed to finish it.

```bash
sprint-report --org your-org --project 4 --snapshots ./snapshots snapshot
```

Run it daily — cron, launchd, or a scheduled workflow. **History cannot be
backfilled**, so start before you need the chart. Until snapshots exist, the
burndown slide is omitted.

## Board requirements

| Field | Type | Purpose |
|---|---|---|
| Iteration | Iteration | Groups work into sprints, supplies dates |
| Status | Single select | `Done` marks completion when issues stay open |
| Points | **Number** | Estimate. Must be Number — a single select cannot be summed |
| Origin | Single select | Where the item came from: `Planned` (committed at planning), `Unplanned` (pulled in mid-sprint), `Carryover` (rolled in from the previous sprint) |

Only the iteration field is required. Everything else degrades gracefully:
without estimates you get item counts, without `Origin` the work mix is
reported as untracked rather than as zero.

Field names are matched loosely (`points`, `pts`, `story points`, `estimate`),
and overridable with `--points-field`, `--origin-field`, `--status-field`,
`--iteration-field`.

## Reading the board

| Source | Flag | Auth |
|---|---|---|
| `gh` CLI | default | `gh auth refresh -s project` |
| Saved export | `--from-export board.json` | none |
| GraphQL API | `--source api` | `GITHUB_PROJECTS_TOKEN` |

`--from-export` reads a `gh project item-list --format json` file, so one
person with access can share a snapshot and anyone can generate reports from
it. The API path exists for CI, where there is no user `gh` session to borrow.

## Delivering the output

Optionally upload to SharePoint or OneDrive through Microsoft Graph:

```bash
sprint-report --org your-org --project 4 report \
  --sharepoint-host contoso.sharepoint.com \
  --sharepoint-site /sites/Engineering \
  --upload-folder "Sprint Reviews"
```

Needs an Entra ID app registration. Prefer `Sites.Selected` scoped to the one
target site over the tenant-wide `Files.ReadWrite.All`.

## A note on velocity

Velocity is a planning input, not a performance metric. Points are team-local,
so cross-team comparison is meaningless, and the moment velocity is reported
upward it inflates — you lose the planning tool to gain a bad status metric.

If a number is going to an executive, prefer predictability, interrupt load,
and forecast dates. The tool computes all three.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). Google-style docstrings, PEP 484
hints, 95% docstring coverage enforced, tests for the failure paths, and a
Sphinx build with warnings as errors.

## Licence

MIT. See [LICENSE](LICENSE).
