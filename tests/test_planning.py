"""Phase 1-2 tests: scanning, rules, planning, conflicts, plan I/O (A01-A12)."""

import copy
import csv
import json
import os

import pytest

from conftest import all_dirs, make_junction, mk, retarget, snapshot
from fileorganizer import planner
from fileorganizer.errors import PreflightError, RuleError
from fileorganizer.rules import Rules
from fileorganizer.scanner import scan


def plan_of(root, **kw):
    return planner.make_plan(root, Rules(**kw))


def dst_of(plan, src):
    return next(i.dst for i in plan.items if i.src == src)


def item(plan, src):
    return next(i for i in plan.items if i.src == src)


# ---------------------------------------------------------------- A01
def test_A01_default_first_level_only(root):
    mk(root, {"a.txt": "1", "sub/b.txt": "2", "sub/deep/c.txt": "3"})
    p = plan_of(root, prefix="x_")
    assert [i.src for i in p.items] == ["a.txt"]


def test_A01_recursive_switch(root):
    mk(root, {"a.txt": "1", "sub/b.txt": "2", "sub/deep/c.txt": "3"})
    p = plan_of(root, prefix="x_", recursive=True)
    assert sorted(i.src for i in p.items) == ["a.txt", "sub/b.txt", "sub/deep/c.txt"]
    assert dst_of(p, "sub/deep/c.txt") == "sub/deep/x_c.txt"  # parent preserved without classify


def test_A01_extension_filter_case_insensitive(root):
    mk(root, {"a.PDF": "1", "b.pdf": "2", "c.txt": "3", "noext": "4"})
    entries = scan(root, Rules(extensions=("Pdf",)))
    inc = sorted(e.rel for e in entries if e.status == "included")
    assert inc == ["a.PDF", "b.pdf"]
    assert {e.rel: e.reason for e in entries if e.status == "skipped"}["c.txt"] == "extension filter"
    entries2 = scan(root, Rules(extensions=(".PDF",)))
    assert sorted(e.rel for e in entries2 if e.status == "included") == inc


def test_A01_unreadable_file_listed_not_ignored(root, monkeypatch):
    mk(root, {"a.txt": "1", "b.txt": "2"})
    from fileorganizer import names
    real = names.sha256_file

    def bad(path):
        if path.endswith("b.txt"):
            raise PermissionError(13, "Permission denied")
        return real(path)

    monkeypatch.setattr(names, "sha256_file", bad)
    p = plan_of(root, prefix="x_")
    it = item(p, "b.txt")
    assert it.status == "conflict" and "read error" in it.reason
    assert p.blocked


# ---------------------------------------------------------------- A02
def test_A02_special_names(root):
    files = {"\u62a5\u544a \u6700\u7ec8.v1.2.pdf": "x", "my file.tar.gz": "y", "Makefile": "z", "empty.txt": b""}
    mk(root, files)
    p = plan_of(root, prefix="P_", suffix="_S")
    assert dst_of(p, "\u62a5\u544a \u6700\u7ec8.v1.2.pdf") == "P_\u62a5\u544a \u6700\u7ec8.v1.2_S.pdf"
    assert dst_of(p, "my file.tar.gz") == "P_my file.tar_S.gz"   # last dot is the extension
    assert dst_of(p, "Makefile") == "P_Makefile_S"               # no extension stays none
    assert dst_of(p, "empty.txt") == "P_empty_S.txt"             # zero-byte file handled
    assert not p.blocked
    assert item(p, "empty.txt").sha256 == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_A02_extension_case_preserved(root):
    mk(root, {"A.JpG": "1"})
    assert dst_of(plan_of(root, prefix="x"), "A.JpG") == "xA.JpG"


# ---------------------------------------------------------------- A03
def test_A03_fixed_order_replace_prefix_suffix_number(root):
    mk(root, {"report_old.txt": "1"})
    p = plan_of(root, find="old", replace="new", prefix="old_", suffix="-s", numbering=True)
    # replacement applies to the stem BEFORE prefix/suffix, so the prefix 'old_' survives
    assert dst_of(p, "report_old.txt") == "old_report_new-s_001.txt"


def test_A03_replace_is_literal_case_sensitive(root):
    mk(root, {"a.b(c).txt": "1", "ABC.txt": "2"})
    p = plan_of(root, find="(c)", replace="X")
    assert dst_of(p, "a.b(c).txt") == "a.bX.txt"
    p = plan_of(root, find="abc", replace="Q")
    assert dst_of(p, "ABC.txt") == "ABC.txt" and item(p, "ABC.txt").action == "no_op"


def test_A03_empty_find_illegal(root):
    with pytest.raises(RuleError):
        Rules(find="", replace="x").validate()


def test_A03_numbering_order_casefold_then_original(root):
    mk(root, {"b.txt": "1", "C.txt": "2", "a.txt": "3", "sub/a.txt": "4"})
    p = plan_of(root, numbering=True, recursive=True, digits=2)
    order = sorted(p.items, key=lambda i: i.dst.rsplit("_", 1)[1])
    # casefold is the primary key: a < b < C (a plain code-point sort would put 'C' first); then 'sub/...'
    assert [i.src for i in order] == ["a.txt", "b.txt", "C.txt", "sub/a.txt"]
    assert dst_of(p, "sub/a.txt") == "sub/a_04.txt"  # batch-wide, not restarted per folder


def test_A03_1000_files_unique_not_truncated(root):
    mk(root, {f"f{i:04d}.txt": str(i) for i in range(1000)})
    p = plan_of(root, numbering=True, digits=3)
    dsts = [i.dst for i in p.items]
    assert len(set(dsts)) == 1000 and not p.blocked
    assert dst_of(p, "f0999.txt") == "f0999_1000.txt"  # grows past 3 digits
    assert dst_of(p, "f0000.txt") == "f0000_001.txt"


# ---------------------------------------------------------------- A04
def test_A04_classify_by_extension(root):
    mk(root, {"a.PDF": "1", "b.Txt": "2", "noext": "3"})
    p = plan_of(root, classify="extension")
    assert dst_of(p, "a.PDF") == "Organized/pdf/a.PDF"
    assert dst_of(p, "b.Txt") == "Organized/txt/b.Txt"
    assert dst_of(p, "noext") == "Organized/no_extension/noext"
    assert item(p, "a.PDF").action == "move"


# ---------------------------------------------------------------- A05
@pytest.mark.parametrize("iso,month", [
    ("2025-12-31T23:30:00", "2025-12"),
    ("2026-01-01T00:00:00", "2026-01"),
    ("2026-01-31T23:59:59", "2026-01"),
    ("2026-02-01T00:00:00", "2026-02"),
    ("2024-02-29T12:00:00", "2024-02"),
])
def test_A05_month_is_utc(root, iso, month):
    mk(root, {"a.txt": "1"}, mtime_iso=iso)
    assert dst_of(plan_of(root, classify="month"), "a.txt") == f"Organized/{month}/a.txt"


# ---------------------------------------------------------------- A06
def test_A06_no_classify_keeps_parent_and_flatten_conflicts(root):
    mk(root, {"x/invoice.pdf": "1", "y/invoice.pdf": "2"})
    p = plan_of(root, prefix="z_", recursive=True)
    assert dst_of(p, "x/invoice.pdf") == "x/z_invoice.pdf" and not p.blocked
    p = plan_of(root, classify="extension", recursive=True)
    assert p.blocked
    for s in ("x/invoice.pdf", "y/invoice.pdf"):
        assert item(p, s).status == "conflict" and "same target" in item(p, s).reason


# ---------------------------------------------------------------- A07
def test_A07_preview_does_not_touch_source(root, state):
    mk(root, {"a.txt": "1", "sub/b.pdf": "2"})
    before, dirs = snapshot(root), all_dirs(root)
    p = planner.make_plan(root, Rules(classify="extension", prefix="n_", recursive=True), state)
    planner.save_plan(p, os.path.join(state, "plans", "p.json"))
    assert snapshot(root) == before and all_dirs(root) == dirs
    assert not os.path.exists(os.path.join(root, "Organized"))


def test_A07_plan_cannot_be_written_inside_root(root):
    mk(root, {"a.txt": "1"})
    p = plan_of(root, prefix="n_")
    with pytest.raises(PreflightError):
        planner.save_plan(p, os.path.join(root, "plan.json"))
    with pytest.raises(PreflightError):
        planner.export_csv(p, os.path.join(root, "plan.csv"))


# ---------------------------------------------------------------- A08
def test_A08_deterministic_mapping(root):
    mk(root, {"a.txt": "1", "b.pdf": "2", "s/c.txt": "3"})
    r = Rules(prefix="n_", numbering=True, classify="extension", recursive=True)
    p1, p2 = planner.make_plan(root, r), planner.make_plan(root, r)
    assert p1.mapping() == p2.mapping() and p1.plan_id != p2.plan_id
    assert p1.digest == p2.digest  # digest covers mapping + sources, not ids/timestamps


def test_A08_empty_rules_and_empty_folder_are_explainable_noops(root):
    p = plan_of(root)
    assert p.summary["total"] == 0 and not p.blocked
    mk(root, {"a.txt": "1"})
    p = plan_of(root)
    it = item(p, "a.txt")
    assert it.action == "no_op" and it.status == "ready" and it.reason == "no rules configured"
    assert p.summary["to_move"] == 0


def test_A08_export_csv_json(root, state):
    mk(root, {"\u6587\u4ef6.txt": "1"})
    p = plan_of(root, prefix="n_")
    c = os.path.join(state, "e.csv")
    j = os.path.join(state, "e.json")
    planner.export_csv(p, c)
    planner.save_plan(p, j)
    raw = open(c, "rb").read()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(raw.decode("utf-8-sig").splitlines()))
    assert rows[0][:4] == ["source", "target", "action", "status"] and rows[1][0] == "\u6587\u4ef6.txt"
    data = json.load(open(j, encoding="utf-8"))
    for k in ("schema_version", "plan_id", "root", "rules", "items", "summary", "digest"):
        assert k in data
    it = data["items"][0]
    assert {"size", "mtime_ns", "sha256", "dst"} <= set(it)
    with pytest.raises(PreflightError):  # never silently overwrites
        planner.save_plan(p, j)


# ---------------------------------------------------------------- A09
def test_A09_existing_target_and_batch_duplicates_block(root):
    mk(root, {"a.txt": "1", "n_a.txt": "2", "b.txt": "3", "c.txt": "4"})
    p = plan_of(root, prefix="n_")
    assert item(p, "a.txt").status == "conflict" and "another file" in item(p, "a.txt").reason  # chain
    assert p.blocked
    root2 = os.path.join(os.path.dirname(root), "src2")
    os.mkdir(root2)
    mk(root2, {"a.txt": "1", "b.txt": "2"})
    p = plan_of(root2, find="a", replace="b")  # a.txt -> b.txt, b.txt stays put
    assert item(p, "a.txt").status == "conflict" and "already exists" in item(p, "a.txt").reason
    assert item(p, "b.txt").status == "ready" and p.blocked and p.summary["conflict"] == 1


def test_A09_batch_duplicate_targets_block_all_involved(root):
    mk(root, {"x/invoice.pdf": "1", "y/invoice.pdf": "2", "z/other.pdf": "3"})
    p = plan_of(root, classify="extension", recursive=True)
    assert p.blocked and p.summary["conflict"] == 2
    assert item(p, "z/other.pdf").status == "ready"


# ---------------------------------------------------------------- A10
@pytest.mark.parametrize("find,replace,why", [
    ("x", "CON", "reserved"),
    ("x", "aux", "reserved"),
    ("x", "a:b", "illegal character"),
    ("x", "a?b", "illegal character"),
    ("x", "a<b", "illegal character"),
])
def test_A10_invalid_windows_names_block(root, find, replace, why):
    mk(root, {"x.txt": "1"})
    p = plan_of(root, find=find, replace=replace)
    assert p.blocked and why in item(p, "x.txt").reason


@pytest.mark.parametrize("suffix", [".", " "])
def test_A10_trailing_dot_or_space_block(root, suffix):
    mk(root, {"noext": "1"})
    p = plan_of(root, suffix=suffix)
    assert p.blocked and "dot or space" in item(p, "noext").reason


def test_A10_case_only_rename_blocked(root):
    mk(root, {"a.txt": "1"})
    p = plan_of(root, find="a", replace="A")
    assert p.blocked and "case-only" in item(p, "a.txt").reason


def test_A10_case_insensitive_collisions_block(root):
    mk(root, {"b.txt": "1", "q.txt": "2"})
    p = plan_of(root, find="q", replace="B")  # q.txt -> B.txt, b.txt exists (case-insensitive)
    assert item(p, "q.txt").status == "conflict" and "already exists" in item(p, "q.txt").reason


def test_A10_same_target_differing_only_by_case(root):
    mk(root, {"x/a.txt": "1", "y/A.txt": "2"})
    p = plan_of(root, classify="extension", recursive=True)
    assert p.blocked
    assert all("same target" in i.reason for i in p.items)


def test_A10_empty_new_name_blocks(root):
    mk(root, {"abc.txt": "1"})
    p = plan_of(root, find="abc", replace="")
    assert p.blocked and "empty" in item(p, "abc.txt").reason


# ---------------------------------------------------------------- A11
def test_A11_swap_and_cycle_rejected(root, state):
    mk(root, {"a.txt": "A", "b.txt": "B", "c.txt": "C"})
    p = plan_of(root, prefix="")
    retarget(p, {"a.txt": "b.txt", "b.txt": "a.txt"})
    with pytest.raises(PreflightError) as e:
        planner.validate_for_apply(p)
    assert any("another file" in x for x in e.value.problems)
    p = plan_of(root, prefix="")
    retarget(p, {"a.txt": "b.txt", "b.txt": "c.txt", "c.txt": "a.txt"})
    with pytest.raises(PreflightError):
        planner.validate_for_apply(p)


def test_A11_parent_path_is_file_rejected(root):
    mk(root, {"a.pdf": "1", "Organized": "i am a file"})
    p = plan_of(root, classify="extension")
    assert p.blocked and "is a file" in item(p, "a.pdf").reason


def test_A11_long_path_precheck_fails_clearly(tmp_path):
    deep = tmp_path
    for _ in range(4):
        deep = deep / ("d" * 50)
    deep.mkdir(parents=True)
    root = str(deep)
    mk(root, {"a.txt": "1"})
    p = plan_of(root, prefix="p" * 60)
    assert p.blocked and "not supported" in item(p, "a.txt").reason


# ---------------------------------------------------------------- A12
@pytest.mark.parametrize("bad", ["../evil.txt", "..\\evil.txt", "C:/evil.txt", "/evil.txt", "a/../../e.txt",
                                 "sub//x.txt", "CON.txt", "x/./y.txt"])
def test_A12_boundary_escape_in_tampered_plan(root, bad):
    mk(root, {"a.txt": "1"})
    p = plan_of(root, prefix="")
    retarget(p, {"a.txt": bad})
    with pytest.raises(PreflightError):
        planner.validate_for_apply(p)


def test_A12_tampered_plan_digest_detected(root):
    mk(root, {"a.txt": "1"})
    p = plan_of(root, prefix="n_")
    p.items[0].dst = "other.txt"  # edited without recomputing digest
    with pytest.raises(PreflightError, match="digest"):
        planner.validate_for_apply(p)


def test_A12_malformed_plan_files(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("{not json", encoding="utf-8")
    with pytest.raises(PreflightError):
        planner.load_plan(str(f))
    f.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
    with pytest.raises(PreflightError):
        planner.load_plan(str(f))
    f.write_text(json.dumps([1, 2]), encoding="utf-8")
    with pytest.raises(PreflightError):
        planner.load_plan(str(f))


def test_A12_plan_roundtrip_through_file(root, state):
    mk(root, {"a.txt": "1"})
    p = plan_of(root, prefix="n_")
    path = os.path.join(state, "plan.json")
    planner.save_plan(p, path)
    q = planner.load_plan(path)
    assert q.digest == p.digest and q.mapping() == p.mapping()
    planner.validate_for_apply(q)


@pytest.mark.windows
def test_A12_junction_and_hardlink_never_included(root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("s")
    mk(root, {"a.txt": "1", "real.txt": "2"})
    make_junction(os.path.join(root, "jl"), str(outside))
    os.link(os.path.join(root, "real.txt"), os.path.join(root, "hard.txt"))
    p = plan_of(root, prefix="n_", recursive=True)
    srcs = {i.src: i for i in p.items}
    assert "jl/secret.txt" not in srcs
    assert "link" in srcs["jl"].reason and srcs["jl"].status == "skipped"
    assert "hard" in srcs["hard.txt"].reason and srcs["hard.txt"].status == "skipped"
    assert "hard" in srcs["real.txt"].reason
    assert srcs["a.txt"].status == "ready"


@pytest.mark.windows
def test_A12_root_that_is_a_junction_is_refused(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "a.txt").write_text("1")
    link = tmp_path / "link"
    make_junction(str(link), str(real))
    with pytest.raises(PreflightError, match="link"):
        planner.make_plan(str(link), Rules(prefix="x"))
    sub = real / "child"
    sub.mkdir()
    with pytest.raises(PreflightError, match="link"):
        planner.make_plan(str(link / "child"), Rules(prefix="x"))


@pytest.mark.windows
def test_A12_target_through_junction_rejected(root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    mk(root, {"a.txt": "1"})
    make_junction(os.path.join(root, "jl"), str(outside))
    p = plan_of(root, prefix="")
    retarget(p, {"a.txt": "jl/a.txt"})
    with pytest.raises(PreflightError) as e:
        planner.validate_for_apply(p)
    assert any("link" in x for x in e.value.problems)
    assert not (outside / "a.txt").exists()


@pytest.mark.windows
def test_A12_organized_link_refused(root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    mk(root, {"a.pdf": "1"})
    make_junction(os.path.join(root, "Organized"), str(outside))
    with pytest.raises(PreflightError, match="Organized"):
        plan_of(root, classify="extension")


def test_A12_target_on_different_volume_rejected_SIMULATED(root, monkeypatch):
    """SIMULATED: no second local NTFS volume is available, so a folder's st_dev is faked.
    (A real mounted folder is also a reparse point and is already rejected as a link.)"""
    mk(root, {"a.txt": "1", "mnt/keep.txt": "2"})
    mnt = os.path.normcase(os.path.join(root, "mnt"))
    real_lstat = os.lstat

    def fake_lstat(path, *a, **kw):
        st = real_lstat(path, *a, **kw)
        if os.path.normcase(os.fspath(path)).startswith(mnt):
            seq = list(st[:10])
            seq[2] = st.st_dev + 1  # st_dev
            return os.stat_result(seq, {"st_file_attributes": getattr(st, "st_file_attributes", 0)})
        return st

    p = plan_of(root, prefix="")
    retarget(p, {"a.txt": "mnt/a.txt"})
    monkeypatch.setattr(os, "lstat", fake_lstat)
    with pytest.raises(PreflightError) as e:
        planner.validate_for_apply(p)
    assert any("different volume" in x for x in e.value.problems)
    monkeypatch.undo()
    assert sorted(os.listdir(root)) == ["a.txt", "mnt"]


def test_rules_strict_parsing():
    with pytest.raises(RuleError):
        Rules.from_dict({"regex": ".*"})
    with pytest.raises(RuleError):
        Rules.from_dict({"classify": "weird"})
    with pytest.raises(RuleError):
        Rules.from_dict({"digits": 0})
    r = Rules.from_dict({"extensions": [".PDF", "pdf", "Txt"]})
    assert r.extensions == ("pdf", "txt")
