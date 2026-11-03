"""Regression tests for the Entire review round 1 findings."""

import csv
import os

import pytest

from conftest import mk
from fileorganizer import planner, runs, state as state_mod
from fileorganizer.errors import PreflightError
from fileorganizer.rules import Rules
from fileorganizer.state import RootLock, State


class Crash(BaseException):
    """Simulates the process dying at a chosen point."""


@pytest.fixture
def st(state):
    return State(state)


def plan_of(root, st, **kw):
    return planner.make_plan(root, Rules(**kw), st.path)


# ---- finding 4: dotfiles
def test_dotfiles_with_no_rules_are_not_conflicts(root):
    mk(root, {".env": "x", ".gitignore": "y", "a.txt": "z"})
    p = planner.make_plan(root, Rules())
    assert not p.blocked
    assert all(i.status == "ready" and i.action == "no_op" for i in p.items)


def test_dotfiles_classify_only_move_is_not_conflict(root):
    mk(root, {".env": "x"})
    p = planner.make_plan(root, Rules(classify="extension"))
    assert not p.blocked
    assert p.items[0].dst == "Organized/env/.env"


def test_empty_name_still_flagged_when_rules_empty_it(root):
    mk(root, {"abc": "x"})
    p = planner.make_plan(root, Rules(find="abc", replace=""))
    assert p.blocked and "empty" in p.items[0].reason


# ---- finding 2: lock
def test_lock_acquire_unwritable_state_raises_preflight(tmp_path, monkeypatch):
    def deny(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(state_mod.os, "makedirs", deny)
    with pytest.raises(PreflightError):
        RootLock(str(tmp_path / "locks" / "x.lock")).acquire()


def test_lock_open_failure_raises_preflight(tmp_path, monkeypatch):
    def deny(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(state_mod.os, "open", deny)
    with pytest.raises(PreflightError):
        RootLock(str(tmp_path / "x.lock")).acquire()


# ---- finding 1 + 7: duplicate review events, _reconcile return value
def _ambiguous_run(root, st):
    mk(root, {"a.txt": "AAA"})
    p = plan_of(root, st, prefix="n_")

    def crash(phase, i, src, dst):
        raise Crash()

    with pytest.raises(Crash):
        runs.apply_plan(p, st, runs.Hooks(pre_move=crash))
    os.remove(os.path.join(root, "a.txt"))  # neither source nor target exists now


def _review_events(st, root):
    r = runs.list_runs(st, root)[0]
    return [e for e in r.events if e.get("type") == "review"]


def test_reconcile_does_not_append_duplicate_review_events(root, st):
    _ambiguous_run(root, st)
    first = runs.recover(st, root)
    assert len(first) == 1
    assert runs.list_runs(st, root)[0].state == "needs_review"
    assert len(_review_events(st, root)) == 1
    n_events = len(runs.list_runs(st, root)[0].events)
    for _ in range(3):
        assert runs.recover(st, root) == []  # nothing changed -> not reported as changed
    assert len(_review_events(st, root)) == 1
    assert len(runs.list_runs(st, root)[0].events) == n_events


# ---- finding 3: interrupted undo leaves created dirs
@pytest.mark.parametrize("when", ["after_done", "after_last_move"])
def test_interrupted_undo_still_removes_created_dirs(root, st, when):
    mk(root, {"a.pdf": "A", "b.pdf": "B"})
    runs.apply_plan(plan_of(root, st, classify="extension"), st)
    assert os.path.isdir(os.path.join(root, "Organized", "pdf"))
    count = {"n": 0}

    if when == "after_done":
        def post_done(phase, i):
            count["n"] += 1
            if count["n"] == 2:
                raise Crash()
        hooks = runs.Hooks(post_done=post_done)
    else:
        def move(src, dst):
            runs.safe_move(src, dst)
            count["n"] += 1
            if count["n"] == 2:
                raise Crash()
        hooks = runs.Hooks(move=move)

    with pytest.raises(Crash):
        runs.undo_run(st, root=root, hooks=hooks)
    runs.recover(st, root)
    r = runs.list_runs(st, root)[0]
    assert r.state == "undone"
    assert not os.path.exists(os.path.join(root, "Organized"))
    assert sorted(os.listdir(root)) == ["a.pdf", "b.pdf"]


# ---- finding 8: unreadable runs
def _corrupt_run(root, st):
    mk(root, {"a.txt": "A"})
    runs.apply_plan(plan_of(root, st, prefix="n_"), st)
    r = runs.list_runs(st, root)[0]
    with open(os.path.join(r.dir, "run.json"), "wb") as f:
        f.write(b"{ not json")
    return r.run_id


def test_list_runs_surfaces_corrupt_run_as_needs_review(root, st):
    rid = _corrupt_run(root, st)
    found = runs.list_runs(st, root)
    assert [r.run_id for r in found] == [rid]
    assert found[0].state == "needs_review"
    assert runs.history(st, root)[0]["state"] == "needs_review"


def test_corrupt_run_blocks_new_apply(root, st):
    _corrupt_run(root, st)
    mk(root, {"b.txt": "B"})
    with pytest.raises(PreflightError, match="needs manual review"):
        runs.apply_plan(plan_of(root, st, prefix="m_"), st)
    runs.recover(st, root)  # must not crash on the broken run


def test_corrupt_run_is_reported_in_undo(root, st):
    _corrupt_run(root, st)
    assert runs.review_report(runs.list_runs(st, root)[0])


# ---- finding 11: CSV formula injection
@pytest.mark.parametrize("name", ["=SUM(1+1).txt", "+cmd.txt", "-x.txt", "@home.txt"])
def test_csv_export_neutralizes_formulas(root, tmp_path, st, name):
    mk(root, {name: "x"})
    p = plan_of(root, st, prefix="")
    p.items[0].reason = name  # reasons echo file names
    out = str(tmp_path / "out" / "plan.csv")
    planner.export_csv(p, out)
    with open(out, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    for cell in rows[1]:
        assert cell[:1] not in ("=", "+", "-", "@", "\t", "\r")
    assert rows[1][0] == "'" + name


def test_csv_export_leaves_normal_cells_unchanged(root, tmp_path, st):
    mk(root, {"a.txt": "x"})
    out = str(tmp_path / "out" / "plan.csv")
    planner.export_csv(plan_of(root, st, prefix="n_"), out)
    with open(out, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[1][0] == "a.txt" and rows[1][1] == "n_a.txt"


# ---- round 2: undo refuses on a broken run; harmless leftovers do not block
def test_undo_refuses_while_newest_run_is_corrupt(root, st):
    mk(root, {"a.txt": "A"})
    runs.apply_plan(plan_of(root, st, prefix="n_"), st)  # older, healthy run
    mk(root, {"b.txt": "B"})
    runs.apply_plan(plan_of(root, st, prefix="m_"), st)  # newest run
    newest = runs.list_runs(st, root)[-1]
    with open(os.path.join(newest.dir, "run.json"), "wb") as f:
        f.write(b"{ not json")
    before = sorted(os.listdir(root))
    with pytest.raises(PreflightError, match="cannot be read"):
        runs.undo_run(st, root=root)
    assert sorted(os.listdir(root)) == before  # the older run was NOT restored


def test_empty_run_json_without_intents_does_not_block_apply(root, st, tmp_path):
    leftover = os.path.join(st.runs_dir, "20260101T000000000000-abcdef")
    os.makedirs(leftover)
    open(os.path.join(leftover, "run.json"), "wb").close()  # empty, no journal
    mk(root, {"a.txt": "A"})
    assert runs.list_runs(st, root) == []
    res = runs.apply_plan(plan_of(root, st, prefix="n_"), st)
    assert res.state == "completed"
    other = str(tmp_path / "other")
    os.makedirs(other)
    mk(other, {"z.txt": "Z"})
    assert runs.apply_plan(plan_of(other, st, prefix="n_"), st).state == "completed"


def test_run_json_is_written_atomically(root, st, monkeypatch):
    mk(root, {"a.txt": "A"})
    real_rename = os.rename

    def boom(src, dst):
        if str(src).endswith("run.json.tmp"):
            raise Crash()
        return real_rename(src, dst)

    monkeypatch.setattr(runs.os, "rename", boom)
    with pytest.raises(Crash):
        runs.apply_plan(plan_of(root, st, prefix="n_"), st)
    monkeypatch.undo()
    assert runs.list_runs(st, root) == []  # no run.json at all, never a truncated one
    assert runs.apply_plan(plan_of(root, st, prefix="m_"), st).state == "completed"
