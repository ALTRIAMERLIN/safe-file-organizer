"""Phase 3 tests: execution, journal, lock, recovery, undo, fault injection (A13-A24, parts of A15)."""

import json
import os
import subprocess
import sys
import threading
import time

import pytest

import make_demo_workspace as demo
from conftest import all_dirs, mk, snapshot
from fileorganizer import planner, runs
from fileorganizer.errors import JournalError, LockBusyError, PreflightError
from fileorganizer.rules import Rules
from fileorganizer.state import Journal, State

HERE = os.path.dirname(__file__)
EXPECTED = json.load(open(os.path.join(HERE, "fixtures", "demo_expected.json"), encoding="utf-8"))


def plan_of(root, state=None, **kw):
    return planner.make_plan(root, Rules(**kw), state.path if state else None)


@pytest.fixture
def st(state):
    return State(state)


def three(root):
    mk(root, {"a.txt": "AAA", "b.txt": "BBB", "c.txt": "CCC"})


def names_in(root):
    return sorted(os.listdir(root))


# ---------------------------------------------------------------- A13
def _expect_zero_move(root, st, plan, before, dirs):
    with pytest.raises(PreflightError):
        runs.apply_plan(plan, st)
    assert snapshot(root) == before and all_dirs(root) == dirs
    assert runs.list_runs(st, root) == []


def test_A13_same_size_content_change_detected_even_with_same_mtime(root, st):
    three(root)
    p = plan_of(root, st, prefix="n_")
    path = os.path.join(root, "b.txt")
    ns = os.stat(path).st_mtime_ns
    open(path, "wb").write(b"XXX")  # same size
    os.utime(path, ns=(ns, ns))     # same mtime: only the SHA-256 can reveal it
    before, dirs = snapshot(root), all_dirs(root)
    with pytest.raises(PreflightError) as e:
        runs.apply_plan(p, st)
    assert any("SHA-256" in x for x in e.value.problems)
    assert snapshot(root) == before and runs.list_runs(st, root) == []


def test_A13_source_deleted(root, st):
    three(root)
    p = plan_of(root, st, prefix="n_")
    os.remove(os.path.join(root, "c.txt"))
    _expect_zero_move(root, st, p, snapshot(root), all_dirs(root))


def test_A13_source_replaced_by_identical_copy(root, st):
    three(root)
    p = plan_of(root, st, prefix="n_")
    path = os.path.join(root, "a.txt")
    ns = os.stat(path).st_mtime_ns
    data = open(path, "rb").read()
    os.remove(path)
    open(path, "wb").write(data)       # same bytes, same size
    os.utime(path, ns=(ns, ns))        # same mtime: only the file identity differs
    before = snapshot(root)
    with pytest.raises(PreflightError) as e:
        runs.apply_plan(p, st)
    assert any("replaced" in x for x in e.value.problems)
    assert snapshot(root) == before


def test_A13_target_created_after_preview(root, st):
    three(root)
    p = plan_of(root, st, prefix="n_")
    mk(root, {"n_b.txt": "intruder"})
    before = snapshot(root)
    with pytest.raises(PreflightError):
        runs.apply_plan(p, st)
    assert snapshot(root) == before and open(os.path.join(root, "n_b.txt")).read() == "intruder"


def test_A13_second_apply_of_same_plan_moves_nothing(root, st):
    three(root)
    p = plan_of(root, st, prefix="n_")
    assert runs.apply_plan(p, st).ok
    after = snapshot(root)
    with pytest.raises(PreflightError):
        runs.apply_plan(p, st)
    assert snapshot(root) == after and len(runs.list_runs(st, root)) == 1


# ---------------------------------------------------------------- A15 / A20 main flow on the demo data
def test_A15_A20_demo_apply_verify_undo_full_restore(tmp_path, st):
    d = str(tmp_path / "demo_workspace")
    demo.build(d)
    original = snapshot(d)
    dirs0 = all_dirs(d)
    plan = planner.make_plan(d, Rules.from_dict(EXPECTED["rules"]), st.path)
    res = runs.apply_plan(plan, st)
    assert res.state == "completed" and res.counts == {"done": 36, "failed": 0, "not_run": 0}
    now = snapshot(d)
    marker_free = {k: v for k, v in now.items() if k != demo.MARKER}
    # every target exists with the planned SHA-256 (independent frozen expectation)
    for src, dst in EXPECTED["mapping"].items():
        assert marker_free[dst] == EXPECTED["sha256"][src]
        assert src not in marker_free
    assert len(marker_free) == 36
    # journal explains every move
    run = runs.list_runs(st, d)[0]
    assert run.state == "completed" and len(run.done_ops) == 36
    kinds = [e["type"] for e in run.events]
    assert kinds.count("intent") == 36 and kinds.count("done") == 36
    # undo
    u = runs.undo_run(st, run_id=run.run_id)
    assert u.state == "undone" and u.counts["done"] == 36
    assert snapshot(d) == original
    assert all_dirs(d) == dirs0  # tool-created Organized/* folders removed, nothing else
    assert runs.list_runs(st, d)[0].state == "undone"


def test_A15_noop_and_skipped_untouched(root, st):
    mk(root, {"keep.txt": "k", "x.pdf": "p"})
    p = plan_of(root, st, find="zz", replace="q", extensions=("txt",))
    # extension filter skips x.pdf; keep.txt has no 'zz' -> pure no-op plan
    before = snapshot(root)
    res = runs.apply_plan(p, st)
    assert res.state == "completed" and res.run_id is None and res.items == []
    assert snapshot(root) == before
    assert runs.list_runs(st, root) == []  # no undoable action created


def test_A15_mixed_plan_only_moves_ready_items(root, st):
    mk(root, {"a.txt": "A", "b.pdf": "B", "same.txt": "S"})
    p = plan_of(root, st, prefix="n_", extensions=("txt",))  # b.pdf is skipped by the filter
    assert p.summary["skipped"] == 1 and p.summary["to_move"] == 2
    res = runs.apply_plan(p, st)
    assert res.counts["done"] == 2
    assert names_in(root) == ["b.pdf", "n_a.txt", "n_same.txt"]  # skipped b.pdf unchanged
    assert open(os.path.join(root, "b.pdf")).read() == "B"


# ---------------------------------------------------------------- A16
def test_A16_target_inserted_at_last_moment_is_never_overwritten(root, st):
    three(root)
    p = plan_of(root, st, prefix="n_")

    def pre_move(phase, i, src, dst):
        if i == 1:
            open(dst, "w").write("INTRUDER")

    res = runs.apply_plan(p, st, runs.Hooks(pre_move=pre_move))
    assert res.state == "partial_failed"
    assert [x["status"] for x in res.items] == ["done", "failed", "not_run"]
    assert open(os.path.join(root, "n_b.txt")).read() == "INTRUDER"
    assert open(os.path.join(root, "b.txt")).read() == "BBB"       # source intact
    assert os.path.exists(os.path.join(root, "c.txt"))               # later item untouched
    assert open(os.path.join(root, "n_a.txt")).read() == "AAA"      # earlier success kept
    assert "already exists" in res.message or "move failed" in res.message


@pytest.mark.windows
def test_A16_os_rename_semantics_refuse_overwrite(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_text("A")
    b.write_text("B")
    with pytest.raises(FileExistsError):
        runs.safe_move(str(a), str(b))
    assert a.read_text() == "A" and b.read_text() == "B"


# ---------------------------------------------------------------- A17
def test_A17_injected_failure_at_item_n(root, st):
    mk(root, {f"f{i}.txt": str(i) for i in range(5)})
    p = plan_of(root, st, prefix="n_")
    calls = {"n": 0}

    def move(src, dst):
        calls["n"] += 1
        if calls["n"] == 3:
            raise PermissionError(13, "Permission denied")
        runs.safe_move(src, dst)

    res = runs.apply_plan(p, st, runs.Hooks(move=move))
    assert res.state == "partial_failed"
    assert [x["status"] for x in res.items] == ["done", "done", "failed", "not_run", "not_run"]
    assert res.counts == {"done": 2, "failed": 1, "not_run": 2}
    assert calls["n"] == 3  # nothing attempted after the failure
    assert names_in(root) == ["f2.txt", "f3.txt", "f4.txt", "n_f0.txt", "n_f1.txt"]
    run = runs.list_runs(st, root)[0]
    assert run.state == "partial_failed" and run.done_ops == [0, 1] and run.exec[2] == "failed"
    kinds = [e["type"] for e in run.events]
    assert kinds.count("intent") == 3 and kinds.count("done") == 2 and kinds.count("failed") == 1


@pytest.mark.windows
def test_A17_real_locked_file_stops_the_run(root, st):
    three(root)
    p = plan_of(root, st, prefix="n_")
    held = open(os.path.join(root, "b.txt"), "rb")  # an open handle blocks the rename on Windows
    try:
        res = runs.apply_plan(p, st)
    finally:
        held.close()
    assert res.state == "partial_failed"
    assert [x["status"] for x in res.items] == ["done", "failed", "not_run"]
    assert names_in(root) == ["b.txt", "c.txt", "n_a.txt"]


# ---------------------------------------------------------------- A18
def test_A18_unwritable_log_dir_means_zero_moves(root, st, tmp_path):
    three(root)
    p = plan_of(root, st, prefix="n_")
    os.makedirs(st.path, exist_ok=True)
    open(st.runs_dir, "w").write("a FILE where the runs folder should be")  # makedirs must fail
    before = snapshot(root)
    with pytest.raises(PreflightError, match="run log"):
        runs.apply_plan(p, st)
    assert snapshot(root) == before


class FailingJournal(Journal):
    fail_on = None  # append number (1-based) that fails and all later ones

    def append(self, event):
        if FailingJournal.fail_on is not None and self.seq + 1 >= FailingJournal.fail_on:
            raise JournalError("injected disk failure")
        super().append(event)


@pytest.fixture
def failing():
    yield FailingJournal
    FailingJournal.fail_on = None


def test_A18_first_journal_write_fails_zero_moves(root, st, failing):
    three(root)
    p = plan_of(root, st, prefix="n_")
    failing.fail_on = 1
    before = snapshot(root)
    with pytest.raises(PreflightError):
        runs.apply_plan(p, st, runs.Hooks(journal_factory=failing))
    assert snapshot(root) == before


def test_A18_midrun_journal_failure_stops_and_recovery_reconciles(root, st, failing):
    three(root)
    p = plan_of(root, st, prefix="n_")
    # events: 1 planned, 2 running, 3 intent0, 4 done0, 5 intent1, 6 done1 -> fail the done of op 1
    failing.fail_on = 6
    res = runs.apply_plan(p, st, runs.Hooks(journal_factory=failing))
    assert res.state == "interrupted"
    assert names_in(root) == ["c.txt", "n_a.txt", "n_b.txt"]  # op 1 DID move, c.txt was not touched
    failing.fail_on = None
    run = runs.list_runs(st, root)[0]
    assert run.state == "running" and run.exec[1] == "intent"
    runs.recover(st, root)
    run = runs.list_runs(st, root)[0]
    assert run.exec == {0: "done", 1: "done"} and run.state == "partial_failed"
    u = runs.undo_run(st, run_id=run.run_id)  # the recovered success can be undone
    assert u.state == "undone" and names_in(root) == ["a.txt", "b.txt", "c.txt"]


def test_A18_journal_fails_before_intent_stops_before_that_move(root, st, failing):
    three(root)
    p = plan_of(root, st, prefix="n_")
    failing.fail_on = 5  # intent for op 1 cannot be written
    res = runs.apply_plan(p, st, runs.Hooks(journal_factory=failing))
    assert names_in(root) == ["b.txt", "c.txt", "n_a.txt"]
    assert res.state == "interrupted"


# ---------------------------------------------------------------- A19 (real process kills)
def run_worker(cfg, expect_code=None):
    r = subprocess.run([sys.executable, os.path.join(HERE, "worker.py"), json.dumps(cfg)],
                       capture_output=True, text=True, timeout=120)
    if expect_code is not None:
        assert r.returncode == expect_code, (r.stdout, r.stderr)
    return r


def killed_apply(root, st, tmp_path, kill_at, op):
    three(root)
    p = plan_of(root, st, prefix="n_")
    plan_file = str(tmp_path / "plan.json")
    planner.save_plan(p, plan_file)
    run_worker({"mode": "exec", "plan": plan_file, "state": st.path, "kill_at": kill_at, "op": op}, 9)
    return runs.list_runs(st, root)[0]


def test_A19_kill_after_intent_before_move(root, st, tmp_path):
    run = killed_apply(root, st, tmp_path, "after_intent", 1)
    assert run.state == "running" and run.exec == {0: "done", 1: "intent"}
    assert names_in(root) == ["b.txt", "c.txt", "n_a.txt"]
    runs.recover(st, root)
    run = runs.list_runs(st, root)[0]
    assert run.exec == {0: "done", 1: "failed"} and run.state == "partial_failed"
    assert names_in(root) == ["b.txt", "c.txt", "n_a.txt"]  # recovery never moves or continues


def test_A19_kill_after_move_before_done(root, st, tmp_path):
    run = killed_apply(root, st, tmp_path, "after_move", 1)
    assert run.exec == {0: "done", 1: "intent"}  # the log does NOT know op 1 moved
    assert names_in(root) == ["c.txt", "n_a.txt", "n_b.txt"]  # ...but it did
    runs.recover(st, root)
    run = runs.list_runs(st, root)[0]
    assert run.exec == {0: "done", 1: "done"} and run.state == "partial_failed"
    assert names_in(root) == ["c.txt", "n_a.txt", "n_b.txt"]
    assert runs.undo_run(st, run_id=run.run_id).state == "undone"
    assert names_in(root) == ["a.txt", "b.txt", "c.txt"]


def test_A19_kill_after_done(root, st, tmp_path):
    run = killed_apply(root, st, tmp_path, "after_done", 1)
    assert run.state == "running" and run.exec == {0: "done", 1: "done"}
    runs.recover(st, root)
    run = runs.list_runs(st, root)[0]
    assert run.state == "partial_failed" and run.done_ops == [0, 1]
    assert names_in(root) == ["c.txt", "n_a.txt", "n_b.txt"]


def test_A19_kill_after_last_done_reconciles_to_completed(root, st, tmp_path):
    run = killed_apply(root, st, tmp_path, "after_done", 2)
    runs.recover(st, root)
    assert runs.list_runs(st, root)[0].state == "completed"


def test_A19_ambiguity_both_locations_needs_review(root, st, tmp_path):
    killed_apply(root, st, tmp_path, "after_intent", 1)
    import shutil
    shutil.copy2(os.path.join(root, "b.txt"), os.path.join(root, "n_b.txt"))  # now at both places
    before = snapshot(root)
    runs.recover(st, root)
    run = runs.list_runs(st, root)[0]
    assert run.state == "needs_review" and run.exec[1] == "review"
    assert snapshot(root) == before  # files left exactly as found
    report = "\n".join(runs.review_report(run))
    assert "both" in report and "b.txt" in report
    with pytest.raises(PreflightError, match="manual review"):
        runs.undo_run(st, root=root)
    with pytest.raises(PreflightError, match="manual review"):
        runs.apply_plan(plan_of(root, st, prefix="z_"), st)


def test_A19_ambiguity_neither_location_needs_review(root, st, tmp_path):
    killed_apply(root, st, tmp_path, "after_intent", 1)
    os.remove(os.path.join(root, "b.txt"))
    runs.recover(st, root)
    run = runs.list_runs(st, root)[0]
    assert run.state == "needs_review" and "neither" in "\n".join(runs.review_report(run))


def test_A19_ambiguity_content_mismatch_needs_review(root, st, tmp_path):
    killed_apply(root, st, tmp_path, "after_move", 1)
    open(os.path.join(root, "n_b.txt"), "w").write("changed after the crash")
    runs.recover(st, root)
    assert runs.list_runs(st, root)[0].state == "needs_review"


def test_A19_needs_review_stays_when_user_recreates_file_with_different_identity(root, st, tmp_path):
    killed_apply(root, st, tmp_path, "after_intent", 1)
    os.remove(os.path.join(root, "b.txt"))
    runs.recover(st, root)
    assert runs.list_runs(st, root)[0].state == "needs_review"
    open(os.path.join(root, "n_b.txt"), "w").write("BBB")  # same bytes but a new file: identity differs
    runs.recover(st, root)
    assert runs.list_runs(st, root)[0].state == "needs_review"  # never guesses


def test_A19_needs_review_resolves_when_original_is_put_back_exactly(root, st, tmp_path):
    killed_apply(root, st, tmp_path, "after_intent", 1)
    src = os.path.join(root, "b.txt")
    saved = str(tmp_path / "saved_b")
    os.rename(src, saved)  # simulate the "neither location" state, then the user puts the SAME file back
    runs.recover(st, root)
    assert runs.list_runs(st, root)[0].state == "needs_review"
    os.rename(saved, src)
    runs.recover(st, root)
    run = runs.list_runs(st, root)[0]
    assert run.state == "partial_failed" and run.exec[1] == "failed"


def test_A19_torn_journal_line_is_tolerated(root, st, tmp_path):
    run = killed_apply(root, st, tmp_path, "after_done", 0)
    with open(run.journal_path, "ab") as f:
        f.write(b'{"type":"intent","op":1,"sr')  # half-written line from a crash
    runs.recover(st, root)
    run = runs.list_runs(st, root)[0]
    assert run.state == "partial_failed" and run.done_ops == [0]


# ---------------------------------------------------------------- A20 / A21 / A22 / A23
def test_A20_undo_preserves_preexisting_dirs(root, st):
    mk(root, {"a.pdf": "1", "b.txt": "2"})
    os.makedirs(os.path.join(root, "Organized", "pdf"))  # pre-existing empty folders: must survive undo
    p = plan_of(root, st, classify="extension")
    res = runs.apply_plan(p, st)
    assert res.ok
    assert os.path.isdir(os.path.join(root, "Organized", "txt"))
    run = runs.list_runs(st, root)[0]
    assert run.mkdirs == ["Organized/txt"]  # only what the tool created
    runs.undo_run(st, run_id=run.run_id)
    assert os.path.isdir(os.path.join(root, "Organized", "pdf"))   # pre-existing: kept
    assert not os.path.exists(os.path.join(root, "Organized", "txt"))
    assert names_in(root) == ["Organized", "a.pdf", "b.txt"]


def test_A20_created_dir_with_foreign_file_is_kept(root, st):
    mk(root, {"a.pdf": "1"})
    runs.apply_plan(plan_of(root, st, classify="extension"), st)
    open(os.path.join(root, "Organized", "pdf", "mine.txt"), "w").write("user file")
    assert runs.undo_run(st, root=root).state == "undone"
    assert open(os.path.join(root, "Organized", "pdf", "mine.txt")).read() == "user file"
    assert os.path.exists(os.path.join(root, "a.pdf"))


def _applied(root, st, classify="extension"):
    mk(root, {"a.pdf": "AAA", "b.pdf": "BBB", "c.txt": "CCC"})
    runs.apply_plan(plan_of(root, st, classify=classify), st)
    return runs.list_runs(st, root)[0]


def _assert_undo_refused(root, st):
    before = snapshot(root)
    dirs = all_dirs(root)
    with pytest.raises(PreflightError, match="Undo refused") as e:
        runs.undo_run(st, root=root)
    assert snapshot(root) == before and all_dirs(root) == dirs
    assert runs.list_runs(st, root)[0].state == "completed"
    return e.value


def test_A21_target_modified(root, st):
    _applied(root, st)
    open(os.path.join(root, "Organized", "pdf", "b.pdf"), "w").write("tampered!!")
    err = _assert_undo_refused(root, st)
    assert any("Organized/pdf/b.pdf" in x for x in err.problems)


def test_A21_target_replaced_same_content(root, st):
    _applied(root, st)
    p = os.path.join(root, "Organized", "pdf", "a.pdf")
    ns = os.stat(p).st_mtime_ns
    os.remove(p)
    open(p, "w").write("AAA")
    os.utime(p, ns=(ns, ns))
    err = _assert_undo_refused(root, st)
    assert any("replaced" in x for x in err.problems)


def test_A21_target_missing(root, st):
    _applied(root, st)
    os.remove(os.path.join(root, "Organized", "txt", "c.txt"))
    err = _assert_undo_refused(root, st)
    assert any("missing" in x for x in err.problems)


def test_A21_original_location_occupied(root, st):
    _applied(root, st)
    open(os.path.join(root, "a.pdf"), "w").write("new file by the user")
    err = _assert_undo_refused(root, st)
    assert any("occupied" in x for x in err.problems)
    assert open(os.path.join(root, "a.pdf")).read() == "new file by the user"  # never overwritten


def test_A22_partial_run_undoes_only_successes_and_repeat_is_noop(root, st):
    mk(root, {f"f{i}.txt": str(i) for i in range(4)})
    original = snapshot(root)
    calls = {"n": 0}

    def move(src, dst):
        calls["n"] += 1
        if calls["n"] == 3:
            raise PermissionError(13, "denied")
        runs.safe_move(src, dst)

    p = plan_of(root, st, prefix="n_")
    res = runs.apply_plan(p, st, runs.Hooks(move=move))
    assert res.state == "partial_failed"
    run = runs.list_runs(st, root)[0]
    u = runs.undo_run(st, run_id=run.run_id)
    assert u.state == "undone" and u.counts == {"done": 2, "failed": 0, "not_run": 0}
    assert snapshot(root) == original
    after = snapshot(root)
    again = runs.undo_run(st, run_id=run.run_id)
    assert again.state == "undone" and again.items == [] and "already" in again.message
    assert snapshot(root) == after
    assert runs.undo_run(st, root=root).message == "Nothing to undo."


def test_A22_only_latest_batch_can_be_undone(root, st):
    mk(root, {"a.txt": "A"})
    original = snapshot(root)
    runs.apply_plan(plan_of(root, st, prefix="one_"), st)
    runs.apply_plan(plan_of(root, st, prefix="two_"), st)
    r1, r2 = runs.list_runs(st, root)
    assert names_in(root) == ["two_one_a.txt"]
    with pytest.raises(PreflightError, match="most recent"):
        runs.undo_run(st, run_id=r1.run_id)
    assert names_in(root) == ["two_one_a.txt"]
    assert runs.undo_run(st, run_id=r2.run_id).ok and names_in(root) == ["one_a.txt"]
    assert runs.undo_run(st, run_id=r1.run_id).ok
    assert snapshot(root) == original
    assert [h["state"] for h in runs.history(st, root)] == ["undone", "undone"]


def test_A23_undo_fails_at_item_n_then_retry_does_not_repeat(root, st):
    mk(root, {f"f{i}.txt": str(i) for i in range(4)})
    original = snapshot(root)
    run = None
    runs.apply_plan(plan_of(root, st, prefix="n_"), st)
    run = runs.list_runs(st, root)[0]
    seen = []

    def move(src, dst):
        seen.append(os.path.basename(dst))
        if len(seen) == 3:
            raise PermissionError(13, "denied")
        runs.safe_move(src, dst)

    u = runs.undo_run(st, run_id=run.run_id, hooks=runs.Hooks(move=move))
    assert u.state == "undo_partial_failed"
    assert [x["status"] for x in u.items] == ["done", "done", "failed", "not_run"]
    assert seen == ["f3.txt", "f2.txt", "f1.txt"]  # reverse order, stopped at the failure
    run = runs.list_runs(st, root)[0]
    assert run.state == "undo_partial_failed" and run.remaining_undo_ops == [0, 1]
    retry_seen = []

    def move2(src, dst):
        retry_seen.append(os.path.basename(dst))
        runs.safe_move(src, dst)

    u2 = runs.undo_run(st, run_id=run.run_id, hooks=runs.Hooks(move=move2))
    assert u2.state == "undone" and retry_seen == ["f1.txt", "f0.txt"]  # restored items not repeated
    assert snapshot(root) == original


def test_A23_undo_process_killed_then_reconciled_and_retried(root, st, tmp_path):
    mk(root, {f"f{i}.txt": str(i) for i in range(3)})
    original = snapshot(root)
    runs.apply_plan(plan_of(root, st, prefix="n_"), st)
    run = runs.list_runs(st, root)[0]
    run_worker({"mode": "undo", "state": st.path, "run_id": run.run_id, "kill_at": "after_move", "op": 1}, 9)
    run = runs.list_runs(st, root)[0]
    assert run.state == "undo_running" and run.undo[1] == "intent"   # restore #2 happened but unlogged
    runs.recover(st, root)
    run = runs.list_runs(st, root)[0]
    assert run.state == "undo_partial_failed" and run.undo == {2: "done", 1: "done"}
    assert runs.undo_run(st, run_id=run.run_id).state == "undone"
    assert snapshot(root) == original


def test_A23_undo_killed_after_intent(root, st, tmp_path):
    mk(root, {f"f{i}.txt": str(i) for i in range(3)})
    original = snapshot(root)
    runs.apply_plan(plan_of(root, st, prefix="n_"), st)
    run = runs.list_runs(st, root)[0]
    run_worker({"mode": "undo", "state": st.path, "run_id": run.run_id, "kill_at": "after_intent", "op": 1}, 9)
    runs.recover(st, root)
    run = runs.list_runs(st, root)[0]
    assert run.state == "undo_partial_failed" and run.undo[1] == "failed"
    assert runs.undo_run(st, run_id=run.run_id).state == "undone"
    assert snapshot(root) == original


# ---------------------------------------------------------------- A24
def test_A24_lock_excludes_second_holder_in_process(root, st):
    three(root)
    p = plan_of(root, st, prefix="n_")
    with st.lock(root):
        before = snapshot(root)
        with pytest.raises(LockBusyError):
            runs.apply_plan(p, st)
        assert snapshot(root) == before
    assert runs.apply_plan(p, st).ok  # released afterwards


def test_A24_two_processes_only_one_executes(root, st, tmp_path):
    three(root)
    p = plan_of(root, st, prefix="n_")
    plan_file = str(tmp_path / "plan.json")
    planner.save_plan(p, plan_file)
    sig, rel = str(tmp_path / "held"), str(tmp_path / "release")
    cfg = {"mode": "exec", "plan": plan_file, "state": st.path, "kill_at": "hold", "op": 1,
           "signal": sig, "release": rel}
    holder = subprocess.Popen([sys.executable, os.path.join(HERE, "worker.py"), json.dumps(cfg)],
                              stdout=subprocess.PIPE, text=True)
    try:
        t0 = time.time()
        while not os.path.exists(sig) and time.time() - t0 < 60:
            time.sleep(0.05)
        assert os.path.exists(sig), "holder never reached the hold point"
        second = run_worker({"mode": "exec", "plan": plan_file, "state": st.path})
        assert second.returncode == 2 and "Another Safe File Organizer task" in second.stdout
        undo_try = run_worker({"mode": "undo", "state": st.path, "root": root})
        assert undo_try.returncode == 2
    finally:
        open(rel, "w").write("go")
        holder.wait(timeout=60)
    assert holder.returncode == 0
    assert names_in(root) == ["n_a.txt", "n_b.txt", "n_c.txt"]
    assert len(runs.list_runs(st, root)) == 1  # exactly one execution happened


def test_A24_lock_released_when_process_killed(root, st, tmp_path):
    run = killed_apply(root, st, tmp_path, "after_intent", 1)
    with st.lock(root):  # would raise LockBusyError if the dead process still held it
        pass
    runs.recover(st, root)
    assert runs.list_runs(st, root)[0].state == "partial_failed"


def test_A24_lock_is_per_root(root, st, tmp_path):
    other = str(tmp_path / "other")
    os.mkdir(other)
    with st.lock(root):
        with st.lock(other):
            pass


def test_A24_threads_double_submit_moves_once(root, st):
    three(root)
    p = plan_of(root, st, prefix="n_")
    outcomes = []

    def go():
        try:
            outcomes.append(runs.apply_plan(p, st).state)
        except PreflightError as e:
            outcomes.append(type(e).__name__)

    ts = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert outcomes.count("completed") == 1
    assert len(runs.list_runs(st, root)) == 1
    assert names_in(root) == ["n_a.txt", "n_b.txt", "n_c.txt"]
