"""Execution, journal-backed recovery and undo.

Safety model (not a database transaction; no power-loss guarantees):
  full pre-flight -> per item: re-check, journal `intent` (fsync), no-overwrite rename, journal `done`.
Anything unexpected stops the run. The journal decides what is known; ambiguity becomes `needs_review`.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from . import names, planner
from .errors import JournalError, PreflightError
from .planner import Plan, PlanItem
from .state import Journal, State, now_iso, read_events, root_id

UNRESOLVED = {"planned", "running", "undo_running", "interrupted"}


# ------------------------------------------------------------------ moving

def safe_move(src: str, dst: str) -> None:
    """Move a file WITHOUT overwriting. On Windows os.rename fails if the target exists
    (MoveFileEx without MOVEFILE_REPLACE_EXISTING). os.replace is never used for user files."""
    if os.name == "nt":
        os.rename(src, dst)
    else:  # pragma: no cover - fallback semantics for other platforms (unsupported in v1)
        os.link(src, dst)
        os.unlink(src)


@dataclass
class Hooks:
    """Fault-injection / test seams. Defaults do nothing."""
    pre_move: Callable[[str, int, str, str], None] | None = None   # (phase, op, src_abs, dst_abs) after intent
    move: Callable[[str, str], None] | None = None                 # replaces safe_move
    post_done: Callable[[str, int], None] | None = None            # after the done event
    journal_factory: Callable[[str], Journal] = Journal


# ------------------------------------------------------------------ run records

class Run:
    """A run directory: run.json (immutable metadata + plan snapshot) and journal.jsonl."""

    def __init__(self, directory: str):
        self.dir = directory
        with open(os.path.join(directory, "run.json"), "rb") as f:
            self.meta: dict[str, Any] = json.loads(f.read().decode("utf-8"))
        self.run_id: str = self.meta["run_id"]
        self.root: str = self.meta["root"]
        self.plan: Plan = planner.plan_from_dict(self.meta["plan"])
        self.ops: list[PlanItem] = self.plan.move_items
        self.refresh()

    @property
    def journal_path(self) -> str:
        return os.path.join(self.dir, "journal.jsonl")

    def refresh(self) -> None:
        self.events = read_events(self.journal_path)
        self.state = "planned"
        self.phase = "exec"
        self.exec: dict[int, str] = {}
        self.undo: dict[int, str] = {}
        self.mkdirs: list[str] = []
        self.notes: dict[tuple[str, int], str] = {}
        for ev in self.events:
            t = ev.get("type")
            if t == "state":
                self.state, self.phase = ev["state"], ev.get("phase", "exec")
            elif t == "intent":
                self.exec[ev["op"]] = "intent"
            elif t == "done":
                self.exec[ev["op"]] = "done"
            elif t == "failed":
                self.exec[ev["op"]] = "failed"
                self.notes[("exec", ev["op"])] = ev.get("error", "")
            elif t == "undo_intent":
                self.undo[ev["op"]] = "intent"
            elif t == "undo_done":
                self.undo[ev["op"]] = "done"
            elif t == "undo_failed":
                self.undo[ev["op"]] = "failed"
                self.notes[("undo", ev["op"])] = ev.get("error", "")
            elif t == "review":
                (self.exec if ev.get("phase", "exec") == "exec" else self.undo)[ev["op"]] = "review"
                self.notes[(ev.get("phase", "exec"), ev["op"])] = ev.get("reason", "")
            elif t == "mkdir" and ev.get("stage") == "intent" and ev["path"] not in self.mkdirs:
                self.mkdirs.append(ev["path"])

    @property
    def done_ops(self) -> list[int]:
        return [i for i, s in sorted(self.exec.items()) if s == "done"]

    @property
    def remaining_undo_ops(self) -> list[int]:
        return [i for i in self.done_ops if self.undo.get(i) != "done"]

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "root": self.root, "state": self.state,
            "created_at": self.meta.get("created_at"), "plan_id": self.plan.plan_id,
            "operations": len(self.ops), "moved": len(self.done_ops),
            "restored": sum(1 for i in self.done_ops if self.undo.get(i) == "done"),
        }


class BrokenRun:
    """A run directory whose run.json cannot be read. Surfaced as needs_review, never hidden."""

    broken = True

    def __init__(self, directory: str, error: str):
        self.dir = directory
        self.run_id = os.path.basename(directory)
        self.error = error
        self.root = _guess_root(directory)
        self.state = "needs_review"
        self.phase = "exec"
        self.ops: list[PlanItem] = []
        self.exec: dict[int, str] = {}
        self.undo: dict[int, str] = {}
        self.mkdirs: list[str] = []
        self.notes: dict[tuple[str, int], str] = {}

    @property
    def journal_path(self) -> str:
        return os.path.join(self.dir, "journal.jsonl")

    @property
    def done_ops(self) -> list[int]:
        return []

    @property
    def remaining_undo_ops(self) -> list[int]:
        return []

    def refresh(self) -> None:
        pass

    def summary(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "root": self.root, "state": self.state, "created_at": None,
                "plan_id": None, "operations": 0, "moved": 0, "restored": 0, "error": self.error}


def _guess_root(directory: str) -> str | None:
    """Best effort: the root recorded in a damaged run.json, or None when unknown."""
    try:
        with open(os.path.join(directory, "run.json"), "rb") as f:
            root = json.loads(f.read().decode("utf-8")).get("root")
        return root if isinstance(root, str) else None
    except (OSError, ValueError, AttributeError):
        return None


def list_runs(state: State, root: str | None = None) -> list[Run]:
    out: list[Run] = []
    if not os.path.isdir(state.runs_dir):
        return out
    rid = root_id(root) if root else None
    for name in sorted(os.listdir(state.runs_dir)):
        d = os.path.join(state.runs_dir, name)
        if not os.path.isfile(os.path.join(d, "run.json")):
            continue
        try:
            r = Run(d)
        except (OSError, ValueError, KeyError, TypeError, IndexError, PreflightError) as e:
            if not any(ev.get("type") == "intent" for ev in read_events(os.path.join(d, "journal.jsonl"))):
                continue  # no intent was ever journaled: nothing was moved, so nothing needs review
            r = BrokenRun(d, str(e) or type(e).__name__)  # unknown root: shown for every root
            if r.root is not None and rid is not None and root_id(r.root) != rid:
                continue
            out.append(r)
            continue
        if rid is None or root_id(r.root) == rid:
            out.append(r)
    out.sort(key=lambda r: r.run_id)
    return out


def find_run(state: State, run_id: str) -> Run:
    d = os.path.join(state.runs_dir, run_id)
    if (not run_id or run_id != os.path.basename(run_id) or not os.path.isfile(os.path.join(d, "run.json"))):
        raise PreflightError(f"Run not found: {run_id}. Use 'history --root ROOT' to list run ids.")
    return Run(d)


@dataclass
class RunResult:
    run_id: str | None
    state: str
    items: list[dict[str, str]] = field(default_factory=list)
    message: str = ""

    @property
    def counts(self) -> dict[str, int]:
        c = {"done": 0, "failed": 0, "not_run": 0}
        for i in self.items:
            c[i["status"]] = c.get(i["status"], 0) + 1
        return c

    @property
    def ok(self) -> bool:
        return self.state in ("completed", "undone")


class _Stop(Exception):
    def __init__(self, message: str, state: str = "partial_failed"):
        super().__init__(message)
        self.state = state


def _abs(root: str, rel: str) -> str:
    return names.abs_path(root, rel)


def _write_json_new(path: str, obj: Any) -> None:
    """Write atomically (temp file + rename) so a crash never leaves a truncated run.json."""
    tmp = path + ".tmp"
    with open(tmp, "xb") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8"))
        f.flush()
        os.fsync(f.fileno())
    try:
        # os.link never overwrites on any platform: it raises FileExistsError if path exists.
        os.link(tmp, path)
    finally:
        try:
            os.remove(tmp)  # drop the temp name after publishing, or on any failure
        except OSError:
            pass


def _try_state(j: Journal, state: str, phase: str = "exec") -> None:
    try:
        j.append({"type": "state", "state": state, "phase": phase})
    except JournalError:
        pass  # state stays 'running'; recovery will reconcile from the journal and the disk


# ------------------------------------------------------------------ apply

def apply_plan(plan: Plan, state: State, hooks: Hooks | None = None) -> RunResult:
    hooks = hooks or Hooks()
    root = names.check_root_dir(plan.root)
    with state.lock(root):
        _recover_root(state, root, hooks)
        _refuse_if_needs_review(state, root)
        planner.validate_for_apply(plan, state.path)
        moves = plan.move_items
        if not moves:
            return RunResult(None, "completed", [], "Nothing to move. No changes were made.")
        return _execute(plan, moves, root, state, hooks)


def _refuse_if_needs_review(state: State, root: str) -> None:
    bad = [r for r in list_runs(state, root) if r.state == "needs_review"]
    if bad:
        raise PreflightError(
            f"Run {bad[-1].run_id} needs manual review before new work can start. "
            "Run 'recover' for details, restore the files by hand if needed, then retry.")


def _execute(plan: Plan, moves: list[PlanItem], root: str, state: State, hooks: Hooks) -> RunResult:
    run_id = dt_id()
    run_dir = os.path.join(state.runs_dir, run_id)
    journal = hooks.journal_factory(os.path.join(run_dir, "journal.jsonl"))
    try:
        os.makedirs(run_dir)
        _write_json_new(os.path.join(run_dir, "run.json"), {
            "run_id": run_id, "root": root, "created_at": now_iso(), "tool": "fileorganizer 1.0.0",
            "plan": plan.to_dict(),
        })
        journal.open()
        journal.append({"type": "state", "state": "planned", "phase": "exec"})  # proves the log is writable
    except (OSError, JournalError) as e:
        journal.close()
        _discard_empty_run(run_dir)
        raise PreflightError(
            f"Cannot write the run log ({getattr(e, 'strerror', None) or e}). Nothing was moved. "
            "Check that the state folder is writable.") from e

    results = [{"src": m.src, "dst": m.dst, "status": "not_run", "error": ""} for m in moves]
    final = "completed"
    message = ""
    try:
        journal.append({"type": "state", "state": "running", "phase": "exec"})
        for i, it in enumerate(moves):
            try:
                _exec_one(root, i, it, journal, hooks)
                results[i]["status"] = "done"
            except _Stop as e:
                results[i]["status"] = "failed"
                results[i]["error"] = str(e)
                final, message = e.state, str(e)
                break
            except JournalError as e:
                results[i]["status"] = "failed"
                results[i]["error"] = str(e)
                final, message = "running", f"Run log failed, stopped before the next move: {e}"
                break
    except JournalError as e:
        final, message = "running", f"Run log failed before any move: {e}"
    if final != "running":
        _try_state(journal, final)
    journal.close()
    if final == "running":  # could not even record the stop; recovery reconciles on next start
        final_report = "interrupted"
    else:
        final_report = final
    return RunResult(run_id, final_report, results, message)


def dt_id() -> str:
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "-" + uuid.uuid4().hex[:6]


def _discard_empty_run(run_dir: str) -> None:
    """Remove a run directory we created that holds no useful data (only run.json/journal)."""
    try:
        for n in ("run.json", "run.json.tmp", "journal.jsonl"):
            p = os.path.join(run_dir, n)
            if os.path.isfile(p):
                os.remove(p)
        os.rmdir(run_dir)
    except OSError:
        pass


def _missing_dirs(root: str, rel: str) -> list[str]:
    parts = rel.split("/")[:-1]
    out = []
    for k in range(1, len(parts) + 1):
        d = "/".join(parts[:k])
        if not os.path.lexists(_abs(root, d)):
            out.append(d)
    return out


def _exec_one(root: str, i: int, it: PlanItem, j: Journal, hooks: Hooks) -> None:
    src, dst = _abs(root, it.src), _abs(root, it.dst)
    why = planner.verify_identity(src, it)
    if why:
        raise _Stop(f"{it.src}: {why}. Stopped; later files were not touched.")
    if os.path.lexists(dst):
        raise _Stop(f"{it.src}: target {it.dst} already exists. Stopped; later files were not touched.")
    link = names.check_no_links_below(root, it.dst)
    if link:
        raise _Stop(f"{it.src}: unsafe target path ({link}). Stopped.")
    made: list[str] = []
    try:
        for d in _missing_dirs(root, it.dst):
            j.append({"type": "mkdir", "stage": "intent", "path": d})
            try:
                os.mkdir(_abs(root, d))
            except OSError as e:
                raise _Stop(f"{it.src}: cannot create folder {d} ({e.strerror}). Stopped.") from e
            made.append(d)
            j.append({"type": "mkdir", "stage": "done", "path": d})
        j.append({"type": "intent", "op": i, "src": it.src, "dst": it.dst})
    except (JournalError, _Stop):
        _cleanup_dirs(root, made)
        raise
    if hooks.pre_move:
        hooks.pre_move("exec", i, src, dst)
    try:
        (hooks.move or safe_move)(src, dst)
    except OSError as e:
        msg = f"{it.src}: move failed ({e.strerror or e}). The file was not moved. Stopped; later files were not touched."
        _cleanup_dirs(root, made)
        try:
            j.append({"type": "failed", "op": i, "error": msg})
        except JournalError:
            pass
        raise _Stop(msg) from e
    try:
        j.append({"type": "done", "op": i})
    except JournalError as e:
        raise JournalError(f"{it.src} WAS moved to {it.dst} but the log write failed ({e}). "
                           "Stopped. Run 'recover' to verify and record it.") from e
    if hooks.post_done:
        hooks.post_done("exec", i)
    why = planner.verify_identity(dst, it)
    if why:
        j.append({"type": "review", "phase": "exec", "op": i, "reason": f"after move: {why}"})
        raise _Stop(f"{it.src}: after the move the target did not match the plan ({why}). "
                    f"Check {it.dst} manually.", "needs_review")


def _cleanup_dirs(root: str, made: list[str]) -> None:
    for d in reversed(made):
        p = _abs(root, d)
        try:
            if os.path.isdir(p) and not names.is_link(p) and not os.listdir(p):
                os.rmdir(p)
        except OSError:
            pass


# ------------------------------------------------------------------ recovery

def recover(state: State, root: str, hooks: Hooks | None = None) -> list[Run]:
    """Reconcile interrupted/needs_review runs of ``root``. Never moves files; only records findings."""
    root = names.check_root_dir(root)
    with state.lock(root):
        return _recover_root(state, root, hooks or Hooks())


def _recover_root(state: State, root: str, hooks: Hooks) -> list[Run]:
    changed: list[Run] = []
    for r in list_runs(state, root):
        if getattr(r, "broken", False):
            continue  # nothing to reconcile; stays needs_review until fixed by hand
        if r.state in UNRESOLVED or r.state == "needs_review":
            if _reconcile(r, root, hooks):
                changed.append(r)
    return changed


def _reconcile(r: Run, root: str, hooks: Hooks) -> bool:
    j = hooks.journal_factory(r.journal_path).open()
    try:
        changed = False
        prev = r.state
        phase = r.phase if prev in ("undo_running", "needs_review", "interrupted") else "exec"
        if prev in ("planned", "running", "undo_running"):
            j.append({"type": "state", "state": "interrupted", "phase": phase})
            changed = True
        status = r.undo if phase == "undo" else r.exec
        review = False
        for i, s in sorted((k, s) for k, s in status.items() if s in ("intent", "review")):
            it = r.ops[i]
            src, dst = _abs(root, it.src), _abs(root, it.dst)
            s_exists, d_exists = os.path.lexists(src), os.path.lexists(dst)
            src_ok = s_exists and planner.verify_identity(src, it) is None
            dst_ok = d_exists and planner.verify_identity(dst, it) is None
            if phase == "exec":
                if dst_ok and not s_exists:
                    j.append({"type": "done", "op": i, "recovered": True})
                elif src_ok and not d_exists:
                    j.append({"type": "failed", "op": i, "error": "recovered: the move did not happen"})
                else:
                    review = True
                    reason = _ambiguity(s_exists, d_exists, src_ok, dst_ok)
                    if not (s == "review" and r.notes.get(("exec", i)) == reason):
                        j.append({"type": "review", "phase": "exec", "op": i, "reason": reason})
                        changed = True
            else:
                if src_ok and not d_exists:
                    j.append({"type": "undo_done", "op": i, "recovered": True})
                elif dst_ok and not s_exists:
                    j.append({"type": "undo_failed", "op": i, "error": "recovered: the restore did not happen"})
                else:
                    review = True
                    reason = _ambiguity(s_exists, d_exists, src_ok, dst_ok)
                    if not (s == "review" and r.notes.get(("undo", i)) == reason):
                        j.append({"type": "review", "phase": "undo", "op": i, "reason": reason})
                        changed = True
        r.refresh()
        if review or any(s == "review" for s in (r.undo if phase == "undo" else r.exec).values()):
            final = "needs_review"
        elif phase == "undo":
            final = "undone" if not r.remaining_undo_ops else "undo_partial_failed"
        else:
            final = "completed" if len(r.done_ops) == len(r.ops) else "partial_failed"
        if final == "undone":
            _remove_created_dirs(root, r, j)  # an interrupted undo must not leave created folders behind
        if final != r.state:
            j.append({"type": "state", "state": final, "phase": phase})
            changed = True
        r.refresh()
        return changed
    finally:
        j.close()


def _ambiguity(s_exists: bool, d_exists: bool, src_ok: bool, dst_ok: bool) -> str:
    if s_exists and d_exists:
        return "file exists at both the source and the target"
    if not s_exists and not d_exists:
        return "file exists at neither the source nor the target"
    return "the file there does not match the planned size, time, identity or SHA-256"


def review_report(r: Run) -> list[str]:
    lines = []
    if getattr(r, "broken", False):
        return [f"Run {r.run_id}: its run.json cannot be read ({r.error}). Inspect the folder {r.dir} "
                "and the files under the root by hand; remove or repair the run folder when done."]
    for (phase, i), note in sorted(r.notes.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        status = (r.undo if phase == "undo" else r.exec).get(i)
        if status == "review":
            it = r.ops[i]
            lines.append(f"[{phase}] {it.src}  <->  {it.dst}: {note}. Inspect both locations under {r.root} "
                         "and put the file back at its original path by hand.")
    return lines


# ------------------------------------------------------------------ undo

def history(state: State, root: str) -> list[dict[str, Any]]:
    return [r.summary() for r in list_runs(state, root)]


def undo_run(state: State, run_id: str | None = None, root: str | None = None,
             hooks: Hooks | None = None) -> RunResult:
    hooks = hooks or Hooks()
    if run_id:
        try:
            root = find_run(state, run_id).root
        except (OSError, ValueError, KeyError, TypeError, IndexError) as e:
            raise PreflightError(f"Run {run_id} cannot be read ({e}). Inspect its run folder by hand, "
                                 "or undo by root once the broken run is removed.") from e
    if not root:
        raise PreflightError("Specify a run id or a root folder to undo.")
    root = names.check_root_dir(root)
    with state.lock(root):
        _recover_root(state, root, hooks)
        broken = [r for r in list_runs(state, root) if getattr(r, "broken", False)]
        if broken:
            raise PreflightError(
                f"Run {broken[-1].run_id} cannot be read, so the most recent run cannot be identified. "
                "Undo is refused until it is reviewed. Run 'recover' for details, inspect or remove "
                "the run folder by hand, then retry.")
        runs = [r for r in list_runs(state, root) if r.done_ops]
        pending = [r for r in runs if r.state != "undone"]
        if run_id:
            target = next((r for r in runs if r.run_id == run_id), None)
            if target is None:
                raise PreflightError(f"Run {run_id} moved no files, so there is nothing to undo.")
            if target.state == "undone":
                return RunResult(run_id, "undone", [], "This run was already undone. No changes were made.")
            if pending and pending[-1].run_id != run_id:
                raise PreflightError(
                    f"Only the most recent run can be undone. Undo {pending[-1].run_id} first.")
        else:
            if not pending:
                return RunResult(None, "undone", [], "Nothing to undo.")
            target = pending[-1]
        if target.state == "needs_review":
            raise PreflightError(f"Run {target.run_id} needs manual review first:\n  " +
                                 "\n  ".join(review_report(target)))
        return _undo(target, root, hooks)


def _undo(r: Run, root: str, hooks: Hooks) -> RunResult:
    order = list(reversed(r.remaining_undo_ops))
    problems: list[str] = []
    for i in order:
        it = r.ops[i]
        src, dst = _abs(root, it.src), _abs(root, it.dst)
        why = planner.verify_identity(dst, it)
        if why:
            problems.append(f"{it.dst}: {why}")
        if os.path.lexists(src):
            problems.append(f"{it.src}: original location is occupied")
        elif not os.path.isdir(os.path.dirname(src)):
            problems.append(f"{it.src}: original folder no longer exists")
        link = names.check_no_links_below(root, it.src) or names.check_no_links_below(root, it.dst)
        if link:
            problems.append(f"{it.src}: unsafe path ({link})")
    if problems:
        raise PreflightError(
            f"Undo refused: {len(problems)} problem(s). Nothing was changed. "
            "Restore or move away the listed items, then try again.", problems[:20])
    j = hooks.journal_factory(r.journal_path)
    try:
        j.open()
        j.append({"type": "state", "state": "undo_running", "phase": "undo"})
    except JournalError as e:
        j.close()
        raise PreflightError(f"Cannot write the run log ({e}). Nothing was changed.") from e
    results = [{"src": r.ops[i].dst, "dst": r.ops[i].src, "status": "not_run", "error": ""} for i in order]
    final, message = "undone", ""
    try:
        for n, i in enumerate(order):
            it = r.ops[i]
            try:
                _undo_one(root, i, it, j, hooks)
                results[n]["status"] = "done"
            except _Stop as e:
                results[n]["status"], results[n]["error"] = "failed", str(e)
                final, message = ("undo_partial_failed" if e.state == "partial_failed" else e.state), str(e)
                break
        if final == "undone":
            _remove_created_dirs(root, r, j)
    except JournalError as e:
        final, message = "undo_running", f"Run log failed; stopped. {e}"
    if final != "undo_running":
        _try_state(j, final, "undo")
    j.close()
    return RunResult(r.run_id, "interrupted" if final == "undo_running" else final, results, message)


def _undo_one(root: str, i: int, it: PlanItem, j: Journal, hooks: Hooks) -> None:
    src, dst = _abs(root, it.src), _abs(root, it.dst)
    why = planner.verify_identity(dst, it)
    if why:
        raise _Stop(f"{it.dst}: {why}. Undo stopped; remaining items were not touched.")
    if os.path.lexists(src):
        raise _Stop(f"{it.src}: original location is occupied. Undo stopped.")
    j.append({"type": "undo_intent", "op": i})
    if hooks.pre_move:
        hooks.pre_move("undo", i, dst, src)
    try:
        (hooks.move or safe_move)(dst, src)
    except OSError as e:
        msg = f"{it.dst}: restore failed ({e.strerror or e}). The file was not moved. Undo stopped; retry later."
        try:
            j.append({"type": "undo_failed", "op": i, "error": msg})
        except JournalError:
            pass
        raise _Stop(msg) from e
    try:
        j.append({"type": "undo_done", "op": i})
    except JournalError as e:
        raise JournalError(f"{it.dst} WAS restored to {it.src} but the log write failed ({e}). "
                           "Stopped. Run 'recover' to verify and record it.") from e
    if hooks.post_done:
        hooks.post_done("undo", i)
    why = planner.verify_identity(src, it)
    if why:
        j.append({"type": "review", "phase": "undo", "op": i, "reason": f"after restore: {why}"})
        raise _Stop(f"{it.src}: restored file did not match the plan ({why}). Check it manually.", "needs_review")


def _remove_created_dirs(root: str, r: Run, j: Journal) -> None:
    """Remove only folders this tool created for the run, and only if they are empty."""
    for d in reversed(r.mkdirs):
        p = _abs(root, d)
        if not os.path.isdir(p) or names.is_link(p):
            continue
        try:
            if os.listdir(p):
                j.append({"type": "rmdir", "path": d, "result": "kept (not empty)"})
                continue
            os.rmdir(p)
            j.append({"type": "rmdir", "path": d, "result": "removed"})
        except OSError:
            pass
