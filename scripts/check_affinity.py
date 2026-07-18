r"""M0b — screen-share hiding proof of concept.

Creates a small always-on-top PySide6 window, applies
SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE) once the native HWND exists,
then reads it back with GetWindowDisplayAffinity to CONFIRM the OS accepted it.
That read-back is the M0b gate (per plan.md).

  Programmatic gate (this script): mode reads back as 0x11  -> PASS/FAIL, exit code.
  Visual gate (M1, you do this):   share your screen and confirm the window is
                                    invisible to the viewer. Run with --hold to
                                    keep the window open for that test.

Run (auto-closes after a few seconds, prints result):
    .venv\Scripts\python.exe scripts\check_affinity.py

Run and keep open for a real screen-share test:
    .venv\Scripts\python.exe scripts\check_affinity.py --hold
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

WDA_NONE = 0x00
WDA_EXCLUDEFROMCAPTURE = 0x11  # Windows 10 2004+ / Windows 11

_user32 = ctypes.windll.user32
_user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
_user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
_user32.GetWindowDisplayAffinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowDisplayAffinity.restype = wintypes.BOOL


def apply_exclude_from_capture(hwnd: int) -> tuple[bool, int]:
    """Set WDA_EXCLUDEFROMCAPTURE and read it back.

    Returns (ok, mode) where ok means the set call succeeded AND the read-back
    mode equals WDA_EXCLUDEFROMCAPTURE. `mode` is whatever the OS reports.
    """
    set_ok = bool(_user32.SetWindowDisplayAffinity(wintypes.HWND(hwnd), WDA_EXCLUDEFROMCAPTURE))
    mode = wintypes.DWORD(0)
    get_ok = bool(_user32.GetWindowDisplayAffinity(wintypes.HWND(hwnd), ctypes.byref(mode)))
    ok = set_ok and get_ok and mode.value == WDA_EXCLUDEFROMCAPTURE
    return ok, mode.value


class AffinityProbe(QWidget):
    def __init__(self, hold: bool):
        super().__init__()
        self._hold = hold
        self._applied = False
        self.result_ok = False
        self.result_mode = -1

        self.setWindowTitle("affinity-probe")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # keep it off the taskbar
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.resize(360, 120)

        self._label = QLabel("Applying capture exclusion…")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(
            "color: #eaeaea; background: #202225; font-size: 14px; padding: 12px;"
            "border: 2px solid #4c8bf5; border-radius: 8px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

    def showEvent(self, event):  # noqa: N802 (Qt override)
        super().showEvent(event)
        # HWND is only valid after the window is actually shown. Apply once.
        if self._applied:
            return
        self._applied = True
        hwnd = int(self.winId())
        self.result_ok, self.result_mode = apply_exclude_from_capture(hwnd)

        status = "HIDDEN (mode=0x%02x)" % self.result_mode if self.result_ok \
            else "FAILED (mode=0x%02x)" % self.result_mode
        if self._hold:
            self._label.setText(
                f"Affinity: {status}\n\nShare your screen now.\n"
                "You should see this window; the viewer should NOT.\n"
                "Press Esc to close."
            )
        else:
            self._label.setText(f"Affinity: {status}\nClosing…")
            # Quit explicitly: Qt.Tool windows are NOT counted toward
            # quitOnLastWindowClosed, so self.close() alone would hang exec().
            QTimer.singleShot(3000, QApplication.quit)

    def keyPressEvent(self, event):  # noqa: N802 (Qt override)
        if event.key() == Qt.Key.Key_Escape:
            QApplication.quit()


def main() -> int:
    hold = "--hold" in sys.argv[1:]
    app = QApplication(sys.argv)
    probe = AffinityProbe(hold=hold)
    probe.show()
    app.exec()

    print("=" * 60)
    print("M0b - SetWindowDisplayAffinity read-back")
    mark = "PASS" if probe.result_ok else "FAIL"
    print(f"[{mark}] read-back mode = 0x%02x "
          f"(expected 0x%02x = WDA_EXCLUDEFROMCAPTURE)"
          % (probe.result_mode, WDA_EXCLUDEFROMCAPTURE))
    if not probe.result_ok:
        print("       The OS did not accept capture exclusion. Requires "
              "Windows 10 2004+ / 11.")
    print("=" * 60)
    return 0 if probe.result_ok else 1


if __name__ == "__main__":
    sys.exit(main())
