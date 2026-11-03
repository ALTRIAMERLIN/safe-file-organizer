"""Windows name/path validation, link detection and hashing helpers."""

from __future__ import annotations

import hashlib
import os
import stat

from .errors import PreflightError

FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4
FILE_ATTRIBUTE_REPARSE_POINT = 0x400

ILLEGAL_CHARS = set('<>:"/\\|?*')
_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
_RESERVED |= {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
_RESERVED |= {"COM\u00b9", "COM\u00b2", "COM\u00b3", "LPT\u00b9", "LPT\u00b2", "LPT\u00b3"}

MAX_PATH_LEN = 260  # absolute paths of this length or longer are rejected (long paths unsupported in v1)


def check_component(name: str) -> str | None:
    """Return a reason string if ``name`` is not a valid single Windows path component."""
    if name == "":
        return "empty name"
    if name in (".", ".."):
        return "'.' and '..' are not allowed"
    for ch in name:
        if ch in ILLEGAL_CHARS or ord(ch) < 32:
            return f"illegal character {ch!r} in name"
    if name[-1] in ". ":
        return "name ends with a dot or space"
    base = name.split(".", 1)[0].rstrip(" ").upper()
    if base in _RESERVED:
        return f"reserved Windows device name {base}"
    return None


def split_rel(rel: str) -> list[str]:
    """Split a stored relative path ('/'-separated) and validate every component.

    Raises ValueError with a short reason for unsafe or invalid paths.
    """
    if not isinstance(rel, str) or rel == "":
        raise ValueError("empty path")
    if rel.startswith("/") or rel.startswith("\\"):
        raise ValueError("absolute path not allowed")  # drive letters fail the ':' check below
    if "\\" in rel:
        raise ValueError("backslash in stored path")
    parts = rel.split("/")
    for p in parts:
        if p in ("", ".", ".."):
            raise ValueError("path escapes the root or is not normalized")
        why = check_component(p)
        if why:
            raise ValueError(why)
    return parts


def key(rel: str) -> str:
    """Case-insensitive comparison key for a stored relative path."""
    return rel.casefold()


def abs_path(root: str, rel: str) -> str:
    return os.path.join(root, *rel.split("/"))


def norm_root(root: str) -> str:
    return os.path.abspath(root)


def path_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def is_within(root: str, path: str) -> bool:
    r = path_key(root).rstrip("\\/") + os.sep
    return (path_key(path) + os.sep).startswith(r)


def file_attrs(st: os.stat_result) -> int:
    return getattr(st, "st_file_attributes", 0)


def is_link_st(st: os.stat_result) -> bool:
    return stat.S_ISLNK(st.st_mode) or bool(file_attrs(st) & FILE_ATTRIBUTE_REPARSE_POINT)


def is_link(path: str) -> bool:
    try:
        return is_link_st(os.lstat(path))
    except OSError:
        return False


def file_id(st: os.stat_result) -> str:
    return f"{st.st_dev}:{st.st_ino}"


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def check_root_dir(root: str) -> str:
    """Validate the source root; the root and its ancestors must not be links/junctions."""
    root = norm_root(root)
    if not os.path.isdir(root):
        raise PreflightError(f"Folder not found: {root}. Choose an existing folder.")
    cur = root
    while True:
        try:
            st = os.lstat(cur)
        except OSError as e:
            raise PreflightError(f"Cannot read folder {cur}: {e.strerror}. Check permissions.") from e
        if is_link_st(st):
            raise PreflightError(
                f"Folder or an ancestor is a link/junction: {cur}. Links are not supported; choose a real folder."
            )
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return root


def check_no_links_below(root: str, rel: str) -> str | None:
    """Return a reason if any existing component of root/rel is a link/junction or on another volume."""
    parts = rel.split("/")
    cur = root
    try:
        root_dev = os.stat(root).st_dev
    except OSError as e:
        return f"cannot read root: {e.strerror}"
    for i, p in enumerate(parts):
        cur = os.path.join(cur, p)
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            return None
        except OSError as e:
            return f"cannot read {p}: {e.strerror}"
        if is_link_st(st):
            return f"'{'/'.join(parts[: i + 1])}' is a link/junction"
        if st.st_dev != root_dev:
            return f"'{'/'.join(parts[: i + 1])}' is on a different volume"
    return None
