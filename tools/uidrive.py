"""Minimal Windows UI driver: real mouse/keyboard input via SendInput, window lookup, screen grabs.

Used by tools/a27_ui_run.py to operate the real tkinter window. No test harness, no Tk internals:
everything goes through the operating system's input queue like a person at the keyboard.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import time

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE = 0x0001, 0x8000
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004
VK = {"enter": 0x0D, "tab": 0x09, "esc": 0x1B, "ctrl": 0x11, "a": 0x41, "backspace": 0x08}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _U)]


def _send(*inputs: INPUT) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    if user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT)) != len(inputs):
        raise OSError("SendInput was blocked")


def screen_size() -> tuple[int, int]:
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def _mouse(flags: int, x: int | None = None, y: int | None = None) -> INPUT:
    i = INPUT(type=INPUT_MOUSE)
    if x is not None:
        w, h = screen_size()
        i.mi.dx, i.mi.dy = int(x * 65535 / (w - 1)), int(y * 65535 / (h - 1))
        flags |= MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
    i.mi.dwFlags = flags
    return i


def cursor() -> tuple[int, int]:
    p = wt.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def move(x: int, y: int, seconds: float = 0.5) -> None:
    """Glide the real cursor so a recording shows where the click goes."""
    x0, y0 = cursor()
    steps = max(2, int(seconds * 60))
    for n in range(1, steps + 1):
        t = n / steps
        t = t * t * (3 - 2 * t)
        _send(_mouse(0, round(x0 + (x - x0) * t), round(y0 + (y - y0) * t)))
        time.sleep(seconds / steps)


def click(x: int, y: int, seconds: float = 0.5) -> None:
    move(x, y, seconds)
    time.sleep(0.12)
    _send(_mouse(MOUSEEVENTF_LEFTDOWN))
    time.sleep(0.06)
    _send(_mouse(MOUSEEVENTF_LEFTUP))
    time.sleep(0.25)


def key(name: str, *mods: str) -> None:
    for m in mods:
        _send(_vk(VK[m], False))
    _send(_vk(VK[name], False), _vk(VK[name], True))
    for m in reversed(mods):
        _send(_vk(VK[m], True))
    time.sleep(0.15)


def _vk(code: int, up: bool) -> INPUT:
    i = INPUT(type=INPUT_KEYBOARD)
    i.ki.wVk = code
    i.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
    return i


def type_text(text: str, delay: float = 0.03) -> None:
    for ch in text:
        for up in (False, True):
            i = INPUT(type=INPUT_KEYBOARD)
            i.ki.wScan = ord(ch)
            i.ki.dwFlags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
            _send(i)
        time.sleep(delay)


# ---------------------------------------------------------------- windows
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def windows_of_pid(pid: int) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []

    def cb(hwnd, _):
        p = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            out.append((hwnd, buf.value))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def wait_window(pid: int, title: str, timeout: float = 20) -> int:
    end = time.time() + timeout
    while time.time() < end:
        for h, t in windows_of_pid(pid):
            if t == title:
                return h
        time.sleep(0.2)
    raise TimeoutError(f"window {title!r} of pid {pid} did not appear")


def rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wt.RECT()
    user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def place(hwnd: int, x: int, y: int, w: int | None = None, h: int | None = None) -> None:
    l, t, r, b = rect(hwnd)
    HWND_TOPMOST, SWP_SHOWWINDOW = -1, 0x0040
    user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wt.UINT]
    if not user32.SetWindowPos(wt.HWND(hwnd), wt.HWND(HWND_TOPMOST), x, y, w or r - l, h or b - t,
                               SWP_SHOWWINDOW):
        raise OSError("SetWindowPos failed")
    user32.SetForegroundWindow(hwnd)


def foreground_title() -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(user32.GetForegroundWindow(), buf, 256)
    return buf.value


def dialogs_of_pid(pid: int, main_title: str) -> list[tuple[int, str]]:
    return [(h, t) for h, t in windows_of_pid(pid) if t != main_title]


def wait_dialog(pid: int, main_title: str, timeout: float = 15) -> tuple[int, str]:
    end = time.time() + timeout
    while time.time() < end:
        d = dialogs_of_pid(pid, main_title)
        if d:
            return d[0]
        time.sleep(0.2)
    raise TimeoutError("expected dialog did not appear")


def wait_no_dialog(pid: int, main_title: str, timeout: float = 15) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if not dialogs_of_pid(pid, main_title):
            return
        time.sleep(0.2)
    raise TimeoutError("dialog did not close")


BACKDROP_CODE = (
    "import tkinter as tk\n"
    "r=tk.Tk(); r.overrideredirect(True); r.configure(bg='#1b2433')\n"
    "r.geometry('%dx%d+0+0' % (r.winfo_screenwidth(), r.winfo_screenheight()))\n"
    "r.title('a27-backdrop'); r.mainloop()\n"
)


def start_backdrop() -> subprocess.Popen:
    """Plain full-screen colour behind the app so recordings show only the app (the desktop holds
    unrelated private windows). It draws nothing."""
    p = subprocess.Popen([sys.executable, "-c", BACKDROP_CODE])
    wait_window(p.pid, "a27-backdrop")
    return p




def child_buttons(hwnd: int) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Visible push buttons of a native dialog: (text, screen rect)."""
    out: list[tuple[str, tuple[int, int, int, int]]] = []

    def cb(h, _):
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(h, cls, 64)
        if cls.value == "Button" and user32.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(128)
            user32.GetWindowTextW(h, buf, 128)
            out.append((buf.value, rect(h)))
        return True

    user32.EnumChildWindows(wt.HWND(hwnd), WNDENUMPROC(cb), 0)
    return out
