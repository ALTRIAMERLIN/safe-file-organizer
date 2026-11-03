# A27 evidence summary (real UI run)

Run id: `20261103T204653395580-49c498`. Machine checks: **15 of 15 passed** (`a27_checks.json`). UI run time: 58.5 s.

How it was done: `tools/a27_ui_run.py` launched the real tkinter app (`python -m fileorganizer ui`) as a separate process
with `FILEORGANIZER_STATE_DIR` pointing at a temp state dir, on fresh copies of the demo fixture and the conflict
fixture in a temp sandbox. All input went through the Windows input queue (`SendInput`, `tools/uidrive.py`): real mouse
clicks, real keystrokes, the native folder picker (path typed, "select folder" button clicked) and the native
Yes buttons of the confirm boxes. Checks read only the disk and the journal. No test harness, no Tk internals.

| Step | Screenshot | Machine check (disk / journal) |
|---|---|---|
| Launch | 01_launch.png | - |
| Folder picker | 02_folder_dialog.png | - |
| Conflict fixture, classify by extension, sub folders, Preview | 03_conflict_blocked.png | conflict folder byte-identical (tree + SHA-256), no Organized folder, no run directory created |
| Demo copy, prefix `Doc_`, numbering, by extension, Preview | 04_demo_preview.png | nothing moved, no run directory before Apply |
| Apply, confirm box | 05_confirm_apply.png | confirm box title "Confirm Apply" |
| After Apply | 06_applied.png | 36 targets exist with the original SHA-256, 36 sources gone, exactly 1 run directory, journal 36 intent + 36 done, last state `completed` |
| Undo, confirm box | 07_confirm_undo.png | confirm box title "Confirm Undo" |
| After Undo | 08_undone.png | tree + SHA-256 identical to the original, Organized removed, journal 36 undo_intent + 36 undo_done, last state `undone` |

Journals (copied from the state dir): `journal_after_apply.jsonl` (87 events: 3 state, 12 mkdir, 36 intent, 36 done) and
`journal_after_undo.jsonl` (167 events: 5 state, 12 mkdir, 36 intent, 36 done, 36 undo_intent, 36 undo_done, 6 rmdir).

Limitation: the screenshots are not used as evidence in this final pass. Opening images failed with a network error
in two earlier runs, so the acceptance result rests on the 15 machine checks and the journal files. A visual
screenshot-by-screenshot comparison against the journal is therefore NOT claimed.
