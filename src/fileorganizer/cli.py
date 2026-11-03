"""Command line interface. Exit codes: 0 ok/no-op, 2 usage or pre-flight failure (nothing moved),
3 failure during execution/undo or recovery needed, 1 unexpected error."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__, names, planner, runs
from .errors import FileOrganizerError, PreflightError
from .rules import Rules
from .state import State


def _common() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--state-dir", default=argparse.SUPPRESS,
                   help="application state folder (default: %%APPDATA%%\\SafeFileOrganizer or $FILEORGANIZER_STATE_DIR)")
    p.add_argument("--debug", action="store_true", default=argparse.SUPPRESS, help="show tracebacks")
    return p


def build_parser() -> argparse.ArgumentParser:
    common = _common()
    ap = argparse.ArgumentParser(prog="fileorganizer", parents=[common],
                                 description="Safe File Organizer: preview first, move only after explicit confirmation, undo later.")
    ap.add_argument("--version", action="version", version=f"fileorganizer {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", parents=[common], help="scan ROOT and write a plan file (moves nothing)")
    p.add_argument("root")
    p.add_argument("--rules", help="rules JSON file (omit for no rules)")
    p.add_argument("--out", required=True, help="plan file to write (must be outside ROOT)")
    p.add_argument("--force", action="store_true", help="overwrite --out if it exists")

    p = sub.add_parser("apply", parents=[common], help="apply a plan file")
    p.add_argument("plan")
    p.add_argument("--yes", action="store_true", help="confirm that files may be moved")

    p = sub.add_parser("history", parents=[common], help="list runs for a folder")
    p.add_argument("--root", required=True)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("undo", parents=[common], help="undo the most recent run (by RUN_ID)")
    p.add_argument("run_id")
    p.add_argument("--yes", action="store_true", help="confirm that files may be moved back")

    p = sub.add_parser("recover", parents=[common], help="check interrupted runs against the disk (moves nothing)")
    p.add_argument("--root", required=True)

    sub.add_parser("ui", parents=[common], help="open the desktop window")
    return ap


def _load_rules(path: str | None) -> Rules:
    if not path:
        return Rules()
    try:
        with open(path, "rb") as f:
            data = json.loads(f.read().decode("utf-8-sig"))
    except FileNotFoundError as e:
        raise PreflightError(f"Rules file not found: {path}. Check the path.") from e
    except (OSError, ValueError) as e:
        raise PreflightError(f"Cannot read rules file {path}: {e}. It must be valid UTF-8 JSON.") from e
    return Rules.from_dict(data)


def _print_items(res: runs.RunResult) -> None:
    for i in res.items:
        extra = f"  ({i['error']})" if i["error"] else ""
        print(f"  {i['status']:<8} {i['src']} -> {i['dst']}{extra}")
    c = res.counts
    print(f"Result: {res.state}. done={c['done']} failed={c['failed']} not_run={c['not_run']}")
    if res.run_id:
        print(f"Run id: {res.run_id}")
    if res.message:
        print(res.message)


def cmd_plan(a, state: State) -> int:
    rules = _load_rules(a.rules)
    plan = planner.make_plan(a.root, rules, state.path)
    planner.save_plan(plan, a.out, overwrite=a.force)
    planner.save_plan(plan, os.path.join(state.plans_dir, f"{plan.plan_id}.json"))
    s = plan.summary
    print(f"Plan {plan.plan_id} written to {a.out}")
    print(f"Scanned {s['total']}: ready={s['ready']} (to move={s['to_move']}, no_op={s['no_op']}) "
          f"conflict={s['conflict']} skipped={s['skipped']}")
    for it in plan.items:
        if it.status == "conflict":
            print(f"  CONFLICT {it.src} -> {it.dst}: {it.reason}")
    if plan.blocked:
        print("The plan has conflicts and cannot be applied. Fix them and run 'plan' again.", file=sys.stderr)
        return 2
    return 0


def cmd_apply(a, state: State) -> int:
    if not a.yes:
        raise PreflightError("Refusing to move files without --yes. Review the plan, then add --yes.")
    plan = planner.load_plan(a.plan)
    res = runs.apply_plan(plan, state)
    _print_items(res)
    return 0 if res.ok else 3


def cmd_history(a, state: State) -> int:
    root = names.check_root_dir(a.root)
    rows = runs.history(state, root)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    elif not rows:
        print("No runs for this folder.")
    for r in rows if not a.json else []:
        print(f"{r['run_id']}  {r['state']:<20} moved={r['moved']}/{r['operations']} restored={r['restored']}")
    return 0


def cmd_undo(a, state: State) -> int:
    if not a.yes:
        raise PreflightError("Refusing to move files back without --yes. Add --yes to confirm the undo.")
    res = runs.undo_run(state, run_id=a.run_id)
    _print_items(res)
    return 0 if res.ok else 3


def cmd_recover(a, state: State) -> int:
    root = names.check_root_dir(a.root)
    changed = {r.run_id for r in runs.recover(state, root)}
    rc, shown = 0, False
    for r in runs.list_runs(state, root):
        if r.run_id in changed or r.state == "needs_review":
            shown = True
            print(f"Run {r.run_id}: {r.state}")
            for line in runs.review_report(r):
                print(f"  REVIEW {line}")
            if r.state == "needs_review":
                rc = 3
    if not shown:
        print("No interrupted runs found.")
    return rc


def cmd_ui(a, state: State) -> int:
    from .ui import launch
    launch(state)
    return 0


COMMANDS = {"plan": cmd_plan, "apply": cmd_apply, "history": cmd_history, "undo": cmd_undo,
            "recover": cmd_recover, "ui": cmd_ui}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    try:
        a = build_parser().parse_args(argv)
    except SystemExit as e:  # argparse: exit 2 for usage errors, 0 for --help
        return int(e.code or 0)
    debug = getattr(a, "debug", False)
    state = State(getattr(a, "state_dir", None))
    try:
        return COMMANDS[a.cmd](a, state)
    except PreflightError as e:
        print(f"Error: {e}", file=sys.stderr)
        for p in e.problems:
            print(f"  - {p}", file=sys.stderr)
        return 2
    except FileOrganizerError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 - last resort, still no raw traceback by default
        if debug:
            raise
        print(f"Unexpected error: {type(e).__name__}: {e}. Nothing further was attempted. "
              "Run 'history' and 'recover' to check state; use --debug for details.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
