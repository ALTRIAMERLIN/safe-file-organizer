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

Latest result: 59 passed.
