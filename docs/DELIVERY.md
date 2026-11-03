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
| Cover | `deliverables/cover.png` (made by `tools/make_cover.py`) | PIL check: 2000x1500, 133,316 bytes. Text and shapes only | done, see limitation 2 |
| Upwork draft | `deliverables/UPWORK.md` | Title 53 characters (limit 70); description 456 characters (limit 600), opens with the personal-demo/synthetic-data disclosure | done |

## Limitations and not verified

1. **Screenshots were not visually reviewed in the final pass.** Opening image files failed with a network error in two
   earlier runs, so this run did not open images. The A27 result rests on `a27_checks.json` (15/15) and the journal
   files. The check that each screenshot matches the journal and the disk is NOT claimed; only the disk and journal
   states at each step were machine-checked.
2. **The finished video and the cover were not watched or viewed.** Caption timing was set from ffmpeg scene-change times of the
   raw recording and the script's step order; caption text and layout were not checked by eye. Cover text fit was
   handled in code (font size shrinks to the box), not reviewed visually. Please look at both before use.
3. The cover does not copy the csv-cleaning-tool cover; it follows its size (2000x1500), English text and
   product-name-plus-key-points idea only. That cover was not opened this run either.
4. This ffmpeg build has no `drawtext` or `subtitles` filter, so captions are PNG overlays made with PIL.
5. The desktop was covered by a plain full-screen backdrop window during the run so private desktop windows are not
   recorded. The native folder picker opens in the user's Documents folder, so the raw recording (and the finished
   video) show that folder's names for about a second before the sandbox path is typed (the first picker view was seen
   in an earlier test screenshot; the finished video was not re-watched). Check both videos before sharing them publicly.
6. Window position (320,180) and widget coordinates in `a27_ui_run.py` are fixed for this 2560x1440 display and the
   current window layout. The native picker button click assumes the Chinese-locale Windows dialog size.
7. A12 (different volume) is still simulated only. Permission and full-disk failures are still injected only.
8. The first attempt of the run failed at a folder-picker step (the picker needs Select-folder clicked, not Enter);
   the driver was fixed and the run repeated from a new sandbox. The evidence and video come from the last run only.
9. `src/` was not changed in stage 6.
