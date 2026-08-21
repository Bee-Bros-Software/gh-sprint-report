Usage
=====

Board requirements
------------------

The tool reads four board fields. Names are configurable via flags if yours
differ.

============  ==============  ==================================================
Field         Type            Purpose
============  ==============  ==================================================
``Sprint``    Iteration       Groups work into sprints and supplies dates.
``Status``    Single select   ``Done`` marks completion when issues stay open.
``Pts``       Number          Numeric estimate. Must be Number, not single select.
``Origin``    Single select   ``Planned`` / ``Unplanned`` / ``Carryover``.
============  ==============  ==================================================

Authentication
--------------

Use a fine-grained personal access token or GitHub App installation token with
**organization Projects: read**. The ``GITHUB_TOKEN`` available to Actions
workflows does *not* carry that scope.

Supply it via ``--token`` or the ``GITHUB_PROJECTS_TOKEN`` environment variable.

Commands
--------

``snapshot``
    Captures today's board state to the snapshot directory. Run daily so
    burndown history accumulates. Re-running on the same day overwrites that
    day's file, so the command is idempotent.

``report``
    Generates the review deck. ``--iteration current`` selects the sprint
    spanning today, falling back to the most recent.

Why snapshots matter
--------------------

GitHub Projects has no burndown, and moving an unfinished item to the next
iteration retroactively removes its points from the sprint that did not finish
it. Daily snapshots fix both: each sprint retains a record of what it looked
like on each of its days.

History cannot be backfilled. Start the collector before you need the chart.
