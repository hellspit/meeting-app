"""Platform detection and honest capability reporting.

This app was built on Windows, where SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)
genuinely excludes the overlay from screen capture. That guarantee does NOT exist
on every platform, and the difference matters more here than anywhere else in the
codebase: if the shield silently does nothing, the overlay is visible to everyone
on the call — the exact failure this tool exists to avoid.

So capability is reported explicitly rather than assumed, and `src/main.py` gates
startup on it. The rule we encode:

  Windows 10 2004+   SetWindowDisplayAffinity works                 -> OK
  macOS <= 14        NSWindow.sharingType blocks LEGACY capture     -> LEGACY_ONLY
  macOS 15+          Apple composites to one framebuffer that
                     ScreenCaptureKit reads; the flag is ignored,
                     and Apple states there is no public API        -> UNAVAILABLE
  Linux (X11)        any client can read the full framebuffer       -> UNAVAILABLE
  Linux (Wayland)    consent-based portal; no self-exclusion proto  -> UNAVAILABLE

Only OK means "hidden from a screen share". LEGACY_ONLY means older/simpler
capture paths are blocked but a modern meeting app is not — which is not good
enough to rely on, so it is treated as unsafe by the startup gate.
"""

from __future__ import annotations

import platform as _platform
import sys
from dataclasses import dataclass

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# Shield status values.
SHIELD_OK = "ok"
SHIELD_LEGACY_ONLY = "legacy_only"
SHIELD_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ShieldCapability:
    """What this OS can actually promise about hiding the overlay."""

    status: str
    detail: str

    @property
    def hides_from_screen_share(self) -> bool:
        """True only when a modern meeting app genuinely cannot see the overlay."""
        return self.status == SHIELD_OK


def os_name() -> str:
    if IS_WINDOWS:
        return f"Windows {_platform.release()}"
    if IS_MACOS:
        return f"macOS {_platform.mac_ver()[0] or _platform.release()}"
    if IS_LINUX:
        return f"Linux ({session_type()})"
    return sys.platform


def macos_major() -> int:
    """Major macOS version (15 = Sequoia, 26 = the 2025+ scheme). 0 if unknown."""
    if not IS_MACOS:
        return 0
    ver = _platform.mac_ver()[0]
    if not ver:
        return 0
    try:
        return int(ver.split(".")[0])
    except ValueError:
        return 0


def session_type() -> str:
    """'wayland' / 'x11' / 'unknown' — only meaningful on Linux."""
    import os

    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    xdg = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
    if xdg in ("wayland", "x11"):
        return xdg
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def shield_capability() -> ShieldCapability:
    """Report what window-level capture exclusion this OS can actually deliver."""
    if IS_WINDOWS:
        return ShieldCapability(
            SHIELD_OK,
            "SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE) — verified by read-back",
        )
    if IS_MACOS:
        major = macos_major()
        if major and major < 15:
            return ShieldCapability(
                SHIELD_LEGACY_ONLY,
                f"macOS {major}: NSWindow.sharingType blocks legacy capture APIs, "
                "but not ScreenCaptureKit — modern meeting apps can still see it",
            )
        return ShieldCapability(
            SHIELD_UNAVAILABLE,
            "macOS 15+ composites all windows into one framebuffer that "
            "ScreenCaptureKit captures; NSWindow.sharingType is ignored and Apple "
            "provides no public API to prevent capture",
        )
    if IS_LINUX:
        if session_type() == "wayland":
            return ShieldCapability(
                SHIELD_UNAVAILABLE,
                "Wayland screen sharing is consent-based via xdg-desktop-portal; "
                "there is no protocol for a window to exclude itself from a stream",
            )
        return ShieldCapability(
            SHIELD_UNAVAILABLE,
            "X11 grants every client access to the full framebuffer; no window-level "
            "capture exclusion exists",
        )
    return ShieldCapability(SHIELD_UNAVAILABLE, f"unknown platform {sys.platform!r}")
