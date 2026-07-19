"""The overlay window.

A frameless, always-on-top panel that shows the live transcript and the streamed
answer, with a status row along the bottom.

On Windows it applies SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE), so it
renders on your physical screen but is excluded from most screen-capture paths,
confirmed by read-back. On macOS and Linux no such guarantee exists (see
`src/platform`), and in that case the panel shows a permanent, unmissable banner
saying so — a silently-visible overlay is the worst possible failure here.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.config import Config
from src.overlay.clickthrough import set_click_through
from src.overlay.shield import ShieldResult, apply_capture_shield
from src.overlay.status import MeetingStatus

# Follow-up quick actions: button label -> action key emitted via `followup`.
FOLLOWUPS = [
    ("Shorter", "shorter"),
    ("Deeper", "deeper"),
    ("Example", "example"),
    ("Code", "code"),
    ("Natural", "natural"),
]


class OverlayWindow(QWidget):
    # Emitted when the user submits a question in the chat box.
    submitted = Signal(str)
    # Emitted when a follow-up quick action is clicked (key from FOLLOWUPS).
    followup = Signal(str)

    def __init__(self, cfg: Config, parent: QWidget | None = None):
        super().__init__(parent)
        self._cfg = cfg
        self._affinity_applied = False
        self.affinity_ok = False
        self.shield: ShieldResult | None = None
        self._click_through = bool(cfg.get("overlay.click_through", False))
        self._demo_timer: QTimer | None = None
        self._nudge_px = 40
        # Answer history: each entry is {"transcript", "answer"}. `_view` is the
        # index being shown; while streaming it points one past the end ("live").
        self._answers: list[dict] = []
        self._view = 0
        self._streaming = False
        # State inputs for the meeting status resolver.
        self._capture: bool | None = None   # None=unknown, True=on, False=off
        self._stt_ready = False
        self._answering = False
        self._question_pending = False
        self._error = False
        self._auto_on = False  # set by main from config

        self.setWindowTitle("meeting-assistant")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # keep off the taskbar
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowOpacity(float(cfg.get("overlay.opacity", 0.92)))

        self._build_ui()
        self._resize_and_place()

    # --- UI ------------------------------------------------------------------
    def _build_ui(self) -> None:
        font_pt = int(self._cfg.get("overlay.font_point_size", 12))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # A rounded "panel" container so WA_TranslucentBackground gives us a
        # card with transparent corners rather than a hard rectangle.
        panel = QWidget()
        panel.setObjectName("panel")
        panel.setStyleSheet(
            "#panel { background: rgba(22, 24, 28, 235); border-radius: 12px;"
            "border: 1px solid rgba(88, 166, 255, 120); }"
        )
        outer.addWidget(panel)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(8)

        self._hint = QLabel("Meeting assistant")
        self._hint.setStyleSheet("color:#8b949e; font-size:11px;")
        layout.addWidget(self._hint)

        # Shown only when the capture shield is NOT protecting this window.
        # Deliberately loud: if this panel is visible to the call, you must know
        # at a glance, not by remembering which OS you're on.
        self._exposed_banner = QLabel("")
        self._exposed_banner.setWordWrap(True)
        self._exposed_banner.setStyleSheet(
            "background: rgba(248, 81, 73, 55); color:#ff9492; "
            "border:1px solid rgba(248,81,73,170); border-radius:7px; "
            "padding:5px 8px; font-size:11px; font-weight:600;"
        )
        self._exposed_banner.setVisible(False)
        layout.addWidget(self._exposed_banner)

        self._transcript = QTextEdit()
        self._transcript.setReadOnly(True)
        self._transcript.setPlaceholderText("Transcript will appear here…")
        self._transcript.setStyleSheet(
            "QTextEdit { background: transparent; color:#c9d1d9; border:none; "
            f"font-size:{font_pt - 1}pt; }}"
        )
        self._transcript.setMaximumHeight(140)
        layout.addWidget(self._transcript)

        # Subtle prompt shown when the last utterance looks like a question.
        self._question_hint = QLabel("")
        self._question_hint.setStyleSheet("color:#d29922; font-size:11px;")
        self._question_hint.setVisible(False)
        layout.addWidget(self._question_hint)

        self._answer_label = QLabel("Suggested answer")
        self._answer_label.setStyleSheet(
            "color:#58a6ff; font-size:11px; font-weight:600;")
        layout.addWidget(self._answer_label)

        self._answer = QTextEdit()
        self._answer.setReadOnly(True)
        self._answer.setPlaceholderText("Press the answer-now hotkey during a question…")
        self._answer.setStyleSheet(
            "QTextEdit { background: transparent; color:#e6edf3; border:none; "
            f"font-size:{font_pt}pt; }}"
        )
        layout.addWidget(self._answer, stretch=1)

        # Follow-up quick actions on the current answer.
        followrow = QHBoxLayout()
        followrow.setContentsMargins(0, 0, 0, 0)
        followrow.setSpacing(5)
        for label, key in FOLLOWUPS:
            btn = QPushButton(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet(
                "QPushButton { background: rgba(88,166,255,28); color:#c9d1d9; "
                "border:1px solid rgba(88,166,255,90); border-radius:7px; "
                "padding:3px 8px; font-size:11px; }"
                "QPushButton:hover { background: rgba(88,166,255,70); }"
            )
            btn.clicked.connect(lambda _=False, k=key: self.followup.emit(k))
            followrow.addWidget(btn)
        layout.addLayout(followrow)

        # Chat box: type a question, Enter to send.
        self._input = QLineEdit()
        self._input.setPlaceholderText("Ask a question…  (Enter to send)")
        self._input.returnPressed.connect(self._on_submit)
        self._input.setStyleSheet(
            "QLineEdit { background: rgba(255,255,255,18); color:#e6edf3; "
            "border: 1px solid rgba(88,166,255,120); border-radius: 8px; "
            f"padding: 6px 10px; font-size:{font_pt}pt; }}"
        )
        layout.addWidget(self._input)

        self._status = MeetingStatus()
        layout.addWidget(self._status)

    def _on_submit(self) -> None:
        text = self._input.text().strip()
        if text:
            self._input.clear()
            self.submitted.emit(text)

    def _resize_and_place(self) -> None:
        w = int(self._cfg.get("overlay.width", 460))
        h = int(self._cfg.get("overlay.height", 520))
        margin = int(self._cfg.get("overlay.margin", 24))
        anchor = str(self._cfg.get("overlay.anchor", "top-right"))
        mon_idx = int(self._cfg.get("overlay.target_monitor", 0))

        self.resize(w, h)

        screens = QGuiApplication.screens()
        if not screens:
            return
        screen = screens[mon_idx] if 0 <= mon_idx < len(screens) else screens[0]
        area = screen.availableGeometry()

        left = "left" in anchor
        top = "top" in anchor
        x = area.left() + margin if left else area.right() - w - margin + 1
        y = area.top() + margin if top else area.bottom() - h - margin + 1
        self.move(x, y)

    # --- Capture shield ------------------------------------------------------
    def showEvent(self, event):  # noqa: N802 (Qt override)
        super().showEvent(event)
        # The native handle is valid only once shown. Apply once, then reflect
        # the honest result in the status row and the exposure banner.
        if not self._affinity_applied:
            self._affinity_applied = True
            self._apply_shield()
            # Honor the configured starting click-through state.
            set_click_through(self, self._click_through)
            self._refresh_hint()

    def _apply_shield(self) -> None:
        """Apply the capture shield and surface exactly what we got."""
        self.shield = apply_capture_shield(self)
        self.affinity_ok = self.shield.hidden
        self._status.set_hidden(self.shield.hidden)
        if self.shield.hidden:
            self._exposed_banner.setVisible(False)
        else:
            self._exposed_banner.setText(
                "⚠  VISIBLE IN SCREEN SHARE — this panel is NOT hidden on this "
                "platform. Anyone you share your screen with can see it.")
            self._exposed_banner.setVisible(True)

    # --- Public API (driven by workers in later milestones) ------------------
    def set_transcript(self, text: str) -> None:
        self._transcript.setPlainText(text)
        self._transcript.moveCursor(self._transcript.textCursor().MoveOperation.End)

    def clear_answer(self) -> None:
        self._answer.clear()

    def append_answer(self, chunk: str) -> None:
        # Insert at the end WITHOUT auto-scrolling: streaming an answer should
        # not yank the view to the bottom while you're reading from the top.
        # We append via a detached cursor and restore the scrollbar position,
        # so wherever you've scrolled to stays put.
        bar = self._answer.verticalScrollBar()
        pos = bar.value()
        cursor = QTextCursor(self._answer.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(chunk)
        bar.setValue(pos)

    def set_status(self, field: str, state: str) -> None:
        """Route low-level pipeline events into the single meeting state.

        Kept as the entry point so the pipeline can stay generic; we translate
        capture/stt/claude/affinity/backlog into one resolved display state.
        """
        if field == "capture":
            if state == "active":
                self._capture, self._error = True, False
            elif state == "inactive":
                self._capture = False
            elif state == "error":
                self._error = True
        elif field == "stt":
            if state == "ready":
                self._stt_ready, self._error = True, False
            elif state == "loading":
                self._stt_ready = False
            elif state == "error":
                self._error = True
        elif field == "claude":
            if state == "streaming":
                self._answering = True
            elif state == "ready":
                self._answering, self._error = False, False
            elif state == "error":
                self._answering, self._error = False, True
        elif field == "affinity":
            self._status.set_hidden(state == "hidden")
            return
        elif field == "backlog":
            self._status.set_backlog(state == "warning")
        self._resolve_state()

    def _resolve_state(self) -> None:
        if self._error:
            key = "error"
        elif self._answering:
            key = "answering"
        elif self._question_pending:
            key = "heard_question"
        elif self._capture is False:
            key = "muted"
        elif self._capture and self._stt_ready:
            key = "listening"
        else:
            key = "ready"
        self._status.set_state(key)

    # --- M2: hotkey-driven controls -----------------------------------------
    def _refresh_hint(self) -> None:
        parts = ["auto-answer ON" if self._auto_on else "auto-answer OFF"]
        if self._click_through:
            parts.append("click-through ON")
        self._hint.setText("Meeting assistant  ·  " + "  ·  ".join(parts))

    def set_auto(self, on: bool) -> None:
        self._auto_on = on
        self._refresh_hint()

    def toggle_visibility(self) -> None:
        self.setVisible(not self.isVisible())

    def focus_input(self) -> None:
        """Bring the overlay forward and put the cursor in the chat box."""
        self.show()
        self.raise_()
        self.activateWindow()
        self._input.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def toggle_click_through(self) -> None:
        self._click_through = not self._click_through
        # On non-Windows this recreates the native window, which discards any
        # platform state attached to it — re-shield so we don't silently lose it.
        if set_click_through(self, self._click_through) and self._affinity_applied:
            self._apply_shield()
        self._refresh_hint()

    def nudge(self, direction: str) -> None:
        dx = {"left": -1, "right": 1}.get(direction, 0) * self._nudge_px
        dy = {"up": -1, "down": 1}.get(direction, 0) * self._nudge_px
        self.move(self.x() + dx, self.y() + dy)

    def emergency_erase(self) -> None:
        """Panic button: stop streaming, wipe visible content AND history, hide.

        The caller is responsible for tearing down the AI session and quitting
        (see main.py) so this stays a pure UI wipe.
        """
        if self._demo_timer is not None:
            self._demo_timer.stop()
        self._answers.clear()
        self._view = 0
        self._streaming = False
        self._answering = False
        self._question_pending = False
        self._error = False
        self._question_hint.setVisible(False)
        self.set_transcript("")
        self.clear_answer()
        self._answer_label.setText("Suggested answer")
        self._resolve_state()
        self.hide()

    # --- Answer streaming lifecycle + history navigation --------------------
    def notify_question(self, hint: str = "Press Ctrl+Alt+A to answer this") -> None:
        """Show the subtle 'this looks like a question' prompt + state."""
        self._question_pending = True
        self._question_hint.setText("❓  " + hint)
        self._question_hint.setVisible(True)
        self._resolve_state()

    def clear_question(self) -> None:
        if self._question_pending or self._question_hint.isVisible():
            self._question_pending = False
            self._question_hint.setVisible(False)
            self._resolve_state()

    def begin_stream(self) -> None:
        """Called when a new answer starts streaming; snaps view to 'live'."""
        self._streaming = True
        self._answering = True
        self._question_pending = False
        self._question_hint.setVisible(False)
        self._view = len(self._answers)
        self.clear_answer()
        self._answer_label.setText("Suggested answer")
        self._resolve_state()

    def commit_answer(self) -> None:
        """Called when streaming finishes; store the turn in history."""
        self._streaming = False
        self._answering = False
        self._resolve_state()
        answer = self._answer.toPlainText().strip()
        if answer:
            self._answers.append({
                "transcript": self._transcript.toPlainText(),
                "answer": self._answer.toPlainText(),
            })
            self._view = len(self._answers) - 1
        self._update_answer_label()

    def history_prev(self) -> None:
        if self._streaming or not self._answers:
            return
        if self._view > 0:
            self._view -= 1
            self._show_history()

    def history_next(self) -> None:
        if self._streaming or not self._answers:
            return
        if self._view < len(self._answers) - 1:
            self._view += 1
            self._show_history()

    def _show_history(self) -> None:
        item = self._answers[self._view]
        self.set_transcript(item["transcript"])
        self._answer.setPlainText(item["answer"])
        self._update_answer_label()

    def _update_answer_label(self) -> None:
        n = len(self._answers)
        if n == 0 or self._view >= n:
            self._answer_label.setText("Suggested answer")
        elif self._view == n - 1:
            self._answer_label.setText(f"Suggested answer  ({n}/{n}, latest)")
        else:
            self._answer_label.setText(f"Suggested answer  ({self._view + 1}/{n})")

    def start_demo_answer(self, text: str) -> None:
        """Typewriter-reveal `text` to mimic a streaming Claude answer (demo)."""
        if self._demo_timer is not None:
            self._demo_timer.stop()
        self.clear_answer()
        self.set_status("claude", "streaming")
        self._demo_chars = list(text)
        self._demo_timer = QTimer(self)
        self._demo_timer.timeout.connect(self._demo_tick)
        self._demo_timer.start(14)

    def _demo_tick(self) -> None:
        if not self._demo_chars:
            if self._demo_timer is not None:
                self._demo_timer.stop()
            self.set_status("claude", "ready")
            return
        self.append_answer(self._demo_chars.pop(0))

    def keyPressEvent(self, event):  # noqa: N802 (Qt override)
        # Standalone convenience; the real app quits via the quit hotkey (M2).
        if event.key() == Qt.Key.Key_Escape:
            QApplication.quit()
