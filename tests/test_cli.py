"""Phase 4 CLI tests (A25: same core, exit codes, no bare tracebacks). Runs the real CLI as a subprocess."""

import json
import os
import shutil
import subprocess
import sys

import pytest

import make_demo_workspace as demo
from conftest import all_dirs, mk, snapshot
from fileorganizer import cli, planner, runs
from fileorganizer.state import State

HERE = os.path.dirname(__file__)
SRC = os.path.abspath(os.path.join(HERE, "..", "src"))
EXPECTED = json.load(open(os.path.join(HERE, "fixtures", "demo_expected.json"), encoding="utf-8"))


def run_cli(state, *args):
    env = dict(os.environ, PYTHONPATH=SRC, PYTHONIOENCODING="utf-8")
    env.pop("FILEORGANIZER_STATE_DIR", None)
    r = subprocess.run([sys.executable, "-m", "fileorganizer", "--state-dir", state, *args],
                       capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)
    assert "Traceback" not in r.stderr, r.stderr
    return r


def write_rules(tmp_path, rules, name="rules.json"):
    p = tmp_path / name
    p.write_text(json.dumps(rules), encoding="utf-8")
    return str(p)


def test_A25_cli_demo_main_flow(tmp_path, state):
    d = str(tmp_path / "demo_workspace")
    demo.build(d)
    original, dirs0 = snapshot(d), all_dirs(d)
    rules = write_rules(tmp_path, EXPECTED["rules"])
    plan_file = str(tmp_path / "plan.json")

    r = run_cli(state, "plan", d, "--rules", rules, "--out", plan_file)
    assert r.returncode == 0, r.stderr
    assert "ready=36 (to move=36, no_op=0) conflict=0" in r.stdout
    plan = planner.load_plan(plan_file)
    assert {i.src: i.dst for i in plan.items if i.status == "ready"} == EXPECTED["mapping"]
    assert snapshot(d) == original and all_dirs(d) == dirs0  # plan moved nothing
    assert os.listdir(os.path.join(state, "plans"))          # plan also kept in the state folder

    r = run_cli(state, "apply", plan_file)  # no --yes
    assert r.returncode == 2 and "--yes" in r.stderr
    assert snapshot(d) == original

    r = run_cli(state, "apply", plan_file, "--yes")
    assert r.returncode == 0, r.stderr
    assert "Result: completed. done=36 failed=0 not_run=0" in r.stdout
    after = snapshot(d)
    for src, dst in EXPECTED["mapping"].items():
        assert after[dst] == EXPECTED["sha256"][src]

    r = run_cli(state, "history", "--root", d, "--json")
    rows = json.loads(r.stdout)
    assert r.returncode == 0 and len(rows) == 1 and rows[0]["state"] == "completed" and rows[0]["moved"] == 36
    run_id = rows[0]["run_id"]

    r = run_cli(state, "undo", run_id)  # no --yes
    assert r.returncode == 2 and snapshot(d) == after
    r = run_cli(state, "undo", run_id, "--yes")
    assert r.returncode == 0, r.stderr
    assert "Result: undone. done=36" in r.stdout
    assert snapshot(d) == original and all_dirs(d) == dirs0
    r = run_cli(state, "undo", run_id, "--yes")
    assert r.returncode == 0 and "already undone" in r.stdout and snapshot(d) == original


def test_A25_cli_blocked_plan_exit_2_and_cannot_apply(tmp_path, state):
    d = str(tmp_path / "conflict_ws")
    demo.build(d, demo.CONFLICT_FILES)
    before = snapshot(d)
    rules = write_rules(tmp_path, {"classify": "extension", "recursive": True})
    plan_file = str(tmp_path / "plan.json")
    r = run_cli(state, "plan", d, "--rules", rules, "--out", plan_file)
    assert r.returncode == 2 and r.stdout.count("CONFLICT") == 2 and "cannot be applied" in r.stderr
    r = run_cli(state, "apply", plan_file, "--yes")
    assert r.returncode == 2 and "conflict" in r.stderr
    assert snapshot(d) == before and not os.path.exists(os.path.join(d, "Organized"))


@pytest.mark.parametrize("args,needle", [
    ([], "required"),
    (["bogus"], "invalid choice"),
    (["plan", "Z:\\definitely\\missing\\dir", "--out", "OUT"], "Folder not found"),
    (["apply", "MISSING_PLAN.json", "--yes"], "Plan file not found"),
    (["undo", "no-such-run", "--yes"], "Run not found"),
    (["history", "--root", "Z:\\definitely\\missing\\dir"], "Folder not found"),
])
def test_A25_cli_usage_and_preflight_errors_exit_2(tmp_path, state, args, needle):
    args = [str(tmp_path / "out.json") if a == "OUT" else a for a in args]
    r = run_cli(state, *args)
    assert r.returncode == 2 and needle in r.stderr


def test_A25_cli_bad_rules_and_output_inside_root_exit_2(tmp_path, root, state):
    mk(root, {"a.txt": "1"})
    before = snapshot(root)
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    r = run_cli(state, "plan", root, "--rules", str(bad), "--out", str(tmp_path / "p.json"))
    assert r.returncode == 2 and "valid UTF-8 JSON" in r.stderr
    r = run_cli(state, "plan", root, "--rules", write_rules(tmp_path, {"regex": "x"}, "r2.json"),
                "--out", str(tmp_path / "p.json"))
    assert r.returncode == 2 and "Unknown rule keys" in r.stderr
    r = run_cli(state, "plan", root, "--rules", write_rules(tmp_path, {"prefix": "n_"}, "r3.json"),
                "--out", os.path.join(root, "plan.json"))
    assert r.returncode == 2 and "inside the source folder" in r.stderr
    assert snapshot(root) == before


def test_A25_cli_tampered_plan_exit_2(tmp_path, root, state):
    mk(root, {"a.txt": "1"})
    plan_file = tmp_path / "plan.json"
    assert run_cli(state, "plan", root, "--rules", write_rules(tmp_path, {"prefix": "n_"}),
                   "--out", str(plan_file)).returncode == 0
    data = json.loads(plan_file.read_text(encoding="utf-8"))
    data["items"][0]["dst"] = "../escaped.txt"
    plan_file.write_text(json.dumps(data), encoding="utf-8")
    r = run_cli(state, "apply", str(plan_file), "--yes")
    assert r.returncode == 2 and "digest" in r.stderr
    assert os.listdir(root) == ["a.txt"] and not (tmp_path / "escaped.txt").exists()


def test_A25_cli_lock_busy_exit_2(tmp_path, root, state):
    mk(root, {"a.txt": "1"})
    plan_file = str(tmp_path / "plan.json")
    run_cli(state, "plan", root, "--rules", write_rules(tmp_path, {"prefix": "n_"}), "--out", plan_file)
    with State(state).lock(root):
        r = run_cli(state, "apply", plan_file, "--yes")
    assert r.returncode == 2 and "Another Safe File Organizer task" in r.stderr
    assert os.listdir(root) == ["a.txt"]


@pytest.mark.windows
def test_A25_cli_failure_during_execution_exit_3(tmp_path, root, state):
    mk(root, {"a.txt": "A", "b.txt": "B", "c.txt": "C"})
    plan_file = str(tmp_path / "plan.json")
    run_cli(state, "plan", root, "--rules", write_rules(tmp_path, {"prefix": "n_"}), "--out", plan_file)
    held = open(os.path.join(root, "b.txt"), "rb")  # an open handle blocks the rename on Windows
    try:
        r = run_cli(state, "apply", plan_file, "--yes")
    finally:
        held.close()
    assert r.returncode == 3, (r.stdout, r.stderr)
    assert "Result: partial_failed. done=1 failed=1 not_run=1" in r.stdout
    assert sorted(os.listdir(root)) == ["b.txt", "c.txt", "n_a.txt"]
    r = run_cli(state, "recover", "--root", root)
    assert r.returncode == 0 and "No interrupted runs found." in r.stdout
    rid = json.loads(run_cli(state, "history", "--root", root, "--json").stdout)[0]["run_id"]
    assert run_cli(state, "undo", rid, "--yes").returncode == 0
    assert sorted(os.listdir(root)) == ["a.txt", "b.txt", "c.txt"]


def test_A25_cli_needs_review_exit_3_and_blocks_new_work(tmp_path, root, state):
    mk(root, {"a.txt": "AAA", "b.txt": "BBB", "c.txt": "CCC"})
    plan_file = str(tmp_path / "plan.json")
    run_cli(state, "plan", root, "--rules", write_rules(tmp_path, {"prefix": "n_"}), "--out", plan_file)
    cfg = {"mode": "exec", "plan": plan_file, "state": state, "kill_at": "after_intent", "op": 1}
    w = subprocess.run([sys.executable, os.path.join(HERE, "worker.py"), json.dumps(cfg)],
                       capture_output=True, text=True, timeout=120)
    assert w.returncode == 9
    shutil.copy2(os.path.join(root, "b.txt"), os.path.join(root, "n_b.txt"))  # file now at both places
    before = snapshot(root)
    r = run_cli(state, "recover", "--root", root)
    assert r.returncode == 3 and "needs_review" in r.stdout and "REVIEW" in r.stdout and "both" in r.stdout
    plan2 = str(tmp_path / "plan2.json")
    r = run_cli(state, "plan", root, "--rules", write_rules(tmp_path, {"suffix": "_x"}, "r2.json"), "--out", plan2)
    r = run_cli(state, "apply", plan2, "--yes")
    assert r.returncode == 2 and "manual review" in r.stderr
    rid = json.loads(run_cli(state, "history", "--root", root, "--json").stdout)[0]["run_id"]
    r = run_cli(state, "undo", rid, "--yes")
    assert r.returncode == 2 and "manual review" in r.stderr
    assert snapshot(root) == before


def test_A25_cli_unexpected_error_exit_1_without_traceback(monkeypatch, capsys, state):
    def boom(a, s):
        raise RuntimeError("simulated bug")

    monkeypatch.setitem(cli.COMMANDS, "history", boom)
    rc = cli.main(["--state-dir", state, "history", "--root", "."])
    err = capsys.readouterr().err
    assert rc == 1 and "Unexpected error: RuntimeError: simulated bug" in err and "Traceback" not in err


def test_cli_help_and_version(state):
    r = run_cli(state, "--help")
    assert r.returncode == 0 and "plan" in r.stdout and "undo" in r.stdout
    r = run_cli(state, "--version")
    assert r.returncode == 0 and "1.0.0" in r.stdout
