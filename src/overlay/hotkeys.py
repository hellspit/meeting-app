"""Global hotkeys via Win32 RegisterHotKey.

These fire even while the meeting app is focused, so you never alt-tab (which
would look obvious on a shared screen). We avoid the `keyboard` package (needs
elevation, trips some AV); a `pynput` fallback is possible later.

Design: a dedicated daemon thread registers the hotkeys and runs a message loop
(GetMessageW). When hwnd is NULL, WM_HOTKEY is posted to the registering thread's
queue. On WM_HOTKEY we emit `triggered(action)` — a Qt signal — which Qt delivers
to the main/UI thread, so widget code never runs on the hotkey thread. Shutdown
posts WM_QUIT to the loop and unregisters everything (from the owning thread).
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal

# Modifier flags for RegisterHotKey.
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000  # ignore auto-repeat while held

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

# Virtual-key codes we use.
VK = {
    "A": 0x41, "E": 0x45, "H": 0x48, "S": 0x53, "T": 0x54, "Q": 0x51,
    "SPACE": 0x20,
    "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
    "LBRACKET": 0xDB, "RBRACKET": 0xDD,  # [ and ]
}

# action -> (modifiers, vk, human label). Ctrl+Alt chords are unlikely to clash
# with meeting apps and are easy to hit one-handed.
DEFAULT_BINDINGS: dict[str, tuple[int, int, str]] = {
    "answer_now":          (MOD_CONTROL | MOD_ALT, VK["A"], "Ctrl+Alt+A"),
    "toggle_auto":         (MOD_CONTROL | MOD_ALT, VK["SPACE"], "Ctrl+Alt+Space"),
    "analyze_screen":      (MOD_CONTROL | MOD_ALT, VK["S"], "Ctrl+Alt+S"),
    "emergency_erase":     (MOD_CONTROL | MOD_SHIFT, VK["E"], "Ctrl+Shift+E"),
    "history_prev":        (MOD_CONTROL | MOD_ALT, VK["LBRACKET"], "Ctrl+Alt+["),
    "history_next":        (MOD_CONTROL | MOD_ALT, VK["RBRACKET"], "Ctrl+Alt+]"),
    "toggle_visible":      (MOD_CONTROL | MOD_ALT, VK["H"], "Ctrl+Alt+H"),
    "toggle_clickthrough": (MOD_CONTROL | MOD_ALT, VK["T"], "Ctrl+Alt+T"),
    "quit":                (MOD_CONTROL | MOD_ALT, VK["Q"], "Ctrl+Alt+Q"),
    "move_left":           (MOD_CONTROL | MOD_ALT, VK["LEFT"], "Ctrl+Alt+Left"),
    "move_up":             (MOD_CONTROL | MOD_ALT, VK["UP"], "Ctrl+Alt+Up"),
    "move_right":          (MOD_CONTROL | MOD_ALT, VK["RIGHT"], "Ctrl+Alt+Right"),
    "move_down":           (MOD_CONTROL | MOD_ALT, VK["DOWN"], "Ctrl+Alt+Down"),
}

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt_x", wintypes.LONG),
        ("pt_y", wintypes.LONG),
    ]


_user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
_user32.RegisterHotKey.restype = wintypes.BOOL
_user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.UnregisterHotKey.restype = wintypes.BOOL
_user32.GetMessageW.argtypes = [ctypes.POINTER(_MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
_user32.GetMessageW.restype = ctypes.c_int
_user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.PostThreadMessageW.restype = wintypes.BOOL


class HotkeyManager(QObject):
    """Registers global hotkeys; emits `triggered(action_name)` on the UI thread."""

    triggered = Signal(str)

    def __init__(self, bindings: dict[str, tuple[int, int, str]] | None = None):
        super().__init__()
        self._bindings = bindings or DEFAULT_BINDINGS
        self._id_to_action: dict[int, str] = {}
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self.failures: list[str] = []  # labels that failed to register

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def _run(self) -> None:
        self._thread_id = _kernel32.GetCurrentThreadId()
        for i, (action, (mods, vk, label)) in enumerate(self._bindings.items(), start=1):
            ok = _user32.RegisterHotKey(None, i, mods | MOD_NOREPEAT, vk)
            if ok:
                self._id_to_action[i] = action
            else:
                self.failures.append(label)
        self._ready.set()

        msg = _MSG()
        while True:
            ret = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret in (0, -1):  # WM_QUIT or error
                break
            if msg.message == WM_HOTKEY:
                action = self._id_to_action.get(int(msg.wParam))
                if action:
                    self.triggered.emit(action)

        for hk_id in list(self._id_to_action):
            _user32.UnregisterHotKey(None, hk_id)

    def stop(self) -> None:
        if self._thread_id is not None:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def labels(self) -> dict[str, str]:
        """action -> human label, for help text."""
        return {action: label for action, (_, _, label) in self._bindings.items()}
