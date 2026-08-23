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

## Private source, public downloads

GitHub release assets inherit repository visibility — a private repo's assets
always require an authenticated API call to fetch. There is no setting for
"private source, public downloads."

The workaround is two repositories:

| Repo | Visibility | Contains |
|---|---|---|
| `gh-sprint-report` | private | source, CI, the release workflow |
| `gh-sprint-report-releases` | public | a README and the release assets |

`.github/workflows/release-to-mirror.yml` builds in the private repo and
publishes the binaries to the public one.

**Setup**

1. Create the public mirror repo with only a README.
2. Create a fine-grained PAT scoped to *just that repo* with
   **Contents: read and write**. Save it in the private repo as the secret
   `RELEASE_REPO_TOKEN`.
3. Set the repository variable `RELEASE_REPO` to `OWNER/gh-sprint-report-releases`.
4. Tag and push. `github.token` is deliberately not used — it grants no access
   outside its own repo.

**What this does and does not protect.** A PyInstaller binary bundles compiled
Python, which is straightforwardly decompilable. Shipping a binary rather than
source is obscurity, not secrecy. It is fine for keeping a work-in-progress
tidy or avoiding support questions; it is not a licensing control.

## Alternatives to a mirror repo

- **Object storage** — S3 + CloudFront, Cloudflare R2, or any S3-compatible
  bucket. Publish binaries from CI, serve them from a URL you control. Gives
  you download metrics and a stable link that does not move if you rename the
  repo.
- **PyPI** — publishes wheels, and wheels contain readable source, so this
  does not keep source private. Good for distribution, not for concealment.
