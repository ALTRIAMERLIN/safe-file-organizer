"""Phase 4 UI tests: drive the real tkinter window (A14, A25 parity, UI main flow).

Confirm dialogs and message boxes are replaced by recorders; everything else is the real widget code.
"""

import json
import os
import subprocess
import sys
import threading
import time

import pytest

tk = pytest.importorskip("tkinter")

import make_demo_workspace as demo  # noqa: E402
from conftest import all_dirs, mk, snapshot  # noqa: E402
from fileorganizer import planner, runs, ui  # noqa: E402
from fileorganizer.state import State  # noqa: E402

HERE = os.path.dirname(__file__)
SRC = os.path.abspath(os.path.join(HERE, "..", "src"))
EXPECTED = json.load(open(os.path.join(HERE, "fixtures", "demo_expected.json"), encoding="utf-8"))


def pump(app, timeout=60):
    t0 = time.time()
    app.update()
    while app.ctl.busy or not app._q.empty():
        if time.time() - t0 > timeout:
            raise AssertionError("UI task did not finish")
        app.update()
        time.sleep(0.01)
    app.update()


def make_app(state_dir, answer=True):
    notes, confirms = [], []
    a = ui.App(State(state_dir), confirm=lambda t, m: confirms.append(m) or answer,
               notify=lambda k, t, m: notes.append((k, m)))
    a.withdraw()
    a.notes, a.confirms = notes, confirms
    return a


@pytest.fixture
def app(state):
    a = make_app(state)
    yield a
    pump(a)
    a.destroy()


def enabled(w):
    return not w.instate(["disabled"])


def open_folder(app, root):
    app.root_var.set(root)
    pump(app)


def do_preview(app):
    app.preview_btn.invoke()
    pump(app)


def set_demo_rules(app):
    app.prefix_var.set(EXPECTED["rules"]["prefix"])
    app.numbering_var.set(True)
    app.digits_var.set("3")
    app.classify_var.set("extension")
    app.recursive_var.set(True)


# ---------------------------------------------------------------- A14
def test_A14_apply_disabled_until_valid_preview(app, root):
    mk(root, {"a.txt": "1"})
    assert not enabled(app.apply_btn)
    open_folder(app, root)
    assert not enabled(app.apply_btn)  # folder alone is not a preview
    app.prefix_var.set("n_")
    do_preview(app)
    assert enabled(app.apply_btn) and app.ctl.plan is not None
    assert app.preview_tree.item("0")["values"][:4] == ["a.txt", "n_a.txt", "rename", "ready"]


def test_A14_rule_change_invalidates_preview_and_apply_does_nothing(app, root, state):
    mk(root, {"a.txt": "1", "b.txt": "2"})
    before = snapshot(root)
    open_folder(app, root)
    app.prefix_var.set("n_")
    do_preview(app)
    assert enabled(app.apply_btn)
    app.suffix_var.set("_x")  # any rule edit
    assert app.ctl.plan is None and not enabled(app.apply_btn)
    assert app.preview_tree.get_children() == ()
    assert "Click Preview" in app.summary_var.get()
    app.apply()  # even a direct call (bypassing the disabled button) does nothing
    pump(app)
    assert app.confirms == [] and snapshot(root) == before and runs.list_runs(State(state), root) == []


@pytest.mark.parametrize("var,value", [("find_var", "a"), ("replace_var", "z"), ("numbering_var", True),
                                       ("digits_var", "4"), ("classify_var", "month"),
                                       ("recursive_var", True), ("ext_var", "pdf")])
def test_A14_every_rule_input_invalidates(app, root, var, value):
    mk(root, {"a.txt": "1"})
    open_folder(app, root)
    app.prefix_var.set("n_")
    do_preview(app)
    assert enabled(app.apply_btn)
    getattr(app, var).set(value)
    assert app.ctl.plan is None and not enabled(app.apply_btn)


def test_A14_folder_change_invalidates_preview(app, root, tmp_path):
    mk(root, {"a.txt": "1"})
    other = tmp_path / "other"
    other.mkdir()
    open_folder(app, root)
    app.prefix_var.set("n_")
    do_preview(app)
    assert enabled(app.apply_btn)
    open_folder(app, str(other))
    assert app.ctl.plan is None and not enabled(app.apply_btn)


def test_A14_preview_finishing_after_a_rule_change_is_discarded(app, root):
    mk(root, {"a.txt": "1"})
    open_folder(app, root)
    app.prefix_var.set("n_")
    app.preview_btn.invoke()          # scan starts on the worker thread
    app.prefix_var.set("m_")           # user edits before the result arrives
    pump(app)
    assert app.ctl.plan is None and not enabled(app.apply_btn)
    assert "changed while scanning" in app.summary_var.get()


def test_A14_double_click_apply_moves_once(app, root, state):
    mk(root, {"a.txt": "A", "b.txt": "B"})
    open_folder(app, root)
    app.prefix_var.set("n_")
    do_preview(app)
    app.apply_btn.invoke()
    app.apply_btn.invoke()             # second click while the first is still running
    app.apply()
    pump(app)
    assert len(app.confirms) == 1
    assert sorted(os.listdir(root)) == ["n_a.txt", "n_b.txt"]
    assert len(runs.list_runs(State(state), root)) == 1
    app.apply()                        # plan is used up after Apply
    pump(app)
    assert len(runs.list_runs(State(state), root)) == 1 and not enabled(app.apply_btn)


def test_A14_cancel_in_confirm_moves_nothing(state, root):
    a = make_app(state, answer=False)
    try:
        mk(root, {"a.txt": "A"})
        open_folder(a, root)
        a.prefix_var.set("n_")
        do_preview(a)
        a.apply_btn.invoke()
        pump(a)
        assert len(a.confirms) == 1 and "1 file(s)" in a.confirms[0] and root in a.confirms[0]
        assert os.listdir(root) == ["a.txt"] and runs.list_runs(State(state), root) == []
    finally:
        a.destroy()


def test_A14_busy_disables_rule_editing_and_resubmit(app, root, monkeypatch):
    mk(root, {"a.txt": "A"})
    open_folder(app, root)
    app.prefix_var.set("n_")
    do_preview(app)
    gate, entered = threading.Event(), threading.Event()
    real = runs.apply_plan

    def slow_apply(plan, st, hooks=None):
        entered.set()
        assert gate.wait(30)
        return real(plan, st, hooks)

    monkeypatch.setattr(runs, "apply_plan", slow_apply)
    app.apply_btn.invoke()
    assert entered.wait(10)
    app.update()
    for w in (app.find_entry, app.prefix_entry, app.digits_spin, app.numbering_chk, app.recursive_chk,
              app.browse_btn, app.preview_btn, app.apply_btn, app.undo_btn, *app.classify_radios):
        assert not enabled(w), w
    app.preview()
    app.apply()
    app._on_close()                   # closing is refused while moving
    assert app.notes[-1] == ("info", "A task is running. Wait for it to finish before closing.")
    gate.set()
    pump(app)
    assert enabled(app.prefix_entry) and enabled(app.preview_btn) and app.winfo_exists()
    assert os.listdir(root) == ["n_a.txt"]


def test_A14_conflict_disables_apply(app, tmp_path):
    d = str(tmp_path / "conflict_ws")
    demo.build(d, demo.CONFLICT_FILES)
    open_folder(app, d)
    app.classify_var.set("extension")
    app.recursive_var.set(True)
    do_preview(app)
    assert app.ctl.plan.blocked and not enabled(app.apply_btn)
    assert "conflict 2" in app.summary_var.get() and "Apply is disabled" in app.summary_var.get()
    tags = [app.preview_tree.item(i)["tags"] for i in app.preview_tree.get_children()]
    assert sum(1 for t in tags if "conflict" in t) == 2


def test_A14_second_instance_cannot_repeat_the_move(state, root):
    mk(root, {"a.txt": "A"})
    a1, a2 = make_app(state), make_app(state)
    try:
        for a in (a1, a2):
            open_folder(a, root)
            a.prefix_var.set("n_")
            do_preview(a)
            assert enabled(a.apply_btn)
        a1.apply_btn.invoke()
        pump(a1)
        a2.apply_btn.invoke()          # same plan, other window: the core re-checks the disk
        pump(a2)
        assert os.listdir(root) == ["n_a.txt"]
        assert len(runs.list_runs(State(state), root)) == 1
        assert any(k == "error" and "Nothing was moved" in m for k, m in a2.notes)
    finally:
        a1.destroy()
        a2.destroy()


def test_A14_lock_held_by_other_instance_shows_error(app, root, state):
    mk(root, {"a.txt": "A"})
    open_folder(app, root)
    app.prefix_var.set("n_")
    do_preview(app)
    with State(state).lock(root):
        app.apply_btn.invoke()
        pump(app)
    assert any("Another Safe File Organizer task" in m for _k, m in app.notes)
    assert os.listdir(root) == ["a.txt"]


def test_ui_rule_error_shown_in_plain_english(app, root):
    mk(root, {"a.txt": "1"})
    open_folder(app, root)
    app.replace_var.set("x")           # replace without find
    do_preview(app)
    assert app.ctl.plan is None
    assert app.notes[-1][0] == "error" and "Find text must not be empty" in app.notes[-1][1]
    app.replace_var.set("")
    app.digits_var.set("abc")
    do_preview(app)
    assert "Digits must be a whole number" in app.notes[-1][1]


def test_ui_export_refuses_inside_root(app, root, tmp_path):
    mk(root, {"a.txt": "1"})
    open_folder(app, root)
    app.prefix_var.set("n_")
    do_preview(app)
    app.export("csv", os.path.join(root, "x.csv"))
    assert "inside the source folder" in app.notes[-1][1] and os.listdir(root) == ["a.txt"]
    app.export("csv", str(tmp_path / "x.csv"))
    app.export("json", str(tmp_path / "x.json"))
    assert (tmp_path / "x.csv").exists() and planner.load_plan(str(tmp_path / "x.json")).digest == app.ctl.plan.digest


# ---------------------------------------------------------------- UI main flow (automated, not the A27 manual run)
def test_ui_demo_main_flow_preview_apply_history_undo(app, tmp_path, state):
    d = str(tmp_path / "demo_workspace")
    demo.build(d)
    original, dirs0 = snapshot(d), all_dirs(d)
    open_folder(app, d)
    set_demo_rules(app)
    do_preview(app)
    assert app.summary_var.get().startswith("Scanned 37: ready 36 (to move 36, unchanged 0), conflict 0, skipped 1.")
    assert enabled(app.apply_btn)
    app.apply_btn.invoke()
    pump(app)
    assert "36 file(s)" in app.confirms[0]
    assert app.results_var.get().startswith("Apply: completed. Done 36, failed 0, not run 0.")
    assert len(app.results_tree.get_children()) == 36
    after = snapshot(d)
    for src, dst in EXPECTED["mapping"].items():
        assert after[dst] == EXPECTED["sha256"][src]
    h = app.history_tree.item("0")["values"]
    assert h[1] == "completed" and h[2] == "36/36"
    assert enabled(app.undo_btn)
    app.undo_btn.invoke()
    pump(app)
    assert app.results_var.get().startswith("Undo: undone. Done 36, failed 0, not run 0.")
    assert snapshot(d) == original and all_dirs(d) == dirs0
    assert app.history_tree.item("0")["values"][1] == "undone" and not enabled(app.undo_btn)


def test_ui_shows_needs_review_after_interrupted_run(app, root, state, tmp_path):
    mk(root, {"a.txt": "AAA", "b.txt": "BBB", "c.txt": "CCC"})
    plan = planner.make_plan(root, planner.Rules(prefix="n_"), state)
    plan_file = str(tmp_path / "plan.json")
    planner.save_plan(plan, plan_file)
    cfg = {"mode": "exec", "plan": plan_file, "state": state, "kill_at": "after_intent", "op": 1}
    assert subprocess.run([sys.executable, os.path.join(HERE, "worker.py"), json.dumps(cfg)],
                          timeout=120).returncode == 9
    os.remove(os.path.join(root, "b.txt"))  # now at neither place
    open_folder(app, root)                  # opening the folder runs the check
    assert app.history_tree.item("0")["values"][1] == "needs_review"
    assert "neither" in app.review_text.get("1.0", "end")
    app.undo_btn.invoke()
    pump(app)
    assert any("manual review" in m for _k, m in app.notes)
    assert sorted(os.listdir(root)) == ["c.txt", "n_a.txt"]


# ---------------------------------------------------------------- A25 CLI vs UI parity
def test_A25_cli_and_ui_same_mapping_and_result(app, tmp_path, state):
    d_cli, d_ui = str(tmp_path / "ws_cli"), str(tmp_path / "ws_ui")
    demo.build(d_cli)
    demo.build(d_ui)
    assert snapshot(d_cli) == snapshot(d_ui)
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps(EXPECTED["rules"]), encoding="utf-8")
    plan_file = str(tmp_path / "plan.json")
    env = dict(os.environ, PYTHONPATH=SRC, PYTHONIOENCODING="utf-8")
    cli_state = str(tmp_path / "cli_state")

    def cli(*args):
        return subprocess.run([sys.executable, "-m", "fileorganizer", "--state-dir", cli_state, *args],
                              capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)

    assert cli("plan", d_cli, "--rules", str(rules), "--out", plan_file).returncode == 0
    cli_plan = planner.load_plan(plan_file)

    open_folder(app, d_ui)
    set_demo_rules(app)
    do_preview(app)
    ui_plan = app.ctl.plan
    assert ui_plan.mapping() == cli_plan.mapping()
    assert ui_plan.rules == cli_plan.rules

    r = cli("apply", plan_file, "--yes")
    assert r.returncode == 0
    app.apply_btn.invoke()
    pump(app)
    assert snapshot(d_cli) == snapshot(d_ui)
    cli_run = runs.list_runs(State(cli_state), d_cli)[0]
    ui_run = runs.list_runs(State(state), d_ui)[0]
    assert cli_run.state == ui_run.state == "completed"
    assert cli_run.done_ops == ui_run.done_ops and len(ui_run.done_ops) == 36
