"""Backend selection for system-audio loopback capture.

Every backend exposes the same small surface (`LoopbackStream`) so
`AudioCapture` stays platform-agnostic and keeps all the shared logic (ring
buffer, recovery, backlog tracking) in one place.
"""

from __future__ import annotations

from typing import Protocol

from src.config import Config
from src.platform import IS_WINDOWS


class LoopbackStream(Protocol):
    """Structural interface both backend streams implement.

    open(frame_ms) -> frames_per_buffer
    read(frames)   -> interleaved float32 bytes  (raises OSError if lost)
    stop()         -> unblock a pending read
    close()        -> release everything
    """

    rate: int
    channels: int
    device_name: str
    default_output_name: str | None

    def open(self, frame_ms: int) -> int: ...

    def read(self, frames: int) -> bytes: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...


def _backend():
    if IS_WINDOWS:
        from src.audio import loopback_wasapi

        return loopback_wasapi, loopback_wasapi.WasapiLoopbackStream
    from src.audio import loopback_sounddevice

    return loopback_sounddevice, loopback_sounddevice.SounddeviceLoopbackStream


def open_loopback(cfg: Config) -> LoopbackStream:
    """Construct (not open) the right loopback stream for this platform."""
    _mod, cls = _backend()
    override = cfg.get("audio.input_device") or None
    return cls(cfg, device_name_override=override)


def current_default_output_name() -> str | None:
    mod, _cls = _backend()
    return mod.current_default_output_name()


def setup_hint() -> str:
    mod, _cls = _backend()
    return mod.setup_hint()


def list_input_devices() -> list[dict]:
    """Capturable devices as {'index', 'name', 'channels', 'loopback'}."""
    mod, _cls = _backend()
    return mod.list_input_devices()
