"""Subprocess worker used by crash/lock tests. Usage: python worker.py CONFIG_JSON"""

import json
import os
import sys
import time

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from fileorganizer import planner, runs  # noqa: E402
from fileorganizer.errors import PreflightError  # noqa: E402
from fileorganizer.state import State  # noqa: E402

cfg = json.loads(sys.argv[1])
kill_at, op = cfg.get("kill_at"), cfg.get("op", 0)


def pre_move(phase, i, src, dst):
    if phase != cfg["mode"] or i != op:
        return
    if kill_at == "after_intent":
        os._exit(9)
    if kill_at == "hold":
        open(cfg["signal"], "w").write("held")
        t0 = time.time()
        while not os.path.exists(cfg["release"]) and time.time() - t0 < 60:
            time.sleep(0.05)


def move(src, dst):
    runs.safe_move(src, dst)
    if kill_at == "after_move" and cfg.get("cur_op_marker", True):
        counter["n"] += 1
        if counter["n"] == op + 1:
            os._exit(9)


def post_done(phase, i):
    if phase == cfg["mode"] and i == op and kill_at == "after_done":
        os._exit(9)


counter = {"n": 0}
hooks = runs.Hooks(pre_move=pre_move, move=move, post_done=post_done)
state = State(cfg["state"])
try:
    if cfg["mode"] == "exec":
        res = runs.apply_plan(planner.load_plan(cfg["plan"]), state, hooks)
    else:
        res = runs.undo_run(state, run_id=cfg.get("run_id"), root=cfg.get("root"), hooks=hooks)
    print(json.dumps({"state": res.state}))
except PreflightError as e:
    print(json.dumps({"preflight": str(e)}))
    sys.exit(2)
