"""Run the main demo end to end through the real CLI and write a verifiable manifest.

Usage:  python tools/run_demo_check.py OUTDIR

OUTDIR must not exist or be empty. It receives demo_workspace/, conflict_ws/, state/ and manifest.json.
Uses whatever `fileorganizer` package the current Python imports (so in a clean venv it checks the
installed package). Absolute paths in the manifest are replaced by <OUT> / <HOME>.
Exit code 0 only if every check passed.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_demo_workspace as demo  # noqa: E402

EXPECTED = json.load(open(os.path.join(HERE, "..", "tests", "fixtures", "demo_expected.json"), encoding="utf-8"))


def main(out: str) -> int:
    out = os.path.abspath(out)
    if os.path.exists(out) and os.listdir(out):
        raise SystemExit(f"Refusing to use non-empty folder: {out}")
    os.makedirs(out, exist_ok=True)
    out = os.path.realpath(out)  # long form (no 8.3 names) so path masking matches CLI output
    ws, cws, state = (os.path.join(out, n) for n in ("demo_workspace", "conflict_ws", "state"))
    log: list[dict] = []
    checks: list[dict] = []

    def clean(s: str) -> str:
        for path, tag in ((out, "<OUT>"), (os.path.expanduser("~"), "<HOME>")):
            for n in (4, 2, 1):  # JSON-escaped forms first (backslashes doubled once or twice)
                s = s.replace(path.replace("\\", "\\" * n), tag)
        return s

    def cli(*args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, "-m", "fileorganizer", "--state-dir", state, *args],
                           capture_output=True, text=True, encoding="utf-8", env=env, timeout=300)
        log.append({"cmd": clean("fileorganizer " + " ".join(args)), "exit": r.returncode,
                    "stdout": clean(r.stdout), "stderr": clean(r.stderr)})
        return r

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "result": "pass" if ok else "FAIL", "detail": detail})

    demo.build(ws)
    demo.build(cws, demo.CONFLICT_FILES)
    before = demo.tree_snapshot(ws)
    conflict_before = demo.tree_snapshot(cws)
    check("fixture has 36 files", len(before) == 36, str(len(before)))
    check("fixture SHA-256 matches frozen expectation", before == EXPECTED["sha256"])

    rules = os.path.join(out, "rules.json")
    with open(rules, "w", encoding="utf-8") as f:
        json.dump(EXPECTED["rules"], f, indent=1)
    plan_file = os.path.join(out, "plan.json")

    r = cli("--version")
    check("installed CLI runs", r.returncode == 0, r.stdout.strip())
    r = cli("plan", ws, "--rules", rules, "--out", plan_file)
    check("plan exit 0", r.returncode == 0)
    if r.returncode != 0:
        print(json.dumps(log, ensure_ascii=False, indent=1))
        print("FAIL  could not create the plan; stopping.")
        return 1
    with open(plan_file, encoding="utf-8") as f:
        plan = json.load(f)
    s = plan["summary"]
    check("preview 36 ready / 0 conflict", s["to_move"] == 36 and s["conflict"] == 0, json.dumps(s))
    mapping = {i["src"]: i["dst"] for i in plan["items"] if i["status"] == "ready"}
    check("plan mapping equals independent frozen mapping", mapping == EXPECTED["mapping"])
    check("preview changed nothing", demo.tree_snapshot(ws) == before)

    r = cli("apply", plan_file, "--yes")
    check("apply exit 0, 36 done", r.returncode == 0 and "done=36 failed=0 not_run=0" in r.stdout)
    after = demo.tree_snapshot(ws)
    ok = len(after) == 36 and all(after.get(dst) == EXPECTED["sha256"][src] for src, dst in EXPECTED["mapping"].items())
    check("every target exists with the planned SHA-256", ok)

    r = cli("history", "--root", ws, "--json")
    hist = json.loads(r.stdout) if r.returncode == 0 else []
    run_id = hist[0]["run_id"] if hist else ""
    check("history shows 1 completed run, 36 moved", len(hist) == 1 and hist[0]["state"] == "completed"
          and hist[0]["moved"] == 36)
    journal_path = os.path.join(state, "runs", run_id, "journal.jsonl")
    with open(journal_path, encoding="utf-8") as f:
        apply_events = [json.loads(x) for x in f if x.strip()]
    kinds = [e["type"] for e in apply_events]
    check("journal: 36 intent + 36 done", kinds.count("intent") == 36 and kinds.count("done") == 36)

    r = cli("undo", run_id, "--yes")
    check("undo exit 0, 36 restored", r.returncode == 0 and "Result: undone. done=36" in r.stdout)
    after_undo = demo.tree_snapshot(ws)
    check("after undo: all original paths and SHA-256 restored", after_undo == before)
    leftover = [d for d, _s, _f in os.walk(ws) if os.path.basename(d) == "Organized"]
    check("Organized folders created by the run were removed", not leftover)
    with open(journal_path, encoding="utf-8") as f:
        all_events = [json.loads(x) for x in f if x.strip()]

    cplan = os.path.join(out, "conflict_plan.json")
    crules = os.path.join(out, "conflict_rules.json")
    with open(crules, "w", encoding="utf-8") as f:
        json.dump({"classify": "extension", "recursive": True}, f)
    r = cli("plan", cws, "--rules", crules, "--out", cplan)
    check("conflict fixture: plan blocked (exit 2, 2 conflicts)",
          r.returncode == 2 and r.stdout.count("CONFLICT") == 2)
    r = cli("apply", cplan, "--yes")
    check("conflict fixture: apply refused (exit 2)", r.returncode == 2)
    check("conflict fixture: nothing changed", demo.tree_snapshot(cws) == conflict_before
          and not os.path.exists(os.path.join(cws, "Organized")))

    manifest = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "note": "Personal demo, synthetic data only.",
        "rules": EXPECTED["rules"],
        "tree_before": before, "tree_after_apply": after, "tree_after_undo": after_undo,
        "plan_summary": s, "run_id": run_id,
        "journal": all_events,
        "commands": log,
        "checks": checks,
    }
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        f.write(clean(json.dumps(manifest, ensure_ascii=False, indent=1)))
    for c in checks:
        print(f"{c['result']:<4}  {c['check']}" + (f"  [{c['detail']}]" if c["detail"] else ""))
    failed = [c for c in checks if c["result"] != "pass"]
    print(f"{len(checks) - len(failed)}/{len(checks)} checks passed. Manifest: {os.path.join(out, 'manifest.json')}")
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    sys.exit(main(sys.argv[1]))
