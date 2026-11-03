# PROGRESS

Environment: Windows (see ACCEPTANCE.md for exact versions), Python 3.11.9, pytest 8.3.4. Local git only; nothing pushed or published.

## Stage 0 - docs mapping (done)
docs/REQUIREMENTS.md, docs/DESIGN.md, docs/TASKS.md written from docs/SPEC.md before any code.

## Stage 1 - frozen rules/data structures + independent fixtures (done)
- `rules.py` (strict `Rules`), plan data structures in `planner.py` (schema_version 1), `names.py`.
- `tools/make_demo_workspace.py`: 36-file demo (PDF10/JPG8/TXT8/CSV6/no-ext 4, 3 sub folders, CJK, spaces, same basenames, zero-byte) + conflict fixture; refuses non-empty dirs; scoped reset (marker + `--yes`).
- `tools/freeze_expected.py` computes the expected mapping independently (imports no production code); output frozen in `tests/fixtures/demo_expected.json`.

## Stage 2 - scan / plan / conflicts (done)
- Command: `python -m pytest -q tests` -> see latest result below.
- Covered: A01-A12 (A12 "different volume" is NOT verified: needs a second volume; code checks `st_dev` but no test).

## Stage 3 - execute / journal / lock / recovery / undo / fault injection (done)
- `state.py` (state dir, `msvcrt.locking` per-root lock, fsync'd JSONL journal), `runs.py` (apply, recover, undo, history).
- Tests: `tests/test_runs.py` (A13, A15, A16, A17, A18, A19, A20, A21, A22, A23, A24), including real subprocess kills (`tests/worker.py`) and a real two-process lock contention test.
- Command: `python -m pytest -q tests` -> 101 passed.
- Not verified: kill timing is limited to the three deterministic points (after intent / after move / after done); true power loss is out of scope by spec. Lock behaviour on network/cloud drives not tested (unsupported by spec).

## Stage 4 - CLI + tkinter UI (done)
- `cli.py` / `__main__.py`: `plan ROOT --rules --out`, `apply PLAN --yes`, `history --root [--json]`, `undo RUN_ID --yes`, `recover --root`, `ui`. Exit codes 0/2/3/1; unexpected errors print one line (traceback only with `--debug`).
- `ui.py`: four areas (Folder & Rules, Preview, Results, History & Undo). A `Controller` holds the preview generation counter: any rule/folder edit drops the preview and disables Apply; a scan that finishes after an edit is discarded. Work runs on a non-daemon thread; while busy all inputs and action buttons are disabled and closing is refused. No force-cancel button. Opening a folder runs the interrupted-run check (moves nothing) and lists runs needing review.
- Tests: `tests/test_cli.py` (15, real subprocess CLI) and `tests/test_ui.py` (22, real Tk widgets; only the confirm/message dialogs are replaced by recorders).
- Mutation check: disabling invalidation and the conflict check in `ui.py` made 10 A14 tests fail; original restored.
- Command: `python -m pytest -q tests` -> 138 passed.
- Not verified in this stage: A27 (a person operating the real window, plus screenshots) belongs to the stage 6 material and was not done. The UI tests drive real widgets but do not click native dialogs (folder picker, confirm box, save dialog).

Latest result: 138 passed.
