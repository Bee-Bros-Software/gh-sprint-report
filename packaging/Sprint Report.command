#!/usr/bin/env bash
# Double-clickable launcher for macOS. Put this next to the sprint-report
# binary, edit the two settings below, and it becomes a one-click report.
#
# Finder may need permission the first time: right-click > Open.

set -euo pipefail
cd "$(dirname "$0")"

# ---- settings ----------------------------------------------------------
ORG="your-org"
PROJECT="1"
OUTPUT_DIR="$HOME/Documents/Sprint Reviews"
# ------------------------------------------------------------------------

if ! command -v gh >/dev/null 2>&1; then
  echo "The GitHub CLI (gh) is not installed."
  echo "Install it from https://cli.github.com then run this again."
  read -r -p "Press return to close." _
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "You are not signed in to GitHub. Running sign-in now..."
  gh auth login
fi

mkdir -p "$OUTPUT_DIR"
STAMP="$(date +%Y-%m-%d)"

./sprint-report --org "$ORG" --project "$PROJECT" report \
  --iteration current \
  --output "$OUTPUT_DIR/Sprint Review $STAMP.pptx" \
  --xlsx "$OUTPUT_DIR/Sprint Follow-ups $STAMP.xlsx"

echo
echo "Done. Files are in: $OUTPUT_DIR"
open "$OUTPUT_DIR"
read -r -p "Press return to close." _
