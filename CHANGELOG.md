# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
