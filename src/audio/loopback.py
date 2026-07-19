"""Backend selection for system-audio loopback capture.

Every backend exposes the same small surface so `AudioCapture` stays
platform-agnostic and keeps all the shared logic (ring buffer, recovery, backlog
tracking) in one place:

    stream.open(frame_ms) -> frames_per_buffer
    stream.read(frames)   -> interleaved float32 bytes  (raises OSError if lost)
    stream.stop()         -> unblock a pending read
    stream.close()        -> release everything
    stream.rate / .channels / .device_name / .default_output_name
"""

from __future__ import annotations

from src.platform import IS_WINDOWS


def _backend():
    if IS_WINDOWS:
        from src.audio import loopback_wasapi as mod
        return mod, mod.WasapiLoopbackStream
    from src.audio import loopback_sounddevice as mod
    return mod, mod.SounddeviceLoopbackStream


def open_loopback(cfg):
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
