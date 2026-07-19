"""Global hotkeys — fire even while the meeting app is focused.

Never alt-tabbing matters: switching windows to reach the overlay is exactly the
tell this tool exists to avoid. So every action is bound to a system-wide chord.

Bindings are declared once, platform-neutrally (modifiers + key name), and each
backend renders them into its own format:

- Windows: Win32 RegisterHotKey on a dedicated thread running a GetMessageW loop.
  Chords are registered with the OS, so they're reliable and can't be swallowed.
- macOS / Linux X11: pynput's GlobalHotKeys listener. On macOS this requires
  Accessibility permission (System Settings > Privacy & Security > Accessibility);
  without it the listener runs but never receives events, so we surface a hint.

Either way `triggered(action)` is a Qt signal, so handlers run on the UI thread
and widget code never touches a background thread.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from src.platform import IS_MACOS, IS_WINDOWS


@dataclass(frozen=True)
class Binding:
    """A chord, independent of any OS API."""

    mods: tuple[str, ...]  # any of: ctrl, alt, shift
    key: str               # 'a', 'space', 'left', '[', ...

    def label(self) -> str:
        """Human-readable chord, using each platform's conventional names."""
        # On Mac keyboards Alt is engraved Option; Ctrl+Opt reads correctly there.
        names = {"ctrl": "Ctrl", "alt": "Opt" if IS_MACOS else "Alt", "shift": "Shift"}
        pretty = {"space": "Space", "left": "Left", "up": "Up",
                  "right": "Right", "down": "Down"}
        parts = [names[m] for m in self.mods]
        parts.append(pretty.get(self.key, self.key.upper()))
        return "+".join(parts)

    def pynput_spec(self) -> str:
        """pynput GlobalHotKeys format, e.g. '<ctrl>+<alt>+a'."""
        special = {"space", "left", "up", "right", "down"}
        key = f"<{self.key}>" if self.key in special else self.key
        return "+".join([f"<{m}>" for m in self.mods] + [key])


# action -> chord. Ctrl+Alt is unlikely to clash with meeting apps and is easy to
# hit one-handed. Emergency erase uses Ctrl+Shift so it can't be fat-fingered.
DEFAULT_BINDINGS: dict[str, Binding] = {
    "answer_now":          Binding(("ctrl", "alt"), "a"),
    "toggle_auto":         Binding(("ctrl", "alt"), "space"),
    "analyze_screen":      Binding(("ctrl", "alt"), "s"),
    "emergency_erase":     Binding(("ctrl", "shift"), "e"),
    "history_prev":        Binding(("ctrl", "alt"), "["),
    "history_next":        Binding(("ctrl", "alt"), "]"),
    "toggle_visible":      Binding(("ctrl", "alt"), "h"),
    "toggle_clickthrough": Binding(("ctrl", "alt"), "t"),
    "quit":                Binding(("ctrl", "alt"), "q"),
    "move_left":           Binding(("ctrl", "alt"), "left"),
    "move_up":             Binding(("ctrl", "alt"), "up"),
    "move_right":          Binding(("ctrl", "alt"), "right"),
    "move_down":           Binding(("ctrl", "alt"), "down"),
}


class HotkeyManager(QObject):
    """Registers global hotkeys; emits `triggered(action_name)` on the UI thread."""

    triggered = Signal(str)

    def __init__(self, bindings: dict[str, Binding] | None = None):
        super().__init__()
        self._bindings = bindings or DEFAULT_BINDINGS
        self.failures: list[str] = []      # labels that failed to register
        self.permission_hint: str | None = None
        self._backend = None

    def start(self) -> None:
        if self._backend is not None:
            return
        if IS_WINDOWS:
            from src.overlay.hotkeys_win32 import Win32HotkeyBackend
            self._backend = Win32HotkeyBackend(self._bindings, self._emit)
            self.backend_name = "Win32 RegisterHotKey"
        else:
            from src.overlay.hotkeys_pynput import PynputHotkeyBackend
            self._backend = PynputHotkeyBackend(self._bindings, self._emit)
            self.backend_name = "pynput GlobalHotKeys"
        self._backend.start()
        self.failures = list(self._backend.failures)
        self.permission_hint = self._backend.permission_hint

    def _emit(self, action: str) -> None:
        # Called from the backend's thread; the Qt signal marshals to the UI thread.
        self.triggered.emit(action)

    def stop(self) -> None:
        if self._backend is not None:
            self._backend.stop()
            self._backend = None

    def labels(self) -> dict[str, str]:
        """action -> human label, for help text."""
        return {action: b.label() for action, b in self._bindings.items()}
