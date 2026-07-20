"""System-audio loopback capture into a drop-oldest ring buffer, with recovery.

A worker thread reads system-output audio (the meeting) and pushes it into a
bounded ring buffer (drop-oldest on overflow → "backlog"). It also RECOVERS from
real-world audio disruptions instead of dying:

- If the device is unplugged / disconnected (read raises), it reopens on the new
  default output — retrying with backoff until the device returns.
- If you switch the default output device mid-meeting (both present, no error),
  a periodic check notices and switches capture to follow it.

The platform-specific part — which device counts as "the meeting's audio" and how
to open it — lives behind `src.audio.loopback`. Everything here is shared.

Status/errors are reported via plain callbacks so this module stays Qt-agnostic.
"""

from __future__ import annotations

import contextlib
import threading
from collections import deque
from collections.abc import Callable

from src.audio.loopback import (
    LoopbackStream,
    current_default_output_name,
    open_loopback,
)
from src.config import Config

StatusCb = Callable[[str, str], None]
ErrorCb = Callable[[str], None]


class RingBuffer:
    """Thread-safe byte ring with drop-oldest overflow and a dropped counter."""

    def __init__(self, max_bytes: int):
        self._chunks: deque[bytes] = deque()
        self._size = 0
        self._max = max_bytes
        self._lock = threading.Lock()
        self.dropped_bytes = 0

    def push(self, data: bytes) -> int:
        with self._lock:
            self._chunks.append(data)
            self._size += len(data)
            dropped = 0
            while self._size > self._max and self._chunks:
                old = self._chunks.popleft()
                self._size -= len(old)
                dropped += len(old)
            self.dropped_bytes += dropped
            return dropped

    def pop_all(self) -> bytes:
        with self._lock:
            data = b"".join(self._chunks)
            self._chunks.clear()
            self._size = 0
            return data

    def __len__(self) -> int:
        with self._lock:
            return self._size


class AudioCapture:
    """Captures system-output audio on a worker thread into a RingBuffer."""

    SAMPLE_BYTES = 4  # float32

    def __init__(
        self,
        cfg: Config,
        on_status: StatusCb | None = None,
        on_error: ErrorCb | None = None,
        ring_bytes_override: int | None = None,
    ):
        self._cfg = cfg
        self._on_status = on_status or (lambda *_: None)
        self._on_error = on_error or (lambda *_: None)
        self._ring_bytes_override = ring_bytes_override
        self._device_check_s = float(cfg.get("audio.device_check_seconds", 0))

        self._stream: LoopbackStream | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._backlog = False
        self._frames_per_buffer = 0
        self._default_out_name: str | None = None

        self.rate = 0
        self.channels = 0
        self.device_name = ""
        self.ring: RingBuffer | None = None
        self.last_error: str | None = None

    # --- open / recover ------------------------------------------------------
    def _open_stream(self) -> bool:
        """Open the platform loopback stream and (re)create the ring buffer.

        The ring is rebuilt on every open so we never mix samples from two
        device formats. Returns True on success; emits capture 'error' otherwise.
        """
        try:
            self._teardown_stream()
            self._stream = open_loopback(self._cfg)
            frame_ms = int(self._cfg.get("audio.frame_ms", 30))
            self._frames_per_buffer = self._stream.open(frame_ms)

            self.rate = self._stream.rate
            self.channels = self._stream.channels
            self.device_name = self._stream.device_name
            self._default_out_name = self._stream.default_output_name

            secs = float(self._cfg.get("audio.ring_buffer_seconds", 30))
            ring_bytes = self._ring_bytes_override or int(
                secs * self.rate * self.channels * self.SAMPLE_BYTES
            )
            self.ring = RingBuffer(ring_bytes)
            self.last_error = None
            return True
        except Exception as e:  # noqa: BLE001
            self.last_error = f"{type(e).__name__}: {e}"
            self._on_status("capture", "error")
            self._on_error(f"capture open failed: {e}")
            self._teardown_stream()
            return False

    def _recover(self) -> None:
        """Reopen capture on the current default device, backing off until it works."""
        backoff = 0.5
        while not self._stop.is_set():
            if self._open_stream():
                self._on_status("capture", "active")
                self._on_error(f"audio capture recovered on {self.device_name!r}")
                return
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 5.0)

    def start(self) -> None:
        if not self._open_stream():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="capture", daemon=True)
        self._thread.start()
        self._on_status("capture", "active")

    # --- capture loop --------------------------------------------------------
    def _run(self) -> None:
        frames_since_check = 0
        while not self._stop.is_set():
            stream = self._stream
            if stream is None:
                # Only possible if stop was requested while recovery was still
                # failing; the loop condition exits on the next check.
                continue
            try:
                raw = stream.read(self._frames_per_buffer)
            except OSError as e:
                # Device unplugged / disconnected mid-meeting → recover.
                if self._stop.is_set():
                    return  # shutdown aborted the read; not a real failure
                self._on_status("capture", "error")
                self._on_error(f"audio device interrupted: {e}; recovering…")
                self._recover()
                frames_since_check = 0
                continue

            if self.ring is not None:
                self._update_backlog(self.ring.push(raw) > 0)

            if self._device_check_s > 0:
                frames_since_check += 1
                check_every = max(
                    1,
                    int(
                        self.rate
                        * self._device_check_s
                        / max(1, self._frames_per_buffer)
                    ),
                )
                if frames_since_check >= check_every:
                    frames_since_check = 0
                    self._maybe_follow_default_change()

    def _maybe_follow_default_change(self) -> None:
        name = current_default_output_name()
        if name and self._default_out_name and name != self._default_out_name:
            self._on_status("capture", "error")
            self._on_error(f"default output changed to {name!r}; switching…")
            self._recover()

    def _update_backlog(self, dropping: bool) -> None:
        if dropping and not self._backlog:
            self._backlog = True
            self._on_status("backlog", "warning")
        elif not dropping and self._backlog:
            self._backlog = False
            self._on_status("backlog", "ok")

    def read(self) -> bytes:
        return self.ring.pop_all() if self.ring is not None else b""

    def stop(self) -> None:
        self._stop.set()
        # Abort any in-progress read FIRST so the worker isn't blocked inside
        # read() when we close the stream — closing out from under a blocked
        # read is a native crash on both backends.
        if self._stream is not None:
            self._stream.stop()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._teardown_stream()
        self._on_status("capture", "inactive")

    def _teardown_stream(self) -> None:
        if self._stream is not None:
            with contextlib.suppress(Exception):
                self._stream.close()
            self._stream = None
