# Roadmap

What is planned, and — more usefully — what a board needs to carry for each
of these to be possible. Most of these are blocked on data that has to be
recorded as work happens; none of it can be reconstructed later.

## Add these fields now

Every field below is cheap to add and impossible to backfill. Adding them
before the features land means the first report that uses them has real
history behind it.

| Field | Type | Why |
|---|---|---|
| `Blocked` | Single select: `No` / `Waiting on us` / `Waiting on them` | Distinguishing internal from external blockers is what makes the figure actionable. A single boolean tells you there is a problem but not whose. |
| `Blocked since` | Date | Age is the signal. A one-day block is normal; a three-week block is a project risk. |
| `Health` | Single select: `On track` / `At risk` / `Off track` | Deliberately a human judgement, not derived. A person's read of a project usually leads the metrics by a week or two. |
| `Risk note` | Text | One line explaining an `At risk` or `Off track` call. Without it, the status is unarguable and therefore useless. |

Estimates must live in a **Number** field. A single select cannot be summed,
so no points-based figure works without it.

## Planned

### Cycle time — shipped in 1.5.0

Measured from `ProjectV2ItemStatusChangedEvent`, so no field needs adding and
it works retroactively. Still to come: trending across sprints, and a
distribution rather than only a median and a tail.

### Blockers

Currently blocked items, how long each has been blocked, and whether the
dependency is internal or external. Needs `Blocked` and `Blocked since`.

The useful chart is blocked-days accumulated per sprint. A team losing a
third of its capacity to external waits has a staffing-and-escalation
problem, not a delivery problem, and the two get confused constantly.

### Project health

A one-line status per project, rolled up from the `Health` field on the
parent issue of each project or initiative. Deliberately human-set: an
automated health status computed from velocity tells leadership what they
could already see on the velocity chart.

### Critical path

GitHub Issues has **native dependencies** — `BlockingAddedEvent` and
`BlockedByAddedEvent` appear on the issue timeline, so the blocking graph is
queryable and retroactive. No convention in issue bodies, no hand-maintained
`Depends on` field.

The remaining work is graph traversal: build the dependency graph, find the
longest path by remaining estimate, and flag items on it. The honest caveat
is that a critical path is only as good as the dependencies people actually
record, so the first version should also report how many items have no
dependency links at all.

### Scope churn over time

Churn per sprint as a trend, not just within one sprint. Answers whether the
planning process is improving. Needs several sprints of snapshots.

## Not planned

**Individual throughput.** Points or issues closed per person. It measures
who picks up small items, and it changes behaviour the moment anyone knows it
exists.

**Automated health scoring.** A red/amber/green computed from velocity tells
you what the velocity chart already shows, while sounding more authoritative
than it is.

**Estimation accuracy per person.** Same failure mode as individual
throughput, with the added effect of pushing estimates upward.

## What GitHub does and does not retain

More is retained than is widely documented. Confirmed present on the issue
timeline and queryable retroactively:

- `AddedToProjectV2Event` — when an issue joined a board
- `ProjectV2ItemStatusChangedEvent` — every status transition, with previous
  and new values
- `BlockingAddedEvent` / `ParentIssueAddedEvent` — dependencies and hierarchy

Not observed: iteration or number field changes. If an item's sprint
assignment or estimate changes, nothing appears to record it, so scope churn
and estimate history still need capturing as they happen:

- **Daily snapshots** (`sprint-report snapshot`) — polling, one file per day.
  Granular to the day. This is what scope churn is built on.
- **Webhooks** (`projects_v2_item`) — every change with old and new values,
  but needs a receiver running continuously.

Snapshots are the right trade for most teams. Neither can recover the past:
whatever is not being captured today is gone.
