#!/usr/bin/env bash
# Build a standalone sprint-report executable.
#
# PyInstaller does NOT cross-compile: run this on the OS you intend to ship
# to. A macOS build must happen on a Mac, a Windows build on Windows.
#
#   ./packaging/build.sh
#
# Output: packaging/dist/sprint-report (or sprint-report.exe on Windows)

set -euo pipefail
cd "$(dirname "$0")"

python3 -m venv .buildenv
# shellcheck disable=SC1091
source .buildenv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet ".." pyinstaller

pyinstaller --clean --noconfirm sprint-report.spec

echo
echo "Built: $(pwd)/dist/sprint-report"
echo

if [[ "$(uname)" == "Darwin" ]]; then
  cat <<'NOTE'
macOS note: this binary is UNSIGNED. Gatekeeper will refuse to run it on
any Mac that did not build it — the recipient sees "cannot be opened because
the developer cannot be verified".

Three options, in order of how well they scale:

  1. Sign and notarize (needs a $99/yr Apple Developer account):
       codesign --force --options runtime --timestamp \
         --sign "Developer ID Application: YOUR NAME (TEAMID)" dist/sprint-report
       xcrun notarytool submit dist/sprint-report.zip \
         --apple-id you@example.com --team-id TEAMID --wait
       xcrun stapler staple dist/sprint-report

  2. Have each recipient clear the quarantine flag once:
       xattr -d com.apple.quarantine ./sprint-report

  3. Skip the binary and use pipx (see packaging/README.md).
NOTE
fi
