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

Latest result: 101 passed.
