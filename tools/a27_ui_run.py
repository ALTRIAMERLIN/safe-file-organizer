"""A27: operate the REAL tkinter window with OS-level mouse/keyboard input on a fresh demo copy.

Usage: python tools/a27_ui_run.py SANDBOX_DIR EVIDENCE_DIR [--record RAW_MP4]
SANDBOX_DIR must not exist. Nothing is simulated: the app is launched as a subprocess, every click and
keystroke goes through SendInput, the native folder picker and confirm boxes are clicked. Checks read the
disk and the journal only. Window is placed at REGION (1920x1080) on a plain backdrop; screenshots and the
optional ffmpeg recording cover exactly that region.
"""
from __future__ import annotations

import json, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_demo_workspace as demo  # noqa: E402
import uidrive as u  # noqa: E402
from PIL import ImageGrab  # noqa: E402

REPO = os.path.dirname(HERE)
X0, Y0, W, H = 320, 180, 1920, 1080
TITLE = "Safe File Organizer"
EXPECTED = json.load(open(os.path.join(REPO, "tests", "fixtures", "demo_expected.json"), encoding="utf-8"))
# widget centres relative to the window's top-left corner (read from the real window's screenshot)
BROWSE, RADIO_EXT, CHK_SUB, PREFIX, CHK_NUM = (1837, 87), (1266, 188), (1446, 155), (1585, 122), (210, 155)
PREVIEW, APPLY, UNDO = (1837, 223), (1837, 644), (1072, 943)


def main(sandbox: str, evidence: str, record: str | None) -> int:
    if os.path.exists(sandbox):
        raise SystemExit(f"Refusing to reuse {sandbox}")
    os.makedirs(sandbox)
    os.makedirs(evidence, exist_ok=True)
    sandbox = os.path.realpath(sandbox)
    ws, cws, state = (os.path.join(sandbox, n) for n in ("demo_workspace", "conflict_ws", "state"))
    demo.build(ws)
    demo.build(cws, demo.CONFLICT_FILES)
    before, cbefore = demo.tree_snapshot(ws), demo.tree_snapshot(cws)
    log: list[dict] = []
    shots: list[str] = []

    def check(step: str, name: str, ok: bool, detail: str = "") -> None:
        log.append({"step": step, "check": name, "result": "pass" if ok else "FAIL", "detail": detail})
        print(("pass " if ok else "FAIL ") + f"[{step}] {name} {detail}", flush=True)

    def shot(name: str) -> None:
        time.sleep(0.6)
        ImageGrab.grab(bbox=(X0, Y0, X0 + W, Y0 + H)).save(os.path.join(evidence, name))
        shots.append(name)
        print("shot", name, flush=True)

    def rel(p):
        return (X0 + p[0], Y0 + p[1])

    def run_dirs():
        d = os.path.join(state, "runs")
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def journal(rid):
        with open(os.path.join(state, "runs", rid, "journal.jsonl"), encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]

    def count(ev, t):
        return sum(1 for e in ev if e.get("type") == t)

    env = dict(os.environ, FILEORGANIZER_STATE_DIR=state, PYTHONPATH=os.path.join(REPO, "src"))
    backdrop = u.start_backdrop()
    app = subprocess.Popen([sys.executable, "-m", "fileorganizer", "ui"], env=env)
    ff = None
    try:
        hwnd = u.wait_window(app.pid, TITLE)
        u.place(hwnd, X0, Y0, W, H)
        time.sleep(1.0)
        u.move(X0 + 900, Y0 + 500, 0.2)
        if record:
            os.makedirs(os.path.dirname(record), exist_ok=True)
            ff = subprocess.Popen(["ffmpeg", "-hide_banner", "-y", "-f", "gdigrab", "-framerate", "30",
                                   "-offset_x", str(X0), "-offset_y", str(Y0), "-video_size", f"{W}x{H}",
                                   "-draw_mouse", "1", "-i", "desktop", "-c:v", "libx264", "-preset",
                                   "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", record],
                                  stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
            time.sleep(2.0)
        t_start = time.time()
        shot("01_launch.png")
        time.sleep(1.5)

        def choose_folder(path: str, tag: str, shotname: str | None):
            u.click(*rel(BROWSE))
            dh, _t = u.wait_dialog(app.pid, TITLE)
            time.sleep(1.0)
            l, t, r, b = u.rect(dh)
            u.place(dh, X0 + (W - (r - l)) // 2, Y0 + (H - (b - t)) // 2)
            time.sleep(0.8)
            u.type_text(path, 0.04)          # the picker's "Folder:" field has focus when it opens
            time.sleep(0.8)
            u.key("enter")                   # navigates into the typed folder
            time.sleep(1.5)
            if shotname:
                shot(shotname)
            l, t, r, b = u.rect(dh)
            u.click(l + 1048, t + 673)       # real click on the picker's select-folder button
            u.wait_no_dialog(app.pid, TITLE)
            time.sleep(1.2)
        # ---- conflict fixture first: blocked preview
        choose_folder(cws, "conflict", "02_folder_dialog.png")
        u.click(*rel(RADIO_EXT)); u.click(*rel(CHK_SUB))
        time.sleep(0.8)
        u.click(*rel(PREVIEW))
        time.sleep(2.5)
        shot("03_conflict_blocked.png")
        check("03", "conflict fixture untouched", demo.tree_snapshot(cws) == cbefore
              and not os.path.exists(os.path.join(cws, "Organized")))
        check("03", "no run created by a blocked preview", run_dirs() == [])
        time.sleep(1.5)

        # ---- demo copy: preview, apply
        choose_folder(ws, "demo", None)
        u.click(*rel(PREFIX)); u.type_text("Doc_")
        u.click(*rel(CHK_NUM))
        time.sleep(0.8)
        u.click(*rel(PREVIEW))
        time.sleep(3.0)
        shot("04_demo_preview.png")
        check("04", "preview moved nothing", demo.tree_snapshot(ws) == before
              and not os.path.exists(os.path.join(ws, "Organized")))
        check("04", "no run before Apply", run_dirs() == [])
        time.sleep(1.5)
        u.click(*rel(APPLY))
        dh, dt = u.wait_dialog(app.pid, TITLE)
        time.sleep(0.8)
        shot("05_confirm_apply.png")
        yes = [b for b in u.child_buttons(dh)][0]
        check("05", "confirm box title", dt == "Confirm Apply", dt)
        l, t, r, b = yes[1]
        time.sleep(1.2)
        u.click((l + r) // 2, (t + b) // 2)
        u.wait_no_dialog(app.pid, TITLE)
        time.sleep(3.0)
        shot("06_applied.png")
        mapping = EXPECTED["mapping"]
        ok = all(not os.path.exists(os.path.join(ws, s)) and os.path.isfile(os.path.join(ws, d))
                 for s, d in mapping.items())
        after = demo.tree_snapshot(ws)
        ok2 = all(after.get(d) == before[s] for s, d in mapping.items()) and len(after) == 36
        check("06", "36 targets exist, 36 sources gone", ok)
        check("06", "targets carry the original SHA-256", ok2)
        rids = run_dirs()
        check("06", "exactly one run dir", len(rids) == 1, str(rids))
        ev = journal(rids[0])
        check("06", "journal: 36 intent + 36 done", count(ev, "intent") == 36 and count(ev, "done") == 36,
              f"intent={count(ev,'intent')} done={count(ev,'done')}")
        check("06", "journal last state completed", [e for e in ev if e["type"] == "state"][-1]["state"] == "completed",
              str([e for e in ev if e["type"] == "state"][-1]))
        shutil.copyfile(os.path.join(state, "runs", rids[0], "journal.jsonl"),
                        os.path.join(evidence, "journal_after_apply.jsonl"))
        time.sleep(2.0)

        # ---- undo
        u.click(*rel(UNDO))
        dh, dt = u.wait_dialog(app.pid, TITLE)
        time.sleep(0.8)
        shot("07_confirm_undo.png")
        check("07", "confirm box title", dt == "Confirm Undo", dt)
        l, t, r, b = u.child_buttons(dh)[0][1]
        time.sleep(1.2)
        u.click((l + r) // 2, (t + b) // 2)
        u.wait_no_dialog(app.pid, TITLE)
        time.sleep(3.0)
        shot("08_undone.png")
        check("08", "all files back at original paths with original SHA-256", demo.tree_snapshot(ws) == before)
        check("08", "Organized folder removed", not os.path.exists(os.path.join(ws, "Organized")))
        ev = journal(rids[0])
        check("08", "journal: 36 undo_intent + 36 undo_done", count(ev, "undo_intent") == 36
              and count(ev, "undo_done") == 36, f"undo_intent={count(ev,'undo_intent')} undo_done={count(ev,'undo_done')}")
        check("08", "journal last state undone", [e for e in ev if e["type"] == "state"][-1]["state"] == "undone")
        shutil.copyfile(os.path.join(state, "runs", rids[0], "journal.jsonl"),
                        os.path.join(evidence, "journal_after_undo.jsonl"))
        time.sleep(3.0)
        duration = time.time() - t_start
    finally:
        if ff is not None:
            try:
                ff.stdin.write(b"q"); ff.stdin.flush(); ff.wait(timeout=30)
            except Exception:
                ff.kill()
        app.terminate(); backdrop.terminate()
    fails = [c for c in log if c["result"] != "pass"]
    json.dump({"checks": log, "screenshots": shots, "run_id": rids[0], "ui_seconds": round(duration, 1),
               "passed": len(log) - len(fails), "failed": len(fails)},
              open(os.path.join(evidence, "a27_checks.json"), "w", encoding="utf-8"), indent=2)
    print(f"{len(log)-len(fails)}/{len(log)} checks passed; ui run {duration:.1f}s")
    return 1 if fails else 0


if __name__ == "__main__":
    a = sys.argv[1:]
    rec = a[a.index("--record") + 1] if "--record" in a else None
    sys.exit(main(a[0], a[1], rec))

