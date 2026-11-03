"""Shared helpers. All file operations happen inside pytest's temp sandbox."""

import datetime as dt
import hashlib
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

from fileorganizer import planner  # noqa: E402


def mk(root, files, mtime_iso=None):
    """Create files: {rel: bytes|str}. Returns root."""
    for rel, data in files.items():
        p = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data.encode("utf-8") if isinstance(data, str) else data)
        if mtime_iso:
            ns = int(dt.datetime.fromisoformat(mtime_iso).replace(tzinfo=dt.timezone.utc).timestamp()) * 10**9
            os.utime(p, ns=(ns, ns))
    return root


def snapshot(root):
    """{rel path: sha256} of every file below root."""
    out = {}
    for base, dirs, fs in os.walk(root):
        for n in fs:
            p = os.path.join(base, n)
            with open(p, "rb") as f:
                out[os.path.relpath(p, root).replace("\\", "/")] = hashlib.sha256(f.read()).hexdigest()
    return out


def all_dirs(root):
    out = set()
    for base, dirs, _ in os.walk(root):
        for d in dirs:
            out.add(os.path.relpath(os.path.join(base, d), root).replace("\\", "/"))
    return out


def retarget(plan, mapping):
    """Hand-edit a plan's targets and recompute summary/digest (simulates a tampered or crafted plan)."""
    for it in plan.items:
        if it.src in mapping:
            it.dst = mapping[it.src]
            it.action = "no_op" if it.dst == it.src else "move_and_rename"
            it.status = "ready"
    plan.summary = planner.summarize(plan.items)
    plan.digest = planner.compute_digest(plan)
    return plan


def make_junction(link, target):
    r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"cannot create junction: {r.stderr or r.stdout}")


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "src"
    r.mkdir()
    return str(r)


@pytest.fixture
def state(tmp_path):
    s = tmp_path / "appstate"
    s.mkdir()
    return str(s)
