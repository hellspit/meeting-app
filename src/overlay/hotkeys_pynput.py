"""macOS / Linux-X11 hotkey backend, built on pynput's GlobalHotKeys.

Unlike Win32 RegisterHotKey, this is not an OS-level registration — it's a
passive listener over the global input stream. Two consequences worth knowing:

1. macOS requires Accessibility permission (System Settings > Privacy & Security
   > Accessibility). Without it the listener starts happily and then never
   receives a single event, which is a miserable thing to debug — so we check
   AXIsProcessTrusted() up front and surface a hint instead.

2. Chords can't be "reserved". If another app consumes the same combination,
   both may fire, or ours may not see it at all. Nothing we can do from here.

macOS layout caveat: Option (Alt) is a character-composing modifier on macOS —
Option+A types 'å'. pynput normalizes this via its canonical() mapping, but the
behavior can vary by keyboard layout. If a chord doesn't respond on your Mac,
remap it in config.yaml under `hotkeys:` rather than editing this file, and use
`scripts/check_hotkeys.py` to see what's actually arriving.
"""

from __future__ import annotations

from typing import Callable

from src.overlay.hotkeys import Binding
from src.platform import IS_MACOS

ACCESSIBILITY_HINT = (
    "macOS has not granted this process Accessibility permission, so global "
    "hotkeys will never fire. Grant it in System Settings > Privacy & Security "
    "> Accessibility (add your terminal or the Python binary), then restart."
)


def macos_accessibility_trusted() -> bool | None:
    """True/False if we can determine Accessibility trust, None if we can't."""
    if not IS_MACOS:
        return None
    try:
        from ApplicationServices import AXIsProcessTrusted
    except Exception:  # noqa: BLE001 - pyobjc framework not present
        return None
    try:
        return bool(AXIsProcessTrusted())
    except Exception:  # noqa: BLE001
        return None


class PynputHotkeyBackend:
    def __init__(self, bindings: dict[str, Binding], on_action: Callable[[str], None]):
        self._bindings = bindings
        self._on_action = on_action
        self._listener = None
        self.failures: list[str] = []
        self.permission_hint: str | None = None

    def start(self) -> None:
        if self._listener is not None:
            return

        if macos_accessibility_trusted() is False:
            self.permission_hint = ACCESSIBILITY_HINT

        try:
            from pynput import keyboard
        except Exception as e:  # noqa: BLE001
            self.failures = [b.label() for b in self._bindings.values()]
            self.permission_hint = f"pynput unavailable ({type(e).__name__}: {e})"
            return

        mapping: dict[str, Callable[[], None]] = {}
        for action, binding in self._bindings.items():
            try:
                spec = binding.pynput_spec()
                keyboard.HotKey.parse(spec)  # validate before we commit to it
            except Exception:  # noqa: BLE001 - unparseable chord for this backend
                self.failures.append(binding.label())
                continue
            # Bind `action` per-iteration; a bare closure would capture the loop var.
            mapping[spec] = (lambda a=action: self._on_action(a))

        if not mapping:
            return
        try:
            self._listener = keyboard.GlobalHotKeys(mapping)
            self._listener.start()
        except Exception as e:  # noqa: BLE001
            self._listener = None
            self.failures = [b.label() for b in self._bindings.values()]
            self.permission_hint = self.permission_hint or (
                f"could not start global hotkey listener ({type(e).__name__}: {e})")

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:  # noqa: BLE001
                pass
            self._listener = None
