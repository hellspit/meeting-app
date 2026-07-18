"""WASAPI loopback capture into a drop-oldest ring buffer, with recovery.

A worker thread reads system-output audio (the meeting) via WASAPI loopback and
pushes it into a bounded ring buffer (drop-oldest on overflow → "backlog"). It
also RECOVERS from real-world audio disruptions instead of dying:

- If the device is unplugged / disconnected (read raises), it reopens on the new
  default output — retrying with backoff until the device returns.
- If you switch the default output device mid-meeting (both present, no error),
  a periodic check notices and switches capture to follow it.

Status/errors are reported via plain callbacks so this module stays Qt-agnostic.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Callable

import pyaudiowpatch as pyaudio

from src.config import Config

StatusCb = Callable[[str, str], None]
ErrorCb = Callable[[str], None]


def resolve_loopback_device(p: "pyaudio.PyAudio") -> dict:
    """Loopback device matching the current default output endpoint."""
    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    default_out = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
    if default_out.get("isLoopbackDevice"):
        return default_out
    for lb in p.get_loopback_device_info_generator():
        if default_out["name"] in lb["name"]:
            return lb
    raise RuntimeError(
        f"no loopback device found for default output {default_out['name']!r}"
    )


def current_default_output_name() -> str | None:
    """Read the CURRENT default output device name via a throwaway PyAudio.

    PortAudio caches devices at init, so an existing instance won't see a
    default-device switch — we need a fresh one. Fully guarded; never raises.
    """
    p = None
    try:
        p = pyaudio.PyAudio()
        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        return p.get_device_info_by_index(wasapi["defaultOutputDevice"])["name"]
    except Exception:  # noqa: BLE001
        return None
    finally:
        if p is not None:
            try:
                p.terminate()
            except Exception:  # noqa: BLE001
                pass


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
    """Captures WASAPI loopback audio on a worker thread into a RingBuffer."""

    SAMPLE_BYTES = 4  # paFloat32

    def __init__(self, cfg: Config, on_status: StatusCb | None = None,
                 on_error: ErrorCb | None = None,
                 ring_bytes_override: int | None = None):
        self._cfg = cfg
        self._on_status = on_status or (lambda *_: None)
        self._on_error = on_error or (lambda *_: None)
        self._ring_bytes_override = ring_bytes_override
        self._device_check_s = float(cfg.get("audio.device_check_seconds", 4.0))

        self._pa: pyaudio.PyAudio | None = None
        self._stream = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._backlog = False
        self._frames_per_buffer = 0
        self._default_out_name: str | None = None

        self.rate = 0
        self.channels = 0
        self.device_name = ""
        self.ring: RingBuffer | None = None

    # --- open / recover ------------------------------------------------------
    def _open_stream(self) -> bool:
        """(Re)create PyAudio, resolve the current loopback device, open a stream.

        Also (re)creates the ring buffer so we never mix samples from two device
        formats. Returns True on success; emits capture 'error' on failure.
        """
        try:
            self._teardown_stream()
            self._pa = pyaudio.PyAudio()
            dev = resolve_loopback_device(self._pa)
            self.rate = int(dev["defaultSampleRate"])
            self.channels = int(dev["maxInputChannels"])
            self.device_name = dev["name"]

            wasapi = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            self._default_out_name = self._pa.get_device_info_by_index(
                wasapi["defaultOutputDevice"])["name"]

            frame_ms = int(self._cfg.get("audio.frame_ms", 30))
            self._frames_per_buffer = max(1, int(self.rate * frame_ms / 1000))

            secs = float(self._cfg.get("audio.ring_buffer_seconds", 30))
            ring_bytes = self._ring_bytes_override or int(
                secs * self.rate * self.channels * self.SAMPLE_BYTES)
            self.ring = RingBuffer(ring_bytes)

            self._stream = self._pa.open(
                format=pyaudio.paFloat32,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self._frames_per_buffer,
                input_device_index=dev["index"],
            )
            return True
        except Exception as e:  # noqa: BLE001
            self._on_status("capture", "error")
            self._on_error(f"capture open failed: {type(e).__name__}: {e}")
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
            try:
                raw = self._stream.read(self._frames_per_buffer,
                                        exception_on_overflow=False)
            except OSError as e:
                # Device unplugged / disconnected mid-meeting → recover.
                self._on_status("capture", "error")
                self._on_error(f"audio device interrupted: {e}; recovering…")
                self._recover()
                frames_since_check = 0
                continue

            if self.ring is not None:
                self._update_backlog(self.ring.push(raw) > 0)

            if self._device_check_s > 0:
                frames_since_check += 1
                check_every = max(1, int(self.rate * self._device_check_s
                                         / max(1, self._frames_per_buffer)))
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
        # stream.read() when we close it — closing a stream out from under a
        # blocked read is a native crash. stop_stream() unblocks the read.
        if self._stream is not None:
            try:
                self._stream.stop_stream()
            except Exception:  # noqa: BLE001
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._teardown_stream()
        self._on_status("capture", "inactive")

    def _teardown_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
            self._stream = None
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:  # noqa: BLE001
                pass
            self._pa = None
