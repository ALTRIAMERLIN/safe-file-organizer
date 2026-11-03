"""Plan generation, conflict detection, plan I/O and validation. Plans are plain data."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from . import names
from .errors import PreflightError, RuleError
from .rules import Rules
from .scanner import ORGANIZED, ext_of, scan

SCHEMA_VERSION = 1
ACTIONS = ("rename", "move", "move_and_rename", "no_op")
STATUSES = ("ready", "conflict", "skipped")


@dataclass
class PlanItem:
    src: str
    dst: str
    action: str
    status: str
    reason: str = ""
    size: int = 0
    mtime_ns: int = 0
    file_id: str = ""
    sha256: str = ""

    @property
    def moves(self) -> bool:
        return self.status == "ready" and self.action != "no_op"


@dataclass
class Plan:
    schema_version: int
    plan_id: str
    created_at: str
    root: str
    rules: dict[str, Any]
    items: list[PlanItem] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)
    digest: str = ""

    @property
    def blocked(self) -> bool:
        return self.summary.get("conflict", 0) > 0

    @property
    def move_items(self) -> list[PlanItem]:
        return [i for i in self.items if i.moves]

    def mapping(self) -> list[tuple[str, str, str, str]]:
        """Deterministic mapping (no ids/timestamps) used for equality checks."""
        return [(i.src, i.dst, i.action, i.status) for i in self.items]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "created_at": self.created_at,
            "root": self.root,
            "rules": self.rules,
            "items": [vars(i).copy() for i in self.items],
            "summary": self.summary,
            "digest": self.digest,
        }


# ---------------------------------------------------------------- conflicts

def detect_conflicts(root: str, specs: list[tuple[str, str]]) -> list[list[str]]:
    """specs: [(src_rel, dst_rel)] for every included file (src == dst means it stays).

    Returns, per spec, the list of conflict reasons (empty = OK). Single implementation shared by
    planning and by pre-execution re-validation. All comparisons use casefold.
    """
    reasons: list[list[str]] = [[] for _ in specs]
    src_keys = {names.key(s): i for i, (s, _d) in enumerate(specs)}
    moving = [d != s for s, d in specs]
    dst_count = Counter(names.key(d) for (s, d), m in zip(specs, moving) if m)
    dst_keys = set(dst_count)
    root_cmp = names.path_key(root)

    for i, (s, d) in enumerate(specs):
        if not moving[i]:
            continue
        r = reasons[i]
        try:
            parts = names.split_rel(d)
        except ValueError as e:
            r.append(f"invalid target: {e}")
            continue
        if names.key(d) == names.key(s):
            r.append("case-only rename is not supported")
            continue
        if dst_count[names.key(d)] > 1:
            r.append("another file maps to the same target")
        j = src_keys.get(names.key(d))
        target = names.abs_path(root, d)
        if j is not None and j != i and moving[j]:
            r.append("target is the current path of another file that is also moving (swap or cycle)")
        elif j is not None and j != i:
            r.append("target already exists")
        elif os.path.lexists(target):
            r.append("target already exists")
        for k in range(1, len(parts)):
            anc = "/".join(parts[:k])
            ak = names.key(anc)
            if ak in src_keys or ak in dst_keys:
                r.append(f"parent path '{anc}' is a file")
                break
            ap = names.abs_path(root, anc)
            if os.path.lexists(ap) and not os.path.isdir(ap):
                r.append(f"parent path '{anc}' is a file")
                break
        link_reason = names.check_no_links_below(root, d)
        if link_reason:
            r.append(f"unsafe target path: {link_reason}")
        link_reason = names.check_no_links_below(root, s)
        if link_reason:
            r.append(f"unsafe source path: {link_reason}")
        if len(target) >= names.MAX_PATH_LEN:
            r.append(f"target path is {len(target)} characters; paths of {names.MAX_PATH_LEN}+ are not supported")
        if not names.is_within(root_cmp, target):
            r.append("target is outside the root folder")
    return reasons


# ---------------------------------------------------------------- planning

def _utc_month(mtime_ns: int) -> str:
    d = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(microseconds=mtime_ns // 1000)
    return f"{d.year:04d}-{d.month:02d}"


def _split_dir(rel: str) -> tuple[str, str]:
    i = rel.rfind("/")
    return ("", rel) if i < 0 else (rel[:i], rel[i + 1:])


def make_plan(root: str, rules: Rules, state_dir: str | None = None) -> Plan:
    rules.validate()
    root = names.check_root_dir(root)
    if rules.classify != "none":
        org = os.path.join(root, ORGANIZED)
        if os.path.lexists(org) and names.is_link(org):
            raise PreflightError("The 'Organized' folder is a link/junction. Remove or rename it, then preview again.")
    entries = sorted(scan(root, rules, state_dir), key=lambda e: (e.rel.casefold(), e.rel))
    included = [e for e in entries if e.status == "included"]
    number = {e.rel: n for n, e in enumerate(included, start=1)}  # already in (casefold, rel) order

    items: list[PlanItem] = []
    incl_idx: list[int] = []
    pre: dict[int, str] = {}
    for e in entries:
        if e.status == "skipped":
            items.append(PlanItem(e.rel, e.rel, "no_op", "skipped", e.reason, e.size, e.mtime_ns))
            continue
        if e.status == "error":
            items.append(PlanItem(e.rel, e.rel, "no_op", "conflict", f"read error: {e.reason}",
                                  e.size, e.mtime_ns))
            continue
        src_dir, name = _split_dir(e.rel)
        stem, ext = ext_of(name)
        orig_stem = stem
        if rules.find:
            stem = stem.replace(rules.find, rules.replace)
        main = rules.prefix + stem + rules.suffix
        if rules.numbering:
            main += f"_{number[e.rel]:0{rules.digits}d}"
        new_name = main if ext is None else f"{main}.{ext}"
        idx = len(items)
        if main == "" and orig_stem != "":  # dotfiles (".env") legitimately have an empty stem
            pre[idx] = "new file name would be empty"
        if rules.classify == "extension":
            sub = "no_extension" if not ext else ext.lower()
            dst_dir = f"{ORGANIZED}/{sub}"
        elif rules.classify == "month":
            dst_dir = f"{ORGANIZED}/{_utc_month(e.mtime_ns)}"
        else:
            dst_dir = src_dir
        dst = f"{dst_dir}/{new_name}" if dst_dir else new_name
        if dst == e.rel:
            action = "no_op"
            reason = "no rules configured" if rules.is_noop else "name and location unchanged"
        else:
            same_dir, same_name = dst_dir == src_dir, new_name == name
            action = "rename" if same_dir else ("move" if same_name else "move_and_rename")
            reason = {"rename": "Rename in place", "move": f"Move to {dst_dir}",
                      "move_and_rename": f"Rename and move to {dst_dir}"}[action]
        incl_idx.append(idx)
        items.append(PlanItem(e.rel, dst, action, "ready", reason, e.size, e.mtime_ns, e.file_id, e.sha256))

    found = detect_conflicts(root, [(items[i].src, items[i].dst) for i in incl_idx])
    for pos, i in enumerate(incl_idx):
        rs = ([pre[i]] if i in pre else []) + found[pos]
        if rs:
            items[i].status = "conflict"
            items[i].reason = "; ".join(rs)

    plan = Plan(SCHEMA_VERSION, uuid.uuid4().hex, _now(), root, rules.to_dict(), items)
    plan.summary = summarize(items)
    plan.digest = compute_digest(plan)
    return plan


def summarize(items: list[PlanItem]) -> dict[str, int]:
    return {
        "total": len(items),
        "ready": sum(i.status == "ready" for i in items),
        "conflict": sum(i.status == "conflict" for i in items),
        "skipped": sum(i.status == "skipped" for i in items),
        "to_move": sum(i.moves for i in items),
        "no_op": sum(i.status == "ready" and i.action == "no_op" for i in items),
    }


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def compute_digest(plan: Plan) -> str:
    body = {
        "schema_version": plan.schema_version,
        "root": plan.root,
        "rules": plan.rules,
        "items": [vars(i) for i in plan.items],
    }
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------- plan I/O

def _write_new(path: str, data: bytes, overwrite: bool) -> None:
    """Write via temp file; never replaces an existing file unless overwrite=True."""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    if os.path.lexists(path) and not overwrite:
        raise PreflightError(f"Output file already exists: {path}. Choose another name or pass --force.")
    tmp = f"{path}.{uuid.uuid4().hex[:8]}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    if overwrite:
        os.replace(tmp, path)  # only ever used on our own output files
    else:
        try:
            os.rename(tmp, path)
        except OSError:
            os.remove(tmp)
            raise


def _check_outside_root(plan: Plan, path: str) -> None:
    if names.is_within(plan.root, path):
        raise PreflightError("Output path is inside the source folder. Save plans and exports outside it.")


def save_plan(plan: Plan, path: str, overwrite: bool = False) -> None:
    _check_outside_root(plan, path)
    data = json.dumps(plan.to_dict(), ensure_ascii=False, indent=2).encode("utf-8")
    _write_new(path, data, overwrite)


def _csv_safe(v: Any) -> Any:
    """Neutralize spreadsheet formula injection: prefix risky text cells with an apostrophe."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "\x27" + v
    return v


def export_csv(plan: Plan, path: str, overwrite: bool = False) -> None:
    _check_outside_root(plan, path)
    import io
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["source", "target", "action", "status", "reason", "size", "sha256"])
    for i in plan.items:
        w.writerow([_csv_safe(c) for c in (i.src, i.dst, i.action, i.status, i.reason, i.size, i.sha256)])
    _write_new(path, buf.getvalue().encode("utf-8-sig"), overwrite)  # BOM so Excel shows CJK correctly


def _bad(msg: str) -> PreflightError:
    return PreflightError(f"Invalid plan file: {msg}. Create a new plan with 'plan'.")


def plan_from_dict(data: Any) -> Plan:
    if not isinstance(data, dict):
        raise _bad("top level must be an object")
    need = {"schema_version", "plan_id", "created_at", "root", "rules", "items", "summary", "digest"}
    if need - set(data):
        raise _bad(f"missing keys {sorted(need - set(data))}")
    if data["schema_version"] != SCHEMA_VERSION:
        raise _bad(f"unsupported schema_version {data['schema_version']!r}")
    for k in ("plan_id", "created_at", "root", "digest"):
        if not isinstance(data[k], str):
            raise _bad(f"'{k}' must be text")
    try:
        Rules.from_dict(data["rules"])
    except RuleError as e:
        raise _bad(str(e)) from e
    if not isinstance(data["items"], list) or not isinstance(data["summary"], dict):
        raise _bad("'items' must be a list and 'summary' an object")
    fields = {"src": str, "dst": str, "action": str, "status": str, "reason": str,
              "size": int, "mtime_ns": int, "file_id": str, "sha256": str}
    items = []
    for n, raw in enumerate(data["items"]):
        if not isinstance(raw, dict) or set(raw) != set(fields):
            raise _bad(f"item {n} has wrong keys")
        for k, t in fields.items():
            if not isinstance(raw[k], t) or isinstance(raw[k], bool):
                raise _bad(f"item {n} field '{k}' has wrong type")
        if raw["action"] not in ACTIONS or raw["status"] not in STATUSES:
            raise _bad(f"item {n} has unknown action or status")
        items.append(PlanItem(**raw))
    return Plan(data["schema_version"], data["plan_id"], data["created_at"], data["root"],
                data["rules"], items, data["summary"], data["digest"])


def load_plan(path: str) -> Plan:
    try:
        with open(path, "rb") as f:
            data = json.loads(f.read().decode("utf-8"))
    except FileNotFoundError as e:
        raise PreflightError(f"Plan file not found: {path}. Check the path.") from e
    except (OSError, ValueError) as e:
        raise _bad(f"cannot read JSON ({e})") from e
    return plan_from_dict(data)


# ---------------------------------------------------------------- validation

def verify_identity(path: str, item: PlanItem) -> str | None:
    """Compare the file at ``path`` with the planned identity. Returns a reason or None."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return "file is missing"
    except OSError as e:
        return f"cannot read file: {e.strerror}"
    if names.is_link_st(st):
        return "path is now a link"
    if not os.path.isfile(path):
        return "not a regular file"
    if st.st_nlink > 1:
        return "file has hard links"
    if st.st_size != item.size:
        return "file size changed"
    if st.st_mtime_ns != item.mtime_ns:
        return "file modified time changed"
    if names.file_id(st) != item.file_id:
        return "file was replaced (different file identity)"
    try:
        if names.sha256_file(path) != item.sha256:
            return "file content changed (SHA-256 differs)"
    except OSError as e:
        return f"cannot read file: {e.strerror}"
    return None


def validate_for_apply(plan: Plan, state_dir: str | None = None) -> None:
    """Full pre-execution validation. Raises PreflightError listing every problem; touches nothing."""
    if compute_digest(plan) != plan.digest:
        raise PreflightError("Plan digest does not match its contents (file edited or damaged). "
                             "Create a new plan with 'plan'.")
    root = names.check_root_dir(plan.root)
    problems: list[str] = []
    state_key = names.path_key(state_dir) if state_dir else None
    specs: list[tuple[str, str]] = []
    spec_items: list[PlanItem] = []
    seen_src: set[str] = set()
    for it in plan.items:
        try:
            names.split_rel(it.src)
            names.split_rel(it.dst)
        except ValueError as e:
            problems.append(f"{it.src}: unsafe path in plan ({e})")
            continue
        if names.key(it.src) in seen_src:
            problems.append(f"{it.src}: listed more than once")
        seen_src.add(names.key(it.src))
        if it.status == "conflict":
            problems.append(f"{it.src}: conflict - {it.reason}")
            continue
        if it.status == "skipped":
            continue
        if (it.action == "no_op") != (it.src == it.dst):
            problems.append(f"{it.src}: action does not match source and target")
            continue
        if state_key and (names.is_within(state_key, names.abs_path(root, it.src))
                          or names.is_within(state_key, names.abs_path(root, it.dst))):
            problems.append(f"{it.src}: path is inside the application state folder")
            continue
        specs.append((it.src, it.dst))
        spec_items.append(it)
    if not problems:
        for it, rs in zip(spec_items, detect_conflicts(root, specs)):
            for r in rs:
                problems.append(f"{it.src}: {r}")
        for it in spec_items:
            if it.moves:
                why = verify_identity(names.abs_path(root, it.src), it)
                if why:
                    problems.append(f"{it.src}: {why}")
    if problems:
        shown = problems[:20]
        more = f" (+{len(problems) - 20} more)" if len(problems) > 20 else ""
        raise PreflightError(
            f"Plan cannot be applied: {len(problems)} problem(s){more}. Nothing was moved. "
            "Fix the listed items and create a new plan.", shown)
