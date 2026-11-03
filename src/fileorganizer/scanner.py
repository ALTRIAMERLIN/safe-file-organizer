"""Read-only scanner. Never modifies the source tree."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass

from . import names
from .rules import Rules, normalize_extensions

ORGANIZED = "Organized"


@dataclass
class Entry:
    rel: str                 # '/'-separated path relative to root
    size: int = 0
    mtime_ns: int = 0
    file_id: str = ""
    sha256: str = ""
    status: str = "included"  # included | skipped | error
    reason: str = ""


def ext_of(name: str) -> tuple[str, str | None]:
    """Split at the LAST dot: returns (stem, ext or None when there is no dot)."""
    i = name.rfind(".")
    if i < 0:
        return name, None
    return name[:i], name[i + 1:]


def scan(root: str, rules: Rules, state_dir: str | None = None) -> list[Entry]:
    root = names.check_root_dir(root)
    wanted = set(normalize_extensions(rules.extensions))
    state_key = names.path_key(state_dir) if state_dir else None
    out: list[Entry] = []

    def walk(abs_dir: str, rel_dir: str, top: bool) -> None:
        try:
            with os.scandir(abs_dir) as it:
                items = sorted(it, key=lambda e: (e.name.casefold(), e.name))
        except OSError as e:
            out.append(Entry(rel_dir or ".", status="error", reason=f"cannot list folder: {e.strerror}"))
            return
        for de in items:
            rel = f"{rel_dir}/{de.name}" if rel_dir else de.name
            try:
                st = os.lstat(de.path)  # DirEntry.stat() lacks st_ino/st_nlink on Windows
            except OSError as e:
                out.append(Entry(rel, status="error", reason=f"cannot read: {e.strerror}"))
                continue
            attrs = names.file_attrs(st)
            if names.is_link_st(st):
                out.append(Entry(rel, status="skipped", reason="link or junction (not supported)"))
                continue
            if attrs & (names.FILE_ATTRIBUTE_HIDDEN | names.FILE_ATTRIBUTE_SYSTEM):
                out.append(Entry(rel, status="skipped", reason="hidden or system item"))
                continue
            if stat.S_ISDIR(st.st_mode):
                if top and de.name.casefold() == ORGANIZED.casefold():
                    out.append(Entry(rel, status="skipped", reason="Organized output folder is excluded"))
                    continue
                if state_key and names.path_key(de.path) == state_key:
                    out.append(Entry(rel, status="skipped", reason="application state folder"))
                    continue
                if rules.recursive:
                    walk(de.path, rel, False)
                continue
            if not stat.S_ISREG(st.st_mode):
                out.append(Entry(rel, status="skipped", reason="not a regular file"))
                continue
            if st.st_nlink > 1:
                out.append(Entry(rel, st.st_size, st.st_mtime_ns, status="skipped",
                                 reason="hard-linked file (not supported)"))
                continue
            if wanted:
                _, ext = ext_of(de.name)
                if ext is None or ext.lower() not in wanted:
                    out.append(Entry(rel, st.st_size, st.st_mtime_ns, status="skipped",
                                     reason="extension filter"))
                    continue
            try:
                digest = names.sha256_file(de.path)
            except OSError as e:
                out.append(Entry(rel, st.st_size, st.st_mtime_ns, status="error",
                                 reason=f"cannot read file: {e.strerror}"))
                continue
            out.append(Entry(rel, st.st_size, st.st_mtime_ns, names.file_id(st), digest))

    walk(root, "", True)
    return out
