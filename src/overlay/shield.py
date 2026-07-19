"""Cross-platform capture shield: keep the overlay out of screen recordings.

Each backend does the most its OS allows and reports back honestly. The return
value drives both the overlay status row and the startup gate in `src/main.py`,
so it must never claim more than the OS actually delivers — see
`src/platform/__init__.py` for the per-OS reality.

Windows is the only platform where this is a real guarantee. macOS gets a
best-effort legacy flag that helps on macOS <= 14 and is ignored on 15+. Linux
has nothing to apply.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.platform import (
    IS_LINUX,
    IS_MACOS,
    IS_WINDOWS,
    SHIELD_OK,
    shield_capability,
)


@dataclass(frozen=True)
class ShieldResult:
    """Outcome of trying to shield a specific window."""

    applied: bool          # did the OS accept the call we made?
    verified: bool         # did we read the state back and confirm it?
    hidden: bool           # is it actually hidden from a modern screen share?
    detail: str

    @property
    def status_label(self) -> str:
        """Short label for the overlay status row."""
        if self.hidden:
            return "hidden"
        if self.applied:
            return "partial"
        return "VISIBLE"


# --------------------------------------------------------------------------
# Windows — SetWindowDisplayAffinity, with read-back confirmation.
# --------------------------------------------------------------------------
WDA_EXCLUDEFROMCAPTURE = 0x11  # Windows 10 2004+ / 11


def _apply_windows(window) -> ShieldResult:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
    user32.GetWindowDisplayAffinity.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowDisplayAffinity.restype = wintypes.BOOL

    hwnd = wintypes.HWND(int(window.winId()))
    applied = bool(user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))

    mode = wintypes.DWORD(0)
    verified = bool(user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(mode)))
    hidden = verified and mode.value == WDA_EXCLUDEFROMCAPTURE
    return ShieldResult(
        applied=applied,
        verified=verified,
        hidden=hidden,
        detail=("excluded from capture (0x11), confirmed by read-back" if hidden
                else f"SetWindowDisplayAffinity did not take (mode=0x{mode.value:x})"),
    )


# --------------------------------------------------------------------------
# macOS — NSWindow.sharingType. Real on <= 14, ignored by ScreenCaptureKit on 15+.
# We still set it: it costs nothing and blocks older CoreGraphics-based capture
# paths. But `hidden` follows the OS capability, never the call's return value.
# --------------------------------------------------------------------------
def _apply_macos(window) -> ShieldResult:
    cap = shield_capability()
    try:
        import objc
        from AppKit import NSWindowSharingNone
    except Exception as e:  # noqa: BLE001 - pyobjc missing or broken
        return ShieldResult(
            applied=False, verified=False, hidden=False,
            detail=f"pyobjc unavailable ({type(e).__name__}); no shield applied — "
                   f"{cap.detail}",
        )

    try:
        # Qt's winId() is an NSView* on macOS; its .window() is the NSWindow.
        view = objc.objc_object(c_void_p=int(window.winId()))
        ns_window = view.window()
        if ns_window is None:
            raise RuntimeError("NSView has no NSWindow yet (call after show())")
        ns_window.setSharingType_(NSWindowSharingNone)
        applied = True
        verified = int(ns_window.sharingType()) == int(NSWindowSharingNone)
    except Exception as e:  # noqa: BLE001
        return ShieldResult(
            applied=False, verified=False, hidden=False,
            detail=f"could not set NSWindow.sharingType ({type(e).__name__}: {e})",
        )

    # Honest reporting: applying the flag does not mean a meeting app can't see it.
    return ShieldResult(
        applied=applied,
        verified=verified,
        hidden=(cap.status == SHIELD_OK),  # never true on macOS today
        detail=(f"NSWindow.sharingType=none applied — {cap.detail}"),
    )


# --------------------------------------------------------------------------
# Linux — nothing to apply on either X11 or Wayland.
# --------------------------------------------------------------------------
def _apply_linux(window) -> ShieldResult:  # noqa: ARG001 - uniform signature
    cap = shield_capability()
    return ShieldResult(
        applied=False, verified=False, hidden=False,
        detail=f"no capture-exclusion mechanism on this platform — {cap.detail}",
    )


def apply_capture_shield(window) -> ShieldResult:
    """Shield `window` (a QWidget) as far as this OS allows.

    Call AFTER show() — on both Windows and macOS the native handle must exist.
    """
    if IS_WINDOWS:
        return _apply_windows(window)
    if IS_MACOS:
        return _apply_macos(window)
    if IS_LINUX:
        return _apply_linux(window)
    return ShieldResult(False, False, False, "unsupported platform")
