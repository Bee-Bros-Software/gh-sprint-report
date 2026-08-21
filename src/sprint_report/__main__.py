"""Allow execution via ``python -m sprint_report``.

Example:
    .. code-block:: console

        $ python -m sprint_report --org acme --project 1 snapshot
"""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
