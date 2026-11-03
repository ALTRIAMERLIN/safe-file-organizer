"""Demo fixture + independent frozen expectations (tests/fixtures/demo_expected.json)."""

import json
import os

import pytest

import make_demo_workspace as demo
from conftest import snapshot
from fileorganizer import planner
from fileorganizer.rules import Rules

EXPECTED = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "demo_expected.json"),
                          encoding="utf-8"))


def build_demo(tmp_path):
    d = str(tmp_path / "demo_workspace")
    demo.build(d)
    return d


def test_fixture_composition(tmp_path):
    d = build_demo(tmp_path)
    snap = snapshot(d)
    snap.pop(demo.MARKER, None)
    assert len(snap) == 36
    by_ext = {}
    for rel in snap:
        n = rel.rsplit("/", 1)[1]
        e = n.rsplit(".", 1)[1].lower() if "." in n else "none"
        by_ext[e] = by_ext.get(e, 0) + 1
    assert by_ext == {"pdf": 10, "jpg": 8, "txt": 8, "csv": 6, "none": 4}
    assert len({r.split("/")[0] for r in snap}) == 3
    assert any(os.path.getsize(os.path.join(d, *r.split("/"))) == 0 for r in snap)
    assert sorted(snap) == sorted(EXPECTED["mapping"])
    assert snap == EXPECTED["sha256"]


def test_demo_plan_matches_independent_expectation(tmp_path):
    d = build_demo(tmp_path)
    p = planner.make_plan(d, Rules.from_dict(EXPECTED["rules"]))
    # 36 real files ready; the hidden generator marker is listed as skipped (37 scanned in total)
    assert p.summary["ready"] == 36 and p.summary["conflict"] == 0 and p.summary["skipped"] == 1
    assert [i.reason for i in p.items if i.status == "skipped"] == ["hidden or system item"]
    assert {i.src: i.dst for i in p.items if i.status == "ready"} == EXPECTED["mapping"]
    planner.validate_for_apply(p)


def test_conflict_fixture_is_blocked(tmp_path):
    d = str(tmp_path / "conflict_ws")
    demo.build(d, demo.CONFLICT_FILES)
    p = planner.make_plan(d, Rules(classify="extension", recursive=True))
    assert p.blocked and p.summary["conflict"] == 2


def test_generator_never_overwrites_and_reset_is_scoped(tmp_path):
    d = build_demo(tmp_path)
    with pytest.raises(SystemExit):
        demo.build(d)  # non-empty -> refuse
    extra = os.path.join(d, "user_file.txt")
    open(extra, "w").write("mine")
    demo.reset(d)
    assert os.path.exists(extra)  # unrelated file untouched; folder kept
    other = tmp_path / "not_demo"
    other.mkdir()
    (other / "a.txt").write_text("x")
    with pytest.raises(SystemExit):
        demo.reset(str(other))  # no marker -> refuse
    assert (other / "a.txt").exists()
