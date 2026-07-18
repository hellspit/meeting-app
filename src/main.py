r"""Entry point.

Run from the project root so `src` is importable:
    .venv\Scripts\python.exe -m src.main            # live overlay + hotkeys + chat
    .venv\Scripts\python.exe -m src.main --demo --hold        # interactive demo
    .venv\Scripts\python.exe -m src.main --demo --seconds 3   # quick self-check

Live now (need OPENAI_API_KEY in .env):
  - Chat box: type a question, Enter -> streamed answer (remembers context).
  - Ctrl+Alt+S: analyze the screen; follow-up questions keep that image in context.
  - Ctrl+Alt+A: jump to the chat box.
Audio -> transcription (answer spoken questions automatically) lands in M4.
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import threading
from collections import deque

from dotenv import load_dotenv
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from src.ai.conversation import Conversation
from src.ai.screen import capture_monitor_png
from src.ai.worker import StreamWorker
from src.config import load_config
from src.core.pipeline import Pipeline
from src.overlay.hotkeys import HotkeyManager
from src.overlay.window import OverlayWindow

_DEMO_TRANSCRIPT = (
    "Them: Can you give us a quick status on the billing migration, and are we "
    "still on track for the end of the month?"
)
_DEMO_ANSWER = (
    "Say this:\n"
    "• Ledger API cutover is done in staging; prod is behind a flag.\n"
    "• On track for month-end for the read path; write path needs 2 more days.\n"
    "• Risk: reconciliation job still manual — I'll confirm the date by Thursday."
)


# Held for the process lifetime so the named mutex stays owned.
_INSTANCE_MUTEX = None
_ERROR_ALREADY_EXISTS = 183


def _is_already_running() -> bool:
    """True if another instance already owns the named mutex.

    Global hotkeys are system-exclusive, so a second instance would fail to
    register them and put a duplicate overlay on screen. This blocks that.
    """
    global _INSTANCE_MUTEX
    # Session-local namespace (no "Global\\") — needs no special privilege and
    # is exactly the scope we want: one instance per logged-in user session.
    _INSTANCE_MUTEX = ctypes.windll.kernel32.CreateMutexW(
        None, False, "MeetingAssistantOverlay_singleinstance")
    if not _INSTANCE_MUTEX:
        return False  # couldn't create the mutex; don't block startup
    return ctypes.windll.kernel32.GetLastError() == _ERROR_ALREADY_EXISTS


# Follow-up quick actions: refine the CURRENT answer (uses conversation memory).
_FOLLOWUP_PROMPTS = {
    "shorter": "Make that shorter — just the key point in one or two sentences.",
    "deeper": "Go a bit deeper on that — add the key detail I might get asked next.",
    "example": "Explain that with a concrete example.",
    "code": "Show me the code for that, as plain pasteable lines.",
    "natural": "Rephrase that to sound natural and conversational, like I'm just speaking.",
}

_Q_WORDS = {
    "what", "what's", "why", "how", "when", "where", "who", "which", "whose",
    "can", "could", "would", "will", "do", "does", "did", "is", "are", "should",
    "tell", "explain", "describe", "define", "give", "walk", "have",
}
_Q_STARTS = ("tell me", "walk me", "how would", "what is", "what's", "can you",
             "could you", "would you", "do you", "have you", "explain",
             "describe", "give me", "what are", "why do", "how do")


def looks_like_question(text: str) -> bool:
    """Heuristic: does this utterance read like a question to answer?"""
    t = text.strip().lower()
    if not t:
        return False
    if t.endswith("?"):
        return True
    if any(t.startswith(p) for p in _Q_STARTS):
        return True
    first = t.split()[0].strip(",.")
    return first in _Q_WORDS


def _print_hotkey_help(hk: HotkeyManager) -> None:
    labels = hk.labels()
    print("Hotkeys (work even while the meeting app is focused):")
    print(f"  answer spoken Q ..... {labels['answer_now']}  (or focus chat box if silent)")
    print(f"  toggle auto-answer .. {labels['toggle_auto']}")
    print(f"  prev / next answer .. {labels['history_prev']} / {labels['history_next']}")
    print(f"  analyze SCREEN ...... {labels['analyze_screen']}")
    print(f"  EMERGENCY ERASE ..... {labels['emergency_erase']}")
    print(f"  show / hide ......... {labels['toggle_visible']}")
    print(f"  click-through toggle  {labels['toggle_clickthrough']}")
    print(f"  move ................ {labels['move_left']} / Right / Up / Down")
    print(f"  quit ................ {labels['quit']}")
    if hk.failures:
        print(f"  [warn] failed to register (in use by another app?): "
              f"{', '.join(hk.failures)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true",
                    help="inject placeholder content and healthy statuses")
    ap.add_argument("--seconds", type=float, default=0.0,
                    help="auto-quit after N seconds (0 = stay open)")
    ap.add_argument("--hold", action="store_true",
                    help="stay open (for a manual screen-share / hotkey test)")
    args = ap.parse_args()

    if not args.demo and _is_already_running():
        print("Meeting Assistant is already running (Ctrl+Alt+Q to quit it).")
        return 0

    load_dotenv()  # OPENAI_API_KEY for chat / screen analysis
    cfg = load_config()
    app = QApplication(sys.argv)
    # We own the lifecycle explicitly (quit hotkey / Esc / --seconds timer). A
    # translucent Qt.Tool overlay isn't counted toward quitOnLastWindowClosed.
    app.setQuitOnLastWindowClosed(False)
    win = OverlayWindow(cfg)
    win.show()

    if args.demo:
        win.set_transcript(_DEMO_TRANSCRIPT)
        win.append_answer(_DEMO_ANSWER)
        win.set_status("capture", "active")
        win.set_status("stt", "ready")
        win.set_status("claude", "ready")

    # --- OpenAI wiring (lazy: only built when a network action first fires) ---
    _client: dict = {"c": None}
    _conv: dict = {"c": None}
    _workers: set[StreamWorker] = set()
    _state = {"busy": False}

    def get_client():
        if _client["c"] is None:
            from openai import OpenAI
            # max_retries: SDK retries transient errors (429 / 5xx / network)
            # with exponential backoff, so a blip doesn't kill the session.
            _client["c"] = OpenAI(max_retries=4)
        return _client["c"]

    def get_conversation() -> Conversation:
        if _conv["c"] is None:
            _conv["c"] = Conversation(
                get_client(),
                model=str(cfg.get("ai.model", "gpt-4o")),
                max_tokens=int(cfg.get("ai.max_answer_tokens", 900)),
            )
        return _conv["c"]

    def stream_into_answer(factory) -> None:
        """Run a text-chunk generator in a worker and stream it into the panel."""
        if _state["busy"]:
            return  # single-flight: ignore while a response is streaming
        _state["busy"] = True
        win.begin_stream()  # clears answer, snaps history view to "live"
        win.set_status("claude", "streaming")
        worker = StreamWorker(factory)
        worker.chunk.connect(win.append_answer)

        def _done():
            win.commit_answer()  # store this turn in the browsable history
            win.set_status("claude", "ready")
            _state["busy"] = False
            _workers.discard(worker)

        def _fail(msg):
            win.append_answer(f"\n[error: {msg}]")
            win.commit_answer()
            win.set_status("claude", "error")
            _state["busy"] = False
            _workers.discard(worker)

        worker.done.connect(_done)
        worker.failed.connect(_fail)
        _workers.add(worker)
        worker.start()

    # Always-on listening. `_heard` is the rolling transcript shown on screen;
    # `_pending` is only the speech SINCE the last answer — i.e. the current
    # question. Answering consumes `_pending` and clears it, so we're instantly
    # ready for the next question no matter when it comes.
    _heard: deque[str] = deque(maxlen=8)
    _pending: list[str] = []
    _auto = {"on": bool(cfg.get("ai.auto_answer", True))}
    _auto_delay = int(cfg.get("ai.auto_answer_delay_ms", 900))
    _auto_timer = QTimer()
    _auto_timer.setSingleShot(True)

    def _pending_has_question() -> bool:
        return any(looks_like_question(p) for p in _pending)

    def on_transcript(text: str) -> None:
        _heard.append(text)
        _pending.append(text)
        if len(_pending) > 12:  # cap if a question is never answered
            del _pending[:-12]
        win.set_transcript(" ".join(_heard))

        is_q = _pending_has_question()
        if _auto["on"]:
            # Re-arm the settle timer on ANY new speech; only answer once the
            # speaker has actually stopped (no new utterance for _auto_delay).
            if is_q or _auto_timer.isActive():
                if is_q:
                    win.notify_question("Question detected — answering when you stop…")
                _auto_timer.start(_auto_delay)
            else:
                win.clear_question()
        else:
            if is_q:
                win.notify_question("Press Ctrl+Alt+A to answer this")
            else:
                win.clear_question()

    def auto_fire() -> None:
        """Fires after the speaker has been silent for _auto_delay."""
        if not _auto["on"] or not _pending_has_question():
            win.clear_question()
            return
        if _state["busy"]:
            _auto_timer.start(400)  # a response is streaming; retry shortly
            return
        answer_last_spoken()

    _auto_timer.timeout.connect(auto_fire)

    def on_followup(key: str) -> None:
        prompt = _FOLLOWUP_PROMPTS.get(key)
        if not prompt:
            return
        try:
            conv = get_conversation()
        except Exception as e:  # noqa: BLE001
            win.clear_answer()
            win.append_answer(f"[needs OPENAI_API_KEY: {e}]")
            win.set_status("claude", "error")
            return
        stream_into_answer(lambda: conv.ask_stream(prompt))

    def answer_last_spoken() -> None:
        """Answer the current question (speech since the last answer)."""
        question = " ".join(_pending).strip()
        if not question:
            win.focus_input()  # nothing new heard — let them type
            return
        try:
            conv = get_conversation()
        except Exception as e:  # noqa: BLE001
            win.clear_answer()
            win.append_answer(f"[needs OPENAI_API_KEY: {e}]")
            win.set_status("claude", "error")
            return
        _pending.clear()  # consumed — ready for the next question immediately
        win.clear_question()
        stream_into_answer(lambda: conv.ask_stream(question))

    def on_question(text: str) -> None:
        try:
            conv = get_conversation()
        except Exception as e:  # noqa: BLE001 - usually a missing key
            win.clear_answer()
            win.append_answer(f"[needs OPENAI_API_KEY: {e}]")
            win.set_status("claude", "error")
            return
        win.set_transcript(f"You asked: {text}")
        stream_into_answer(lambda: conv.ask_stream(text))

    def analyze_screen_action() -> None:
        if not cfg.get("screen.enabled", True):
            return
        try:
            conv = get_conversation()
        except Exception as e:  # noqa: BLE001
            win.clear_answer()
            win.append_answer(f"[screen analysis needs OPENAI_API_KEY: {e}]")
            win.set_status("claude", "error")
            return
        try:
            png = capture_monitor_png(int(cfg.get("screen.target_monitor", 0)))
        except Exception as e:  # noqa: BLE001
            win.set_status("claude", "error")
            win.append_answer(f"\n[screenshot failed: {e}]")
            return
        conv.add_screen(png)
        win.set_transcript("[screen captured — analyzing…]")
        question = str(cfg.get("screen.question", "What's on my screen?"))
        stream_into_answer(lambda: conv.ask_stream(question))

    win.submitted.connect(on_question)
    win.followup.connect(on_followup)
    win.set_auto(_auto["on"])

    # --- live audio pipeline (capture -> VAD -> transcription) ----------------
    # Skipped in --demo so the placeholder text isn't overwritten by real audio.
    pipeline: Pipeline | None = None
    if not args.demo:
        try:
            pipeline = Pipeline(cfg, get_client())  # light: no model load yet
            pipeline.status.connect(win.set_status)
            pipeline.transcript.connect(on_transcript)
            pipeline.error.connect(lambda m: print(f"[pipeline] {m}"))
            app.aboutToQuit.connect(pipeline.stop)
            # Load the VAD (imports torch, ~1-2s) and start capture on a
            # BACKGROUND thread so the overlay is visible and interactive
            # immediately — status shows loading → ready as it comes up.
            threading.Thread(target=pipeline.start, name="pipeline-start",
                             daemon=True).start()
        except Exception as e:  # noqa: BLE001 - e.g. missing key / no loopback
            print(f"[pipeline] not started: {type(e).__name__}: {e}")

    # --- global hotkeys ------------------------------------------------------
    hk = HotkeyManager()

    def on_action(action: str) -> None:
        if action == "quit":
            QApplication.quit()
        elif action == "toggle_visible":
            win.toggle_visibility()
        elif action == "toggle_clickthrough":
            win.toggle_click_through()
        elif action.startswith("move_"):
            win.nudge(action.split("_", 1)[1])
        elif action == "history_prev":
            win.history_prev()
        elif action == "history_next":
            win.history_next()
        elif action == "answer_now":
            answer_last_spoken()
        elif action == "toggle_auto":
            _auto["on"] = not _auto["on"]
            win.set_auto(_auto["on"])
            if not _auto["on"]:
                _auto_timer.stop()
                win.clear_question()
        elif action == "analyze_screen":
            analyze_screen_action()
        elif action == "emergency_erase":
            win.emergency_erase()
            QTimer.singleShot(300, QApplication.quit)

    hk.triggered.connect(on_action)
    hk.start()
    app.aboutToQuit.connect(hk.stop)
    _print_hotkey_help(hk)

    if args.seconds > 0 and not args.hold:
        QTimer.singleShot(int(args.seconds * 1000), QApplication.quit)

    app.exec()

    print("=" * 60)
    print("overlay + hotkeys + chat + screen analysis")
    mark = "PASS" if win.affinity_ok and not hk.failures else "PARTIAL"
    print(f"[{mark}] capture shield: "
          f"{'hidden (0x11)' if win.affinity_ok else 'FAILED'}; "
          f"hotkeys: {len(hk.labels()) - len(hk.failures)}/{len(hk.labels())}")
    print("=" * 60)
    return 0 if win.affinity_ok else 1


if __name__ == "__main__":
    sys.exit(main())
