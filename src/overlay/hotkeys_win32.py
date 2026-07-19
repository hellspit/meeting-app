"""Windows hotkey backend: Win32 RegisterHotKey + a dedicated message loop.

A daemon thread registers the hotkeys and pumps GetMessageW. When hwnd is NULL,
WM_HOTKEY is posted to the registering thread's queue, so the loop must live on
the same thread that registered. Shutdown posts WM_QUIT and unregisters from that
owning thread.

We avoid the `keyboard` package (needs elevation, trips some AV); RegisterHotKey
needs no special privilege.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

from src.overlay.hotkeys import Binding

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000  # ignore auto-repeat while held

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

_MOD_FLAGS = {"alt": MOD_ALT, "ctrl": MOD_CONTROL, "shift": MOD_SHIFT}

# Virtual-key codes for the keys our bindings use.
_VK = {
    "a": 0x41, "e": 0x45, "h": 0x48, "s": 0x53, "t": 0x54, "q": 0x51,
    "space": 0x20,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "[": 0xDB, "]": 0xDD,
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


class Win32HotkeyBackend:
    def __init__(self, bindings: dict[str, Binding], on_action: Callable[[str], None]):
        self._bindings = bindings
        self._on_action = on_action
        self._id_to_action: dict[int, str] = {}
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self.failures: list[str] = []
        self.permission_hint: str | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def _run(self) -> None:
        self._thread_id = _kernel32.GetCurrentThreadId()
        for i, (action, binding) in enumerate(self._bindings.items(), start=1):
            mods = 0
            for m in binding.mods:
                mods |= _MOD_FLAGS[m]
            vk = _VK.get(binding.key)
            if vk is None:
                self.failures.append(binding.label())
                continue
            if _user32.RegisterHotKey(None, i, mods | MOD_NOREPEAT, vk):
                self._id_to_action[i] = action
            else:
                self.failures.append(binding.label())
        self._ready.set()

        msg = _MSG()
        while True:
            ret = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret in (0, -1):  # WM_QUIT or error
                break
            if msg.message == WM_HOTKEY:
                action = self._id_to_action.get(int(msg.wParam))
                if action:
                    self._on_action(action)

        for hk_id in list(self._id_to_action):
            _user32.UnregisterHotKey(None, hk_id)

    def stop(self) -> None:
        if self._thread_id is not None:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
