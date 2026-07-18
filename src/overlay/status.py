"""Overlay status: one clear meeting state + a screen-share safety indicator.

Instead of technical pills (capture/STT/LLM), we show a single state that maps
to what's actually happening in the meeting — Ready, Listening, Heard question,
Answering, Muted, Error — plus a small always-visible indicator of whether the
overlay is currently hidden from screen capture (the thing you most need to
trust). Backlog (audio falling behind) shows as a subtle suffix only when it
happens.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

_OK = "#3fb950"
_INFO = "#58a6ff"
_WARN = "#d29922"
_ERR = "#f85149"
_IDLE = "#8b949e"

# state key -> (label, color)
STATES: dict[str, tuple[str, str]] = {
    "ready": ("Ready", _IDLE),
    "listening": ("Listening", _OK),
    "heard_question": ("Heard question", _WARN),
    "answering": ("Answering…", _INFO),
    "muted": ("Muted", _IDLE),
    "error": ("Error", _ERR),
}


class MeetingStatus(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        self._state = QLabel()
        self._state.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._state)
        layout.addStretch(1)

        self._shield = QLabel()
        self._shield.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._shield)

        self._backlog = False
        self.set_state("ready")
        self.set_hidden(False)

    def set_state(self, key: str) -> None:
        text, color = STATES.get(key, STATES["ready"])
        if self._backlog and key in ("listening", "ready", "heard_question"):
            text += "  ·  audio catching up"
        self._state.setText(f"●  {text}")
        self._state.setStyleSheet(f"color:{color}; font-size:12px; font-weight:600;")

    def set_hidden(self, hidden: bool) -> None:
        if hidden:
            self._shield.setText("hidden from share ✓")
            self._shield.setStyleSheet(f"color:{_OK}; font-size:11px;")
        else:
            self._shield.setText("VISIBLE — not hidden")
            self._shield.setStyleSheet(f"color:{_ERR}; font-size:11px; font-weight:600;")

    def set_backlog(self, behind: bool) -> None:
        self._backlog = behind
