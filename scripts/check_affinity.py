r"""Capture-shield check — can this platform hide the overlay from a screen share?

Creates a small always-on-top window, applies whatever capture exclusion the OS
offers, and reports honestly.

  Programmatic gate: Windows sets WDA_EXCLUDEFROMCAPTURE and confirms it by
                     read-back. macOS/Linux have no equivalent, so this reports
                     UNAVAILABLE — that is the correct result, not a bug.
  Visual gate:       share your screen and confirm for yourself. Run with --hold
                     to keep the window up while you check.

Run:
    python scripts/check_affinity.py
    python scripts/check_affinity.py --hold
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # import src.*

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from src.overlay.shield import ShieldResult, apply_capture_shield
from src.platform import os_name


class ShieldProbe(QWidget):
    def __init__(self, hold: bool):
        super().__init__()
        self._hold = hold
        self._applied = False
        self.result: ShieldResult | None = None

        self.setWindowTitle("shield-probe")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # keep it off the taskbar
        )
        self.resize(420, 150)

        self._label = QLabel("Applying capture exclusion…")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        self._label.setStyleSheet(
            "color: #eaeaea; background: #202225; font-size: 13px; padding: 12px;"
            "border: 2px solid #4c8bf5; border-radius: 8px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

    def showEvent(self, event):  # noqa: N802 (Qt override)
        super().showEvent(event)
        # The native handle is only valid after the window is shown. Apply once.
        if self._applied:
            return
        self._applied = True
        result = apply_capture_shield(self)
        self.result = result

        status = "HIDDEN" if result.hidden else "NOT HIDDEN"
        if self._hold:
            self._label.setText(
                f"Capture shield: {status}\n\nShare your screen now.\n"
                + (
                    "You should see this window; the viewer should NOT."
                    if result.hidden
                    else "The viewer WILL see this window."
                )
                + "\nPress Esc to close."
            )
        else:
            self._label.setText(f"Capture shield: {status}\nClosing…")
            # Quit explicitly: Qt.Tool windows are NOT counted toward
            # quitOnLastWindowClosed, so self.close() alone would hang exec().
            QTimer.singleShot(3000, QApplication.quit)

    def keyPressEvent(self, event):  # noqa: N802 (Qt override)
        if event.key() == Qt.Key.Key_Escape:
            QApplication.quit()


def main() -> int:
    hold = "--hold" in sys.argv[1:]
    app = QApplication(sys.argv)
    probe = ShieldProbe(hold=hold)
    probe.show()
    app.exec()

    result = probe.result
    print("=" * 66)
    print(f"Capture shield — {os_name()}")
    print("=" * 66)
    mark = "PASS" if (result and result.hidden) else "UNAVAILABLE"
    print(f"[{mark}] {result.detail if result else 'probe did not run'}")
    print(
        f"        applied={result.applied if result else '?'} "
        f"verified={result.verified if result else '?'}"
    )
    if not (result and result.hidden):
        print()
        print("        This platform cannot hide the overlay from a modern")
        print("        screen share. The app will refuse to start unless you")
        print("        pass --i-know-its-visible.")
    print("=" * 66)
    return 0 if (result and result.hidden) else 1


if __name__ == "__main__":
    sys.exit(main())
