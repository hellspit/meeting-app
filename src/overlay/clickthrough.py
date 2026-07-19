"""Mouse click-through: let clicks pass to whatever is underneath the overlay.

When enabled the panel stops receiving mouse input entirely, so it never gets in
the way of the meeting app. A hotkey toggles it off so you can grab, move, or
type into the window.

Two backends, because the Windows one is better:

- Windows: add WS_EX_TRANSPARENT to the extended window style. This is a live
  style change — no re-show, no flicker, and the capture shield is untouched.
- macOS / Linux: Qt's WindowTransparentForInput flag. Changing a window flag
  makes Qt recreate the native window, which drops it off screen and can discard
  native state (on macOS, the NSWindow is new, so the sharing-type flag must be
  re-applied). `set_click_through` reports whether that happened so the caller
  can re-shield.
"""

from __future__ import annotations

from src.platform import IS_WINDOWS

if IS_WINDOWS:
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


def _set_click_through_windows(window, enabled: bool) -> bool:
    hwnd = wintypes.HWND(int(window.winId()))
    style = _get(hwnd, GWL_EXSTYLE)
    if enabled:
        style |= WS_EX_LAYERED | WS_EX_TRANSPARENT
    else:
        # Drop transparency but KEEP layered (translucent background needs it).
        style &= ~WS_EX_TRANSPARENT
        style |= WS_EX_LAYERED
    _set(hwnd, GWL_EXSTYLE, style)
    return False  # native window untouched; no re-shield needed


def _set_click_through_qt(window, enabled: bool) -> bool:
    from PySide6.QtCore import Qt

    if bool(window.windowFlags() & Qt.WindowTransparentForInput) == enabled:
        return False  # already in the requested state
    was_visible = window.isVisible()
    window.setWindowFlag(Qt.WindowTransparentForInput, enabled)
    if was_visible:
        window.show()  # flag changes hide the window; bring it back
    return True  # native window was recreated — caller should re-shield


def set_click_through(window, enabled: bool) -> bool:
    """Enable/disable click-through on a QWidget.

    Returns True if the native window was recreated, meaning platform state
    (notably the macOS capture shield) needs re-applying.
    """
    if IS_WINDOWS:
        return _set_click_through_windows(window, enabled)
    return _set_click_through_qt(window, enabled)
