"""Run a text-chunk generator off the UI thread and stream results to Qt.

Both screen analysis (now) and Claude/GPT answers (M6) produce a stream of text
chunks from a blocking network call. Running that on the Qt main thread would
freeze the overlay, so we run the generator in a plain daemon thread and emit
each chunk as a Qt signal. Signals use AutoConnection: because the receiver
(the overlay) lives on the main thread, its slots run there — safe for widgets.

Keep a reference to the returned StreamWorker until `done`/`failed` fires, or it
(and its thread) may be garbage-collected mid-stream.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator

from PySide6.QtCore import QObject, Signal


class StreamWorker(QObject):
    chunk = Signal(str)
    done = Signal()
    failed = Signal(str)

    def __init__(self, generator_factory: Callable[[], Iterator[str]]):
        super().__init__()
        self._factory = generator_factory
        self._thread: threading.Thread | None = None

    def start(self) -> StreamWorker:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        try:
            for piece in self._factory():
                self.chunk.emit(piece)
            self.done.emit()
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")
