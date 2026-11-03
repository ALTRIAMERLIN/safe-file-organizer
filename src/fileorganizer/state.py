"""Application state: state directory, per-root exclusive lock, append-only journal."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from typing import Any

from .errors import JournalError, LockBusyError

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - non-Windows is unsupported but keep importable
    msvcrt = None  # type: ignore


def default_state_dir() -> str:
    env = os.environ.get("FILEORGANIZER_STATE_DIR")
    if env:
        return os.path.abspath(env)
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "SafeFileOrganizer")


def root_id(root: str) -> str:
    """Stable id of a root folder (case-insensitive, long-name resolved)."""
    return os.path.normcase(os.path.realpath(os.path.abspath(root)))


class RootLock:
    """Exclusive, non-blocking lock released by the OS when the process exits (even if killed)."""

    def __init__(self, path: str):
        self.path = path
        self.fd: int | None = None

    def acquire(self) -> "RootLock":
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT)
        try:
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"L")
            os.lseek(fd, 0, 0)
            if msvcrt is not None:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:  # pragma: no cover
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            os.close(fd)
            raise LockBusyError(
                "Another Safe File Organizer task is using this folder. Wait for it to finish, then try again."
            ) from e
        self.fd = fd
        return self

    def release(self) -> None:
        if self.fd is None:
            return
        try:
            os.lseek(self.fd, 0, 0)
            if msvcrt is not None:
                msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        os.close(self.fd)
        self.fd = None

    def __enter__(self) -> "RootLock":
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()


class State:
    def __init__(self, path: str | None = None):
        self.path = os.path.abspath(path or default_state_dir())

    @property
    def runs_dir(self) -> str:
        return os.path.join(self.path, "runs")

    @property
    def plans_dir(self) -> str:
        return os.path.join(self.path, "plans")

    @property
    def locks_dir(self) -> str:
        return os.path.join(self.path, "locks")

    def lock(self, root: str) -> RootLock:
        h = hashlib.sha1(root_id(root).encode("utf-8")).hexdigest()
        return RootLock(os.path.join(self.locks_dir, f"{h}.lock"))


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds")


class Journal:
    """Append-only JSON-lines file; every append is flushed and fsync'd before returning."""

    def __init__(self, path: str):
        self.path = path
        self._f = None
        self.seq = 0

    def open(self) -> "Journal":
        try:
            existing = read_events(self.path)
            self.seq = len(existing)
            self._f = open(self.path, "ab")
            if os.path.getsize(self.path) > 0:
                with open(self.path, "rb") as r:
                    r.seek(-1, os.SEEK_END)
                    if r.read(1) != b"\n":  # a previous crash left a partial line
                        self._f.write(b"\n")
                        self._f.flush()
        except OSError as e:
            raise JournalError(f"Cannot open the run log ({e.strerror}). Check the state folder is writable.") from e
        return self

    def append(self, event: dict[str, Any]) -> None:
        if self._f is None:
            raise JournalError("Run log is not open.")
        self.seq += 1
        rec = {"seq": self.seq, "t": now_iso(), **event}
        line = (json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            self._f.write(line)
            self._f.flush()
            os.fsync(self._f.fileno())
        except OSError as e:
            raise JournalError(f"Cannot write the run log ({e.strerror}). Free disk space or check permissions.") from e

    def close(self) -> None:
        if self._f is not None:
            try:
                self._f.close()
            finally:
                self._f = None


def read_events(path: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        with open(path, "rb") as f:
            for raw in f.read().split(b"\n"):
                if not raw.strip():
                    continue
                try:
                    out.append(json.loads(raw.decode("utf-8")))
                except ValueError:
                    continue  # torn final line after a crash
    except FileNotFoundError:
        pass
    return out
