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
| `Started` | Date | Set when work actually begins. Cycle time from creation includes however long an item sat in the backlog, which is noise. Cycle time from `Started` is the number that means something. |
| `Blocked` | Single select: `No` / `Waiting on us` / `Waiting on them` | Distinguishing internal from external blockers is what makes the figure actionable. A single boolean tells you there is a problem but not whose. |
| `Blocked since` | Date | Age is the signal. A one-day block is normal; a three-week block is a project risk. |
| `Health` | Single select: `On track` / `At risk` / `Off track` | Deliberately a human judgement, not derived. A person's read of a project usually leads the metrics by a week or two. |
| `Risk note` | Text | One line explaining an `At risk` or `Off track` call. Without it, the status is unarguable and therefore useless. |

Estimates must live in a **Number** field. A single select cannot be summed,
so no points-based figure works without it.

## Planned

### Cycle time

Median days from `Started` to close, trending across sprints, with a
distribution rather than only an average — the tail is where the problems
live. Works partially today from `createdAt` and `closedAt`; the `Started`
field is what makes it trustworthy.

Worth more to a leadership audience than velocity: it is measured in days
rather than points, so it cannot inflate and it compares across teams.

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

Requires dependency information, which GitHub Projects does not model.
Sub-issues give hierarchy — parent to child — but not "A must finish before
B", and the two are different questions.

Two viable approaches, neither pretty:

- **Convention in issue bodies.** A `Blocked by: #123` line, parsed. Fragile,
  but needs no new tooling and works today.
- **A `Depends on` text field** holding issue numbers. Structured, still
  manual, and prone to going stale.

Either way the graph has to be maintained by hand, and a stale dependency
graph produces a confidently wrong critical path. Worth being sure the team
will keep it current before building the feature.

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

## Data that does not exist

GitHub keeps no history of Projects v2 field changes — no API, and iteration
and number field changes do not appear in the issue timeline. Anything about
*how* an item moved has to be captured as it happens:

- **Daily snapshots** (`sprint-report snapshot`) — polling, one file per day.
  Granular to the day. This is what scope churn is built on.
- **Webhooks** (`projects_v2_item`) — every change with old and new values,
  but needs a receiver running continuously.

Snapshots are the right trade for most teams. Neither can recover the past:
whatever is not being captured today is gone.
