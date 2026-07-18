"""Live audio pipeline: capture -> preprocess -> VAD -> transcription.

Runs a worker thread that drains the capture ring buffer, converts to 16 kHz
mono, runs Silero VAD to cut complete utterances, and transcribes each via
OpenAI. Transcription happens on a single background worker so the drain/VAD
loop never blocks (and transcripts stay in order).

It's a QObject: results are delivered as Qt signals (`status`, `transcript`,
`error`) which Qt marshals to the UI thread, so overlay widgets are only ever
touched on the main thread.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal

from src.audio.capture import AudioCapture
from src.audio.preprocess import bytes_to_mono16k
from src.config import Config
from src.stt.transcriber import Transcriber

# NOTE: src.audio.vad (and thus torch) is imported lazily in start(), off the
# UI thread, so launching the app doesn't pay the ~1-2s torch import up front.


class Pipeline(QObject):
    status = Signal(str, str)   # (field, state) for the overlay status row
    transcript = Signal(str)    # a completed transcribed utterance
    error = Signal(str)

    def __init__(self, cfg: Config, client):
        super().__init__()
        self._cfg = cfg
        self.capture = AudioCapture(
            cfg,
            on_status=lambda f, s: self.status.emit(f, s),
            on_error=lambda m: self.error.emit(m),
        )
        self.transcriber = Transcriber(
            client,
            model=str(cfg.get("stt.model", "gpt-4o-mini-transcribe")),
            language=str(cfg.get("stt.language", "en")),
        )
        self.vad: StreamingVAD | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")

    def start(self) -> None:
        self.status.emit("stt", "loading")
        try:
            from src.audio.vad import StreamingVAD  # imports torch (deferred)
            self.vad = StreamingVAD(self._cfg)  # loads Silero (CPU)
        except Exception as e:  # noqa: BLE001
            self.status.emit("stt", "error")
            self.error.emit(f"VAD load failed: {type(e).__name__}: {e}")
            return
        self.status.emit("stt", "ready")

        self.capture.start()  # sets rate/channels, emits capture status
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="pipeline", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        assert self.vad is not None
        while not self._stop.is_set():
            raw = self.capture.read()
            if raw:
                mono = bytes_to_mono16k(raw, self.capture.channels, self.capture.rate)
                for utt in self.vad.feed(mono):
                    self._exec.submit(self._transcribe, utt)
            self._stop.wait(0.05)

    def _transcribe(self, utt) -> None:
        try:
            text = self.transcriber.transcribe(utt)
        except Exception as e:  # noqa: BLE001
            # A single failed transcription is recoverable — the SDK already
            # retried transient errors. Log it, but keep STT "ready" so one bad
            # call doesn't freeze the UI in Error; the next utterance proceeds.
            self.error.emit(f"transcribe failed (skipped): {type(e).__name__}: {e}")
            self.status.emit("stt", "ready")
            return
        if text:
            self.transcript.emit(text)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self.capture.stop()
        self._exec.shutdown(wait=False)
