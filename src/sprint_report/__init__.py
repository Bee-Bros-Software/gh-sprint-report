"""Sprint reporting for GitHub Projects boards.

Reads a Projects v2 board over GraphQL, accumulates daily snapshots so that
burndown history survives carryover, and renders a PowerPoint sprint review
deck with native editable charts.

Example:
    >>> from sprint_report import __version__
    >>> isinstance(__version__, str)
    True
"""

from __future__ import annotations

__all__ = ["__version__"]

#: Package version, kept in step with ``pyproject.toml``.
__version__ = "1.0.0"
