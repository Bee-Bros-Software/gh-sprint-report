# Distributing sprint-report

Three ways to get it onto someone's machine, easiest first.

## 1. pipx (recommended)

```bash
brew install pipx
pipx install ./gh-sprint-report
```

Installs into its own virtualenv and puts `sprint-report` on `PATH`. No
`--break-system-packages`, nothing touching Homebrew's Python. Upgrades are
`pipx upgrade gh-sprint-report`.

## 2. Standalone binary

```bash
./build.sh
```

Produces `dist/sprint-report` — no Python required on the target machine.

**PyInstaller does not cross-compile.** Build on the OS you are shipping to:
a Mac binary must be built on a Mac.

**macOS binaries are unsigned by default.** Gatekeeper blocks them on any
machine that did not build them. Either sign and notarize (Apple Developer
account, $99/yr), or have each recipient run
`xattr -d com.apple.quarantine ./sprint-report` once. For a handful of
colleagues the second is fine; for wider distribution, sign it.

## 3. Double-clickable launcher

`Sprint Report.command` wraps the binary with the arguments baked in. Edit
`ORG`, `PROJECT`, and `OUTPUT_DIR` at the top, drop it beside the binary, and
it becomes a one-click report that opens the output folder when done. It
checks for `gh` and offers to sign in if needed.

## The real prerequisite

**None of this removes the `gh` dependency.** The tool reads the board through
the GitHub CLI, so every recipient still needs `gh` installed, signed in, and
carrying the `project` scope:

```bash
gh auth refresh -s project
```

Freezing the Python does not help with that, and for a genuinely non-technical
recipient it is the harder half. Two alternatives that do solve it:

- **Send them the output, not the tool.** The scheduled workflow already
  writes the deck to SharePoint. Most people who want the report do not want
  to run anything.
- **Use `--from-export`.** One technical person runs
  `gh project item-list 20 --owner acme --format json --limit 500 > board.json`
  and shares the file; anyone can then generate reports from it with no GitHub
  access at all.
