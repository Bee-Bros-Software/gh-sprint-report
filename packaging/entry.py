"""Frozen-executable entry point.

PyInstaller needs a module-level script rather than a console-script entry
point, so this simply defers to the CLI.
"""

from __future__ import annotations

import sys

from sprint_report.cli import main

if __name__ == "__main__":
    sys.exit(main())
