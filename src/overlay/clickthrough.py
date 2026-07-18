"""Mouse click-through via extended window styles.

When enabled, the overlay becomes transparent to the mouse: clicks pass straight
through to whatever is underneath (your meeting app), so the panel never gets in
your way. A hotkey toggles it off so you can grab and move the window.

Mechanism: add WS_EX_TRANSPARENT to the window's extended style. WS_EX_LAYERED is
required alongside it and is already present because the window uses a translucent
background — we keep it set regardless so translucency never breaks.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020

_user32 = ctypes.windll.user32

# On 64-bit Python the *Ptr variants exist and are correct for LONG_PTR styles.
_get = getattr(_user32, "GetWindowLongPtrW", _user32.GetWindowLongW)
_set = getattr(_user32, "SetWindowLongPtrW", _user32.SetWindowLongW)
_get.argtypes = [wintypes.HWND, ctypes.c_int]
_get.restype = ctypes.c_longlong
_set.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
_set.restype = ctypes.c_longlong


def set_click_through(hwnd: int, enabled: bool) -> None:
    style = _get(wintypes.HWND(hwnd), GWL_EXSTYLE)
    if enabled:
        style |= WS_EX_LAYERED | WS_EX_TRANSPARENT
    else:
        # Drop transparency but KEEP layered (translucent background needs it).
        style &= ~WS_EX_TRANSPARENT
        style |= WS_EX_LAYERED
    _set(wintypes.HWND(hwnd), GWL_EXSTYLE, style)
