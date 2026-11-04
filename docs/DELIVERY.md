# Delivery check (stage 6, 2026-11-04)

Personal demo project. Synthetic data only. Not a client project. Nothing was pushed or published.

## What stage 6 produced

| Item | Where | Checked how | Status |
|---|---|---|---|
| A27 real-window run | `tools/a27_ui_run.py`, `tools/uidrive.py`, `docs/evidence/a27/` | Real tkinter process driven with SendInput (mouse, keyboard, native folder picker and confirm boxes); 15 of 15 disk and journal checks passed, UI run 58.5 s | done |
| A27 evidence | `docs/evidence/a27/` | 8 screenshots, `a27_checks.json`, `journal_after_apply.jsonl` (87 events), `journal_after_undo.jsonl` (167 events), `A27_SUMMARY.md` | done, see limitation 1 |
| Acceptance and test report | `docs/ACCEPTANCE.md` (A27 row), `docs/TEST_REPORT.md` | Updated from the files above; `python -m pytest -q tests`: 159 passed, 0 failed, 0 skipped, 10.73 s | done |
| Raw recording | `video/raw/safe-file-organizer-real-run.mp4` | ffprobe: 60.87 s, 1920x1080, 30 fps, 2,091,621 bytes; recorded with ffmpeg gdigrab during the A27 run, not edited | done |
| Finished video | `video/out/safe-file-organizer-demo.mp4` (made by `tools/make_video.py`) | ffprobe: H.264, 1920x1080, 30 fps, 1793 frames, 59.77 s, 2,422,668 bytes, no audio. Cut = raw 1.0 s to 60.8 s, English captions burned in. Caption presence was checked by pixel statistics at four timestamps | done, see limitation 2 |
| Cover | `deliverables/cover.png` (made by `tools/make_cover.py`) | Rebuilt in the follow-up pass in the csv-cleaning-tool cover layout (title, subtitle, real screenshot panel, three number cards, orange "Personal demo · Synthetic data" badge). Only UI pixels: a crop of the real A27 screenshot `03_conflict_blocked.png`. 2000x1500, 309,350 bytes. Viewed and compared with the csv cover | done |
| Upwork draft | `deliverables/UPWORK.md` | Title 53 characters (limit 70); description 456 characters (limit 600), opens with the personal-demo/synthetic-data disclosure | done |

## Limitations and not verified

1. **Screenshot cross-check: done in the follow-up pass.** All 8 screenshots were opened and compared with the
   journals, the frozen mapping and the machine checks; no contradiction (table in `docs/evidence/a27/A27_SUMMARY.md`).
   Display note, not fixed because `src/` is frozen: the tables do not draw `_` on most rows (row height clips the
   glyph); names on disk are correct.
2. **Videos: sampled, not watched end to end.** Frames of the finished video were extracted and viewed at 3, 8, 14,
   15, 16.5, 18, 19.5, 21, 22, 30, 38, 46 and 54 s. Each caption matched what the frame shows: intro, picker, rules,
   conflict interception (about 16-21 s, both invoice.pdf rows red, Apply disabled), demo folder, rules, preview
   36 ready / 0 conflicts, Apply done 36, Undo restored 36. Frames between the samples were not viewed and nothing
   was listened to (there is no audio).
3. The cover now follows the csv-cleaning-tool cover layout (see the table); it was opened and compared with it.
4. This ffmpeg build has no `drawtext` or `subtitles` filter, so captions are PNG overlays made with PIL.
5. **Privacy check before publishing.** A full-screen backdrop window hid the rest of the desktop during the run. The
   earlier note that the picker first shows the Documents folder was wrong: raw frames at 5-7.5 s show it opening on a
   leftover sandbox from an earlier attempt (`C:\ego-run\a27tmp\run1\demo_workspace`, synthetic folders only). But in
   every picker view, in the raw recording, the finished video and `02_folder_dialog.png`, the left pane shows this
   machine's Quick Access entries (图片, 音乐, 视频, 学习资料, Game) and drives (系统 (C:), Google Drive, 本地磁盘 (Z:)).
   The Windows UI is Chinese-locale. Decide whether that is acceptable before sharing publicly.
6. Window position (320,180) and widget coordinates in `a27_ui_run.py` are fixed for this 2560x1440 display and the
   current window layout. The native picker button click assumes the Chinese-locale Windows dialog size.
7. A12 (different volume) is still simulated only. Permission and full-disk failures are still injected only.
8. The first attempt of the run failed at a folder-picker step (the picker needs Select-folder clicked, not Enter);
   the driver was fixed and the run repeated from a new sandbox. The evidence and video come from the last run only.
9. `src/` was not changed in stage 6.
10. **Intermittent Tk init error in the test suite.** In the follow-up pass `python -m pytest -q tests` ran 6 times:
    3 x 159 passed, 3 x 158 passed + 1 error. Each error was a Tcl init failure while a `tests/test_ui.py` fixture
    created `Tk()` ("Can't find a usable init.tcl" / "invalid command name tcl_findLibrary"), never a failed
    assertion, and not always in the same test. Not fixed; tests and `src/` unchanged.

## Follow-up pass (2026-11-04)

When this pass started, `main` already held the five stage-6 commits on top of the round-4 fix `780978f` (same tree
as `review/v1.0` `d66c542`), and `origin/main` already pointed at `d850233`. The A27 run, the raw recording and the
finished video were **not** redone; they were checked: screenshot cross-check (limitation 1), video frame sampling
(limitation 2), ffprobe values re-read (raw 60.87 s / 1823 frames / 2,091,621 bytes; finished 59.77 s / 1793 frames /
2,422,668 bytes, both 1920x1080 H.264 30 fps). The cover was rebuilt. This pass made new local commits only; nothing
was pushed.
