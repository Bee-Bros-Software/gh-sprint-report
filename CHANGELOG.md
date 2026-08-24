# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.5.0] — 2026-08-23

### Added

- A **Cycle time** slide: median days from work starting to finishing, with
  the slowest items listed. Built from `ProjectV2ItemStatusChangedEvent` on
  the issue timeline, which GitHub retains — so it works **retroactively**,
  with no field to add and no collector to have been running.
- Measured from the first transition into a working status rather than from
  issue creation, so backlog queue time is excluded. Median rather than mean,
  because cycle times are right-skewed.
- `--summary-json` gains a `cycle_time` block.

### Fixed

- `ROADMAP.md` claimed GitHub Projects does not model dependencies. It does:
  `BlockingAddedEvent` is on the issue timeline, so critical path needs graph
  traversal rather than a hand-maintained convention. The suggested `Started`
  date field is also unnecessary — status transitions already carry it.

## [1.4.0] — 2026-08-23

### Added

- A **Scope churn** slide: what entered and left the sprint after it started,
  by day, with a net figure. Derived by diffing daily snapshots, since GitHub
  keeps no history of iteration-field changes. Appears only when snapshots
  cover the sprint.
- `ROADMAP.md`, documenting planned work and — more usefully — the board
  fields each feature needs recorded as work happens, since none of it can be
  backfilled.

## [1.3.1] — 2026-08-23

### Fixed

- The generation timestamp crashed on Windows. `%-d` is a glibc extension for
  a day number without a leading zero; Windows spells it `%#d` and rejects
  the other, so neither is portable. The day is now formatted from the
  integer, and a test scans the function for either directive.
- Console output and `--help` text are now ASCII. Windows terminals default
  to cp1252 and rendered em dashes as replacement characters.

## [1.3.0] — 2026-08-23

### Added

- A **Burnup** slide, drawn from the same daily data as the burndown. It is
  the framing that makes scope visible: a burndown flattening could mean work
  stalled or work being added, and only a burnup distinguishes them. Scope
  moves when the curve comes from snapshots and is flat when reconstructed
  from closure dates, which the sub-heading states.
- `BurndownPoint` carries `scope`, with `completed` derived from it, so the
  two framings are computed from one record and cannot disagree.

### Changed

- **Velocity** is a line chart again, on its own slide, with committed and
  completed as lines plus a flat recent-average reference. Direction over
  time reads better as a line than as columns; the delivered-against-
  commitment percentages remain beneath it.

## [1.2.1] — 2026-08-23

### Added

- Every deck records exactly when its data was read: a full local timestamp
  with timezone on the title slide, a small footer on every other slide, and
  the same details in the file's own document properties. A bare date could
  not distinguish two decks generated the same day from a board that changes
  hourly, and the footer means the stamp survives a slide being pasted
  somewhere else.

## [1.2.0] — 2026-08-23

### Added

- Velocity measured from closure dates, via `metrics.velocity_by_closure` and
  `metrics.throughput`, reported in `--summary-json` as
  `throughput_by_sprint`.

  This answers "how much closed during this sprint's dates" rather than "how
  much of what this sprint was assigned is now done", and is better in two
  ways. It is **stable**: moving an unfinished item into the next iteration
  retroactively removes its points from the sprint that failed to finish it,
  so assignment-based velocity for a past sprint changes after the fact,
  while a closure date does not move. And it is **complete**: work closed
  during a sprint but never assigned to it still consumed capacity.

## [1.1.1] — 2026-08-23

### Fixed

- Completed work was undercounted. `gh project item-list` returns the board's
  Status column but not the issue's own state, so an issue closed by a merged
  pull request and never dragged to Done counted as incomplete — depressing
  completed points, predictability, and the burndown. Issue state is now
  fetched and takes precedence, and the CLI reports how many items disagreed.

## [1.1.0] — 2026-08-23

### Added

- Burndown is now reconstructed from issue closure dates when no snapshots
  exist. GitHub retains `closedAt` on every closed issue, which is enough to
  derive remaining work per day — so a burndown appears for sprints that
  predate the collector, retroactively.
- The slide and stderr both state when a curve was reconstructed, because it
  cannot show mid-sprint scope changes: an item added on day five is counted
  from day one. Snapshots remain the accurate source.

## [1.0.6] — 2026-08-23

### Changed

- Work mix series are ordered chronologically, so both bars read left to
  right as a timeline: carried in, planned, unplanned — then completed and
  rolling forward.

## [1.0.5] — 2026-08-23

### Changed

- The work mix slide now shows both directions as two bars that sum to the
  same total: **Came from** (planned / unplanned / carried in) and **Went to**
  (completed / rolling forward). Showing one direction alone invited readers
  to supply the other from assumption.

### Added

- A first sprint cannot have work carried in. When points are marked as such
  with no earlier sprint on the board, the slide says so, the CLI warns on
  stderr, and `--summary-json` carries `data_quality.impossible_carry_in`.

## [1.0.4] — 2026-08-23

### Fixed

- "Carryover" no longer means two opposite things in one deck. The work mix
  series is now **Carried in** — work that rolled in from the previous sprint,
  read from the `Origin` field — and the incomplete-work slide is now
  **Rolling forward**, describing work moving to the next sprint. A test
  asserts the word is never reused.

## [1.0.3] — 2026-08-23

### Fixed

- The final day of a sprint now resolves to `review`, not `midsprint`. An
  inclusive end date meant a review held on the closing day was labelled a
  mid-sprint check.

### Changed

- The work mix slide no longer requires prior sprints. A single sprint's
  planned/unplanned/carryover split is a composition, not a trend, and is
  useful from the first sprint onward. With one sprint it renders as a
  horizontal stacked bar with in-bar labels rather than a lone column.

## [1.0.2] — 2026-08-21

### Changed

- Velocity and predictability are one slide, not two. Completed points per
  sprint *is* velocity, so the two charts were showing the same series; the
  merged "Delivery trend" slide carries both — bar height is velocity, filled
  proportion is predictability.
- Trend columns are fully overlapped rather than clustered, so each sprint
  reads as a single progress bar instead of a pair to compare by eye.

## [1.0.1] — 2026-08-21

### Fixed

- Future iterations are no longer charted as history. Iteration fields
  generate sprints forward, so a board almost always carries unstarted
  sprints; those were appearing in velocity, predictability, and work-mix
  charts as zero completed points, dragging the rolling average toward zero
  and reordering the current sprint to the end of the axis.
- The title slide uses the board's own name rather than the organisation
  slug. `--title` overrides it.

## [1.0.0] — 2026-08-21

First public release.

### Added

- Read a GitHub Projects v2 board through the `gh` CLI, the GraphQL API, or a
  saved `gh project item-list` export.
- PowerPoint sprint review deck with native, editable charts: burndown,
  velocity, predictability, work mix, carryover, forecast, and follow-up lists
  with clickable issue links.
- Follow-up workbook (`--xlsx`) with an `Unestimated` sheet and an
  `Off Sprint` sheet covering work that never reached the board.
- Machine-readable run summary (`--summary-json`) including data-quality
  counts, so downstream tooling can tell when a figure is untrustworthy.
- Daily snapshots (`snapshot`) so burndown history survives carryover
  rewriting the iteration field.
- Mid-sprint mode, selected automatically from the iteration dates.
- Optional delivery to SharePoint or OneDrive via Microsoft Graph.
- Standalone binaries for macOS (Apple silicon), Linux, and Windows.

### Notes

- Trend slides are omitted rather than rendered with a single data point.
- Snapshot history cannot be backfilled; start the collector before you need
  a burndown.
