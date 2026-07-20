# Contributing to meeting-app

Thanks for contributing! This repo uses a two-branch flow:

- **`develop`** (default) — the integration branch. All contributions land
  here through pull requests. Code here works but is still being tested.
- **`release`** — the latest verified release. It only ever advances when a
  maintainer merges `develop` into it; nothing else may target it.

## Workflow

1. **Fork** the repo (external contributors) or create a branch (collaborators
   with write access), starting from the latest **`develop`**.
2. **Name your branch by what it does** (enforced by CI and repo rules):

   | Prefix | Use for |
   | --- | --- |
   | `feature/<name>` | New functionality |
   | `fix/<name>` | Bug fixes |
   | `hotfix/<name>` | Urgent fixes |
   | `chore/<name>` | Maintenance, tooling, CI |
   | `docs/<name>` | Documentation only |
   | `refactor/<name>` | Restructuring with no behavior change |
   | `perf/<name>` | Performance improvements |
   | `test/<name>` | Adding or fixing tests |

   Example: `git switch develop && git pull && git switch -c feature/mute-hotkey`

3. Make your changes and **run the checks locally** (below).
4. Open a **pull request to `develop`** and fill in the template.
5. A repository admin reviews the PR. Only admins can merge, and only after an
   approving review and green CI. Direct pushes to `develop` and `release` are
   blocked for everyone.

When enough has been merged and verified on `develop`, a maintainer opens a
`develop` → `release` pull request; CI (including a check that the source
really is `develop`) runs, and an admin merges it. That merge is the release.

## Local checks (same as CI)

Requires Python 3.12:

```bash
pip install -r requirements-dev.txt

ruff check src scripts                        # lint + security rules
black src scripts                             # auto-format
mypy                                          # type check (config in pyproject.toml)
bandit -c pyproject.toml -r src scripts -ll   # security lint
```

Optional — run them automatically before each commit:

```bash
pre-commit install
```

## Notes

- The app targets **Windows (fully supported)** and **macOS (experimental —
  needs the BlackHole virtual audio driver, and the overlay cannot hide from
  screen shares there)**; see README.md for per-platform setup. It needs
  Python 3.12. CI runs static checks only, so please test real behavior on
  your platform and say which one in the PR template.
- **Never commit secrets.** Your OpenAI key belongs in `.env`, which is
  gitignored. CI scans every push for leaked secrets.
- `temp/` and `context/` contents are gitignored — use `temp/` for scratch
  files and keep personal meeting context out of commits.
