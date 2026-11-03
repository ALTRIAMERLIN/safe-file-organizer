# Safe File Organizer (draft README)

> Personal demo project. All demo files are synthetic. Not published.

Safe File Organizer renames and sorts the files in one folder on Windows. It always shows a preview first,
moves files only after you confirm, writes a log before every move, and can undo the last run.

Flow: choose folder → set rules → preview → apply (confirm) → check results and log → undo.

## What it does

- **Scan** one folder (sub folders only if you turn them on). Optional file-type filter (`pdf, jpg`, case-insensitive).
  Hidden/system files, links/junctions, hard-linked files and the app's own state folder are skipped, and the
  reason is shown.
- **Rename** in a fixed order: replace text in the name (literal, case-sensitive) → prefix/suffix → optional
  number `_001`. The extension and its case are kept.
- **Sort** (optional) into `<folder>\Organized\<ext>\` or `<folder>\Organized\YYYY-MM\` (modified time, **UTC**).
- **Preview** every file: source, target, action, status (`ready` / `conflict` / `skipped`) and reason.
  Export as CSV (UTF-8) or JSON.
- **Conflicts block the whole plan**: target exists, two files to one target, case-only rename, invalid Windows
  names, swaps/cycles, parent path is a file, path too long, path outside the folder. Nothing is renamed with an
  automatic suffix, overwritten or silently skipped.
- **Apply** re-checks every file (size, time, file identity, SHA-256) before anything moves, and again right before
  each move. Moves never overwrite. The first problem stops the run; files already moved stay moved and can be undone.
- **Log and recovery**: each run has a journal (`intent` before a move, `done` after). After a crash the next start
  compares the log with the disk. Only clear cases are recorded as moved or not moved; anything else becomes
  `needs_review` with the paths to check by hand. Recovery never continues a run.
- **Undo** the most recent run of a folder, in reverse order, after checking every file is still exactly as the run
  left it. Undo only removes empty folders the run created.

## Not supported (v1)

Moving across drives, network shares, cloud-sync folders being changed at the same time, renaming folders,
symbolic links/junctions, regex or fuzzy matching, content detection, duplicate removal, compression,
background watching, schedules. It does not promise transaction safety against power loss or a hostile process
changing files at the same moment. Undo restores paths and file contents, not folder times, ACLs or other metadata.

## Requirements

- Windows 10 or 11 (tested on Windows 11, build 26200)
- Python 3.11+ from python.org (includes tkinter). Tested with Python 3.11.9.
- No runtime dependencies. Tests: `pytest==8.3.4` (pinned in `requirements-dev.txt`).

## Install (clean)

```powershell
git clone <this repo> safe-file-organizer
cd safe-file-organizer
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install .
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
```

## Use

Desktop window:

```powershell
.\.venv\Scripts\python -m fileorganizer ui
```

Command line (always two steps; `apply` needs `--yes`):

```powershell
python -m fileorganizer plan C:\path\to\folder --rules rules.json --out C:\plans\plan.json
python -m fileorganizer apply C:\plans\plan.json --yes
python -m fileorganizer history --root C:\path\to\folder
python -m fileorganizer undo RUN_ID --yes
python -m fileorganizer recover --root C:\path\to\folder
```

`rules.json` (all keys optional):

```json
{"find": "old", "replace": "new", "prefix": "Doc_", "suffix": "", "numbering": true, "digits": 3,
 "classify": "extension", "recursive": true, "extensions": ["pdf", "jpg"]}
```

`classify` is `none`, `extension` or `month`. Plan files must be saved outside the source folder.

Exit codes: `0` success or nothing to do · `2` bad arguments or a check failed before anything moved ·
`3` failure during apply/undo, or a run needs review · `1` unexpected error (one-line message; add `--debug`
for the traceback).

App state (plans, run logs, locks) is in `%APPDATA%\SafeFileOrganizer`. Override with `--state-dir` or
`FILEORGANIZER_STATE_DIR`.

## Demo data

```powershell
python tools\make_demo_workspace.py demo_workspace              # 36 synthetic files in 3 sub folders
python tools\make_demo_workspace.py conflict_ws --conflict       # two invoice.pdf -> conflict when sorted
python tools\make_demo_workspace.py demo_workspace --reset --yes # removes only the generated files
python tools\run_demo_check.py OUT_DIR                           # full demo via the CLI + manifest.json
```

The generator refuses to write into a non-empty folder. The expected mapping in
`tests/fixtures/demo_expected.json` was computed by `tools/freeze_expected.py`, which does not use the app's code.

## Tests

```powershell
python -m pytest -q tests
```

All file tests run in pytest temp folders. Crash tests kill real child processes (`tests/worker.py`).
UI tests drive the real tkinter window; only the confirm and message dialogs are replaced.
See `docs/ACCEPTANCE.md` for the A01–A27 results and what is not verified.

## Layout

```
src/fileorganizer/  names, rules, scanner, planner (plan + conflicts), state (lock + journal),
                    runs (apply / recover / undo), cli, ui
tests/              pytest suites + fixtures/demo_expected.json + worker.py
tools/              demo generator, frozen-expectation script, demo check
docs/               SPEC, REQUIREMENTS, DESIGN, TASKS, ACCEPTANCE, TEST_REPORT, START_zh
```

中文启动说明：见 [docs/START_zh.md](docs/START_zh.md)。
