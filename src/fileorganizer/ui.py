"""tkinter desktop window. All file logic lives in the core (planner/runs); this module only wires widgets.

Four areas: Folder & Rules, Preview, Results, History & Undo.
Long tasks run on a worker thread; results come back through a queue polled on the Tk thread.
There is deliberately no "force cancel" button: a move in progress cannot be cancelled safely.
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from . import planner, runs
from .errors import FileOrganizerError, LockBusyError, PreflightError, RuleError
from .planner import Plan
from .rules import Rules, normalize_extensions
from .state import State

CLASSIFY_CHOICES = [("none", "No sorting"), ("extension", "By extension"),
                    ("month", "By modified month (UTC)")]


class Controller:
    """Widget-free state of the window: which preview is valid and whether a task is running."""

    def __init__(self, state: State):
        self.state = state
        self.plan: Plan | None = None
        self.generation = 0          # bumped on every input change; stale previews are discarded
        self.busy = False
        self._mutex = threading.Lock()

    def invalidate(self) -> None:
        self.generation += 1
        self.plan = None

    def build_plan(self, root: str, rules: Rules) -> Plan:
        plan = planner.make_plan(root, rules, self.state.path)
        planner.save_plan(plan, os.path.join(self.state.plans_dir, f"{plan.plan_id}.json"))
        return plan

    def accept(self, plan: Plan, generation: int) -> bool:
        if generation != self.generation:
            return False
        self.plan = plan
        return True

    @property
    def can_apply(self) -> bool:
        p = self.plan
        return p is not None and not self.busy and not p.blocked and p.summary.get("to_move", 0) > 0

    def begin(self) -> bool:
        with self._mutex:
            if self.busy:
                return False
            self.busy = True
            return True

    def end(self) -> None:
        with self._mutex:
            self.busy = False


def _error_text(e: BaseException) -> str:
    if isinstance(e, PreflightError):
        lines = [str(e)] + [f"- {p}" for p in e.problems[:10]]
        if len(e.problems) > 10:
            lines.append(f"- ... and {len(e.problems) - 10} more")
        return "\n".join(lines)
    if isinstance(e, FileOrganizerError):
        return str(e)
    if isinstance(e, OSError):
        return f"{e.strerror or e}. Check the path and permissions, then try again."
    return f"Unexpected error: {type(e).__name__}: {e}. Check History & Undo before trying again."


class App(tk.Tk):
    def __init__(self, state: State, confirm: Callable[[str, str], bool] | None = None,
                 notify: Callable[[str, str, str], None] | None = None):
        super().__init__()
        self.title("Safe File Organizer")
        self.ctl = Controller(state)
        self.confirm = confirm or (lambda title, msg: messagebox.askyesno(title, msg, parent=self))
        self.notify = notify or self._default_notify
        self._q: queue.Queue = queue.Queue()
        self._confirming = False
        self._undo_candidate: dict[str, Any] | None = None
        self._inputs: list[tuple[Any, str]] = []   # (widget, normal state)
        self._build()
        self._fit_to_content()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self._poll)

    # ------------------------------------------------------------- layout
    def _build(self) -> None:
        pad = {"padx": 6, "pady": 3}
        self.root_var = tk.StringVar()
        self.find_var, self.replace_var = tk.StringVar(), tk.StringVar()
        self.prefix_var, self.suffix_var = tk.StringVar(), tk.StringVar()
        self.numbering_var, self.recursive_var = tk.BooleanVar(), tk.BooleanVar()
        self.digits_var = tk.StringVar(value="3")
        self.ext_var = tk.StringVar()
        self.classify_var = tk.StringVar(value="none")
        self.summary_var = tk.StringVar(value="No preview yet. Choose a folder and click Preview.")
        self.results_var = tk.StringVar(value="No run yet.")
        self.status_var = tk.StringVar(value="Ready.")

        # 1. Folder & Rules
        fr = ttk.LabelFrame(self, text="1. Folder & Rules")
        fr.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(fr, text="Folder:").grid(row=0, column=0, sticky="e", **pad)
        self.root_entry = ttk.Entry(fr, textvariable=self.root_var, state="readonly", width=60)
        self.root_entry.grid(row=0, column=1, columnspan=6, sticky="we", **pad)
        self.browse_btn = ttk.Button(fr, text="Browse...", command=self.browse)
        self.browse_btn.grid(row=0, column=7, **pad)
        self._inputs += [(self.root_entry, "readonly"), (self.browse_btn, "normal")]

        def entry(row, col, label, var, width=18):
            ttk.Label(fr, text=label).grid(row=row, column=col, sticky="e", **pad)
            e = ttk.Entry(fr, textvariable=var, width=width)
            e.grid(row=row, column=col + 1, sticky="w", **pad)
            self._inputs.append((e, "normal"))
            return e

        self.find_entry = entry(1, 0, "Find (exact text):", self.find_var)
        self.replace_entry = entry(1, 2, "Replace with:", self.replace_var)
        self.prefix_entry = entry(1, 4, "Prefix:", self.prefix_var)
        self.suffix_entry = entry(1, 6, "Suffix:", self.suffix_var, 12)

        self.numbering_chk = ttk.Checkbutton(fr, text="Add number _NNN", variable=self.numbering_var)
        self.numbering_chk.grid(row=2, column=1, sticky="w", **pad)
        ttk.Label(fr, text="Digits:").grid(row=2, column=2, sticky="e", **pad)
        self.digits_spin = ttk.Spinbox(fr, from_=1, to=10, textvariable=self.digits_var, width=5)
        self.digits_spin.grid(row=2, column=3, sticky="w", **pad)
        self.recursive_chk = ttk.Checkbutton(fr, text="Include sub folders", variable=self.recursive_var)
        self.recursive_chk.grid(row=2, column=4, columnspan=2, sticky="w", **pad)
        self._inputs += [(self.numbering_chk, "normal"), (self.digits_spin, "normal"),
                         (self.recursive_chk, "normal")]
        self.ext_entry = entry(2, 6, "Only types:", self.ext_var, 12)

        ttk.Label(fr, text="Sort into Organized\\:").grid(row=3, column=0, sticky="e", **pad)
        self.classify_radios = []
        for n, (value, label) in enumerate(CLASSIFY_CHOICES):
            rb = ttk.Radiobutton(fr, text=label, value=value, variable=self.classify_var)
            rb.grid(row=3, column=1 + n * 2, columnspan=2, sticky="w", **pad)
            self.classify_radios.append(rb)
            self._inputs.append((rb, "normal"))

        ttk.Label(fr, foreground="#555", text=(
            "Order: replace text in the name, then prefix/suffix, then number. Find is literal and "
            "case-sensitive. Only types: e.g. pdf, jpg (empty = all).")).grid(
            row=4, column=0, columnspan=7, sticky="w", **pad)
        self.preview_btn = ttk.Button(fr, text="Preview", command=self.preview)
        self.preview_btn.grid(row=4, column=7, **pad)
        fr.columnconfigure(1, weight=1)

        # 2. Preview
        pv = ttk.LabelFrame(self, text="2. Preview")
        pv.pack(fill="both", expand=True, padx=8, pady=4)
        f, self.preview_tree = self._tree(pv, ("Source", "Target", "Action", "Status", "Reason"),
                                          (240, 300, 110, 75, 300), 10)
        self.preview_tree.tag_configure("conflict", foreground="#b00020")
        self.preview_tree.tag_configure("skipped", foreground="#777777")
        f.pack(fill="both", expand=True, padx=6, pady=3)
        bar = ttk.Frame(pv)
        bar.pack(fill="x", padx=6, pady=3)
        ttk.Label(bar, textvariable=self.summary_var).pack(side="left")
        self.apply_btn = ttk.Button(bar, text="Apply...", command=self.apply)
        self.apply_btn.pack(side="right", padx=3)
        self.export_json_btn = ttk.Button(bar, text="Export JSON...", command=lambda: self.export("json"))
        self.export_json_btn.pack(side="right", padx=3)
        self.export_csv_btn = ttk.Button(bar, text="Export CSV...", command=lambda: self.export("csv"))
        self.export_csv_btn.pack(side="right", padx=3)

        bottom = ttk.Frame(self)
        bottom.pack(fill="both", expand=True, padx=8, pady=4)
        # 3. Results
        rs = ttk.LabelFrame(bottom, text="3. Results")
        rs.pack(side="left", fill="both", expand=True, padx=(0, 4))
        f, self.results_tree = self._tree(rs, ("From", "To", "Status", "Error"), (140, 160, 60, 120), 6)
        self.results_tree.tag_configure("failed", foreground="#b00020")
        self.results_tree.tag_configure("not_run", foreground="#777777")
        f.pack(fill="both", expand=True, padx=6, pady=3)
        ttk.Label(rs, textvariable=self.results_var, wraplength=520, justify="left").pack(
            fill="x", padx=6, pady=3)
        # 4. History & Undo
        hs = ttk.LabelFrame(bottom, text="4. History & Undo")
        hs.pack(side="left", fill="both", expand=True, padx=(4, 0))
        f, self.history_tree = self._tree(hs, ("Run", "State", "Moved", "Restored", "Created (UTC)"),
                                          (160, 100, 50, 55, 120), 4)
        f.pack(fill="both", expand=True, padx=6, pady=3)
        hb = ttk.Frame(hs)
        hb.pack(fill="x", padx=6)
        self.refresh_btn = ttk.Button(hb, text="Check / Refresh", command=self.refresh_history)
        self.refresh_btn.pack(side="left", padx=3)
        self.undo_btn = ttk.Button(hb, text="Undo latest run...", command=self.undo)
        self.undo_btn.pack(side="left", padx=3)
        self.review_text = tk.Text(hs, height=4, wrap="word", state="disabled")
        self.review_text.pack(fill="x", padx=6, pady=3)

        ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w").pack(fill="x", side="bottom")

        for v in (self.find_var, self.replace_var, self.prefix_var, self.suffix_var, self.numbering_var,
                  self.recursive_var, self.digits_var, self.ext_var, self.classify_var):
            v.trace_add("write", self._on_input_change)
        self.root_var.trace_add("write", self._on_root_change)
        self._update_buttons()

    def _fit_to_content(self) -> None:
        """Open large enough for every control (fonts scale with Windows display settings)."""
        self.update_idletasks()
        w = min(max(self.winfo_reqwidth(), 1100), self.winfo_screenwidth() - 40)
        h = min(max(self.winfo_reqheight(), 760), self.winfo_screenheight() - 80)
        self.geometry(f"{w}x{h}")
        self.minsize(min(w, 1000), min(h, 700))

    def _tree(self, parent, cols, widths, height):
        frame = ttk.Frame(parent)
        tree = ttk.Treeview(frame, columns=cols, show="headings", height=height)
        for c, w in zip(cols, widths):
            tree.heading(c, text=c)
            tree.column(c, width=w, stretch=True, anchor="w")
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return frame, tree

    # ------------------------------------------------------------- state helpers
    def _default_notify(self, kind: str, title: str, msg: str) -> None:
        {"error": messagebox.showerror, "warning": messagebox.showwarning}.get(kind, messagebox.showinfo)(
            title, msg, parent=self)

    def _error(self, e: BaseException) -> None:
        text = _error_text(e)
        self.status_var.set(text.splitlines()[0])
        self.notify("error", "Safe File Organizer", text)

    def _set_busy(self, busy: bool) -> None:
        for w, normal in self._inputs:
            w.configure(state="disabled" if busy else normal)
        self._update_buttons()

    def _set_state(self, w, enabled: bool) -> None:
        w.configure(state="normal" if enabled else "disabled")

    def _update_buttons(self) -> None:
        idle = not self.ctl.busy
        self._set_state(self.preview_btn, idle)
        self._set_state(self.apply_btn, self.ctl.can_apply)
        self._set_state(self.export_csv_btn, idle and self.ctl.plan is not None)
        self._set_state(self.export_json_btn, idle and self.ctl.plan is not None)
        self._set_state(self.refresh_btn, idle and bool(self.root_var.get()))
        self._set_state(self.undo_btn, idle and self._undo_candidate is not None)

    def _clear(self, tree) -> None:
        tree.delete(*tree.get_children())

    def _on_input_change(self, *_):
        self.ctl.invalidate()
        self._clear(self.preview_tree)
        self.summary_var.set("Rules or folder changed. Click Preview to see the new plan.")
        self._update_buttons()

    def _on_root_change(self, *_):
        self._on_input_change()
        self._undo_candidate = None
        self._clear(self.history_tree)
        self._update_buttons()
        self.after_idle(self.refresh_history)

    def read_rules(self) -> Rules:
        try:
            digits = int(self.digits_var.get().strip())
        except ValueError as e:
            raise RuleError("Digits must be a whole number from 1 to 10.") from e
        exts = self.ext_var.get().replace(";", ",").replace(" ", ",").split(",")
        return Rules(find=self.find_var.get(), replace=self.replace_var.get(), prefix=self.prefix_var.get(),
                     suffix=self.suffix_var.get(), numbering=bool(self.numbering_var.get()), digits=digits,
                     classify=self.classify_var.get(), recursive=bool(self.recursive_var.get()),
                     extensions=normalize_extensions(exts)).validate()

    def _run_bg(self, label: str, fn: Callable[[], Any], done: Callable[[Any, BaseException | None], None]) -> bool:
        if not self.ctl.begin():
            return False
        self._set_busy(True)
        self.status_var.set(f"{label}... please wait.")

        def work():
            try:
                res, err = fn(), None
            except BaseException as e:  # noqa: BLE001 - reported to the user on the Tk thread
                res, err = None, e
            self._q.put((done, res, err))

        threading.Thread(target=work, name=f"fo-{label}").start()  # non-daemon: a move always finishes
        return True

    def _poll(self) -> None:
        try:
            while True:
                done, res, err = self._q.get_nowait()
                self.ctl.end()
                self._set_busy(False)
                self.status_var.set("Ready.")
                try:
                    done(res, err)
                except Exception as e:  # noqa: BLE001
                    self._error(e)
        except queue.Empty:
            pass
        try:
            self.after(50, self._poll)
        except tk.TclError:
            pass

    def _on_close(self) -> None:
        if self.ctl.busy:
            self.notify("info", "Safe File Organizer", "A task is running. Wait for it to finish before closing.")
            return
        self.destroy()

    # ------------------------------------------------------------- actions
    def browse(self) -> None:
        path = filedialog.askdirectory(parent=self, title="Choose the folder to organize", mustexist=True)
        if path:
            self.root_var.set(os.path.abspath(path))

    def preview(self) -> None:
        if self.ctl.busy:
            return
        root = self.root_var.get().strip()
        if not root:
            self._error(PreflightError("Choose a folder first."))
            return
        try:
            rules = self.read_rules()
        except FileOrganizerError as e:
            self._error(e)
            return
        gen = self.ctl.generation
        self._run_bg("Scanning", lambda: self.ctl.build_plan(root, rules),
                     lambda plan, err: self._preview_done(plan, err, gen))

    def _preview_done(self, plan: Plan | None, err: BaseException | None, gen: int) -> None:
        if err is not None:
            self._error(err)
            return
        if not self.ctl.accept(plan, gen):
            self.summary_var.set("Rules or folder changed while scanning. Click Preview again.")
            self._update_buttons()
            return
        self._clear(self.preview_tree)
        for n, it in enumerate(plan.items):
            tag = it.status if it.status in ("conflict", "skipped") else ""
            self.preview_tree.insert("", "end", iid=str(n), values=(it.src, it.dst, it.action, it.status, it.reason),
                                     tags=(tag,))
        s = plan.summary
        text = (f"Scanned {s['total']}: ready {s['ready']} (to move {s['to_move']}, unchanged {s['no_op']}), "
                f"conflict {s['conflict']}, skipped {s['skipped']}.")
        if plan.blocked:
            text += " Apply is disabled: fix the conflicts and preview again."
        elif s["to_move"] == 0:
            text += " Nothing to move."
        self.summary_var.set(text)
        self._update_buttons()

    def apply(self) -> None:
        plan = self.ctl.plan
        if self._confirming or plan is None or not self.ctl.can_apply:
            return
        n = plan.summary["to_move"]
        self._confirming = True
        try:
            ok = self.confirm("Confirm Apply", f"Move or rename {n} file(s) in this folder?\n\n{plan.root}\n\n"
                                               "You can undo this run later in History & Undo.")
        finally:
            self._confirming = False
        if not ok or self.ctl.plan is not plan or not self.ctl.can_apply:
            return
        self._run_bg("Applying", lambda: runs.apply_plan(plan, self.ctl.state), self._apply_done)

    def _plan_used(self) -> None:
        self.ctl.invalidate()
        self.summary_var.set("Files changed. Click Preview to make a new plan.")
        self._update_buttons()

    def _apply_done(self, res: runs.RunResult | None, err: BaseException | None) -> None:
        self._plan_used()
        if err is not None:
            self._error(err)
        else:
            self._show_results(res, "Apply")
        self.refresh_history()

    def _show_results(self, res: runs.RunResult, label: str) -> None:
        self._clear(self.results_tree)
        for n, i in enumerate(res.items):
            self.results_tree.insert("", "end", iid=str(n), values=(i["src"], i["dst"], i["status"], i["error"]),
                                     tags=(i["status"],))
        c = res.counts
        text = f"{label}: {res.state}. Done {c['done']}, failed {c['failed']}, not run {c['not_run']}."
        if res.run_id:
            text += f" Run {res.run_id}."
        if res.message:
            text += f" {res.message}"
        self.results_var.set(text)
        if not res.ok:
            self.notify("warning", "Safe File Organizer", text)

    def refresh_history(self) -> None:
        root = self.root_var.get().strip()
        if not root:
            return
        state = self.ctl.state

        def work():
            try:
                runs.recover(state, root)  # only checks interrupted runs; never moves files
            except LockBusyError:
                pass  # another task is using the folder; show what the logs say
            return [(r.summary(), runs.review_report(r) if r.state == "needs_review" else [])
                    for r in runs.list_runs(state, root)]

        self._run_bg("Checking history", work, self._history_done)

    def _history_done(self, rows, err: BaseException | None) -> None:
        self._clear(self.history_tree)
        self._undo_candidate = None
        if err is not None:
            self._update_buttons()
            self._error(err)
            return
        review: list[str] = []
        for n, (s, lines) in enumerate(reversed(rows)):
            self.history_tree.insert("", "end", iid=str(n), values=(
                s["run_id"], s["state"], f"{s['moved']}/{s['operations']}", s["restored"], s["created_at"]))
            review += [f"{s['run_id']}: {x}" for x in lines]
        pending = [s for s, _ in rows if s["moved"] > 0 and s["state"] != "undone"]
        self._undo_candidate = pending[-1] if pending else None
        self.review_text.configure(state="normal")
        self.review_text.delete("1.0", "end")
        self.review_text.insert("1.0", "\n".join(review) if review else
                                ("No runs need review." if rows else "No runs for this folder yet."))
        self.review_text.configure(state="disabled")
        self._update_buttons()

    def undo(self) -> None:
        cand = self._undo_candidate
        if self._confirming or cand is None or self.ctl.busy:
            return
        self._confirming = True
        try:
            ok = self.confirm("Confirm Undo", f"Undo run {cand['run_id']}?\n\nMove "
                                              f"{cand['moved'] - cand['restored']} file(s) back to their original "
                                              f"paths in:\n{cand['root']}")
        finally:
            self._confirming = False
        if not ok:
            return
        self._run_bg("Undoing", lambda: runs.undo_run(self.ctl.state, run_id=cand["run_id"]), self._undo_done)

    def _undo_done(self, res: runs.RunResult | None, err: BaseException | None) -> None:
        self._plan_used()
        if err is not None:
            self._error(err)
        else:
            self._show_results(res, "Undo")
        self.refresh_history()

    def export(self, kind: str, path: str | None = None) -> None:
        plan = self.ctl.plan
        if plan is None or self.ctl.busy:
            return
        if path is None:
            ext = ".csv" if kind == "csv" else ".json"
            path = filedialog.asksaveasfilename(parent=self, defaultextension=ext, title="Export plan",
                                                filetypes=[(kind.upper(), f"*{ext}")])
            if not path:
                return
        try:
            overwrite = os.path.exists(path)  # the save dialog already asked before replacing
            if kind == "csv":
                planner.export_csv(plan, path, overwrite=overwrite)
            else:
                planner.save_plan(plan, path, overwrite=overwrite)
            self.status_var.set(f"Exported to {path}")
        except (FileOrganizerError, OSError) as e:
            self._error(e)


def launch(state: State) -> None:
    App(state).mainloop()
