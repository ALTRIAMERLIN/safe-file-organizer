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

## Screenshot cross-check (done 2026-11-04, follow-up pass)

The earlier pass could not open images. In this pass all 8 screenshots were opened and read, and what each shows
was compared with the journal files above, `tests/fixtures/demo_expected.json` and the machine checks. The two
confirm-box shots were also told apart by pixel (dialog title bar present in 05 and 07 only), so file names match content.

| Screenshot | What it shows | Matches |
|---|---|---|
| 01_launch | Empty window, folder empty, "No preview yet", Apply / Undo disabled, "No run yet." | no run directory existed (check 03 "no run created") |
| 02_folder_dialog | Native picker titled "Choose the folder to organize", path `C:\ego-run\a27\conflict_ws`, sub folders 2025 and 2026 | conflict fixture layout (`CONFLICT_FILES`: 2025/invoice.pdf, 2026/invoice.pdf, 2026/other.txt) |
| 03_conflict_blocked | By extension + sub folders; 2025/invoice.pdf and 2026/invoice.pdf both -> Organized/pdf/invoice.pdf, status conflict (red); 2026/other.txt ready; marker skipped; "Scanned 4: ready 1, conflict 2, skipped 1. Apply is disabled"; Apply greyed | checks: conflict folder byte-identical, no Organized, no run dir |
| 04_demo_preview | Prefix `Doc_`, Add number, sub folders, by extension; "Scanned 37: ready 36 (to move 36, unchanged 0), conflict 0, skipped 1"; 14 visible rows | the 14 visible source -> target rows equal the first 14 `intent` events in order; all 36 intents equal the frozen expected mapping |
| 05_confirm_apply | "Confirm Apply": "Move or rename 36 file(s) in this folder?", `C:\ego-run\a27\demo_workspace` | check: title "Confirm Apply"; 36 intents |
| 06_applied | "Apply: completed. Done 36, failed 0, not run 0. Run 20261103T204653395580-49c498"; history row completed, Moved 36/36, Restored 0; Apply disabled ("Files changed") | run id in a27_checks.json; journal after apply: 36 intent + 36 done, last state completed |
| 07_confirm_undo | "Confirm Undo": "Undo run 20261103T204653395580-49c498? Move 36 file(s) back" | check: title "Confirm Undo"; same run id |
| 08_undone | "Undo: undone. Done 36, failed 0, not run 0"; history row undone, 36/36, Restored 36 | the 13 visible undo rows (Organized/csv/Doc_客户 名单_036.csv -> reports/客户 名单.csv ... Doc_旅行 照片_024.jpg -> photos 照片/旅行 照片.jpg) equal the first 13 `undo_intent` events in order (reverse of apply); every undo_intent has an undo_done; last state undone |

Result: no screenshot contradicts the journal or the disk checks.

Display note (no code change, src/ is frozen): in the preview and results tables the `_` character is not drawn on
most rows (e.g. `Doc data.v1 001.csv` on screen vs `Doc_data.v1_001.csv` in the journal and on disk); it is drawn on
the last visible row. This looks like the Treeview row height clipping the underscore glyph at this font size and
DPI. The names on disk are correct (checked against the journal and the frozen mapping). Reported, not fixed.
