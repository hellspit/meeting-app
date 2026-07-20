"""macOS / Linux loopback backend, via sounddevice (PortAudio).

Neither platform gives us Windows' free lunch:

- macOS has no system-audio loopback at all. You must install a virtual audio
  driver (BlackHole is free) and route output through it — normally with a
  Multi-Output Device so you still HEAR the meeting while we capture it.
- Linux is easy by comparison: PulseAudio/PipeWire already expose a `.monitor`
  source for every output sink, which is exactly what we want.

Device choice order: an explicit `audio.input_device` from config, then a known
virtual/monitor device by name, then nothing (we raise with setup instructions
rather than silently capturing the microphone — recording your own mic instead of
the meeting would be both useless and a privacy surprise).
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import numpy as np

from src.platform import IS_MACOS

if TYPE_CHECKING:
    import sounddevice as sd

# Substrings that identify a loopback-capable input, most preferred first.
_MACOS_CANDIDATES = (
    "blackhole",
    "loopback audio",
    "soundflower",
    "existential audio",
    "multi-output",
    "aggregate",
)
_LINUX_CANDIDATES = ("monitor",)

MAX_CHANNELS = 2  # we downmix to mono anyway; no need to haul 16 aggregate channels


def _candidates() -> tuple[str, ...]:
    return _MACOS_CANDIDATES if IS_MACOS else _LINUX_CANDIDATES


def setup_hint() -> str:
    if IS_MACOS:
        return (
            "No loopback input device found.\n"
            "macOS cannot capture system audio without a virtual audio driver.\n"
            "  1. Install BlackHole (free):  brew install --cask blackhole-2ch\n"
            "  2. Open 'Audio MIDI Setup' and create a Multi-Output Device that\n"
            "     includes BOTH your speakers/headphones AND BlackHole 2ch.\n"
            "     (Without this you capture audio but hear nothing.)\n"
            "  3. Set that Multi-Output Device as your system output.\n"
            "  4. Re-run. To pin a specific device, set audio.input_device in\n"
            "     config.yaml to part of its name, e.g. 'BlackHole'."
        )
    return (
        "No monitor source found.\n"
        "On PulseAudio/PipeWire each output sink has a matching '.monitor' source.\n"
        "  - Check with:  pactl list short sources | grep monitor\n"
        "  - Then set audio.input_device in config.yaml to part of that name,\n"
        "    e.g. 'monitor'."
    )


def list_input_devices() -> list[dict]:
    """Capturable devices as {'index', 'name', 'channels', 'loopback', ...}."""
    try:
        import sounddevice as sd
    except Exception:  # noqa: BLE001
        return []

    out = []
    for idx, info in enumerate(sd.query_devices()):
        if int(info.get("max_input_channels", 0)) > 0:
            name = str(info["name"])
            out.append(
                {
                    **info,
                    "index": idx,
                    "name": name,
                    "channels": int(info["max_input_channels"]),
                    "loopback": any(c in name.lower() for c in _candidates()),
                }
            )
    return out


def _pick_device(override: str | None) -> dict:
    devices = list_input_devices()
    if not devices:
        raise RuntimeError("no audio input devices are available at all")

    if override:
        for d in devices:
            if override.lower() in str(d["name"]).lower():
                return d
        names = ", ".join(repr(str(d["name"])) for d in devices)
        raise RuntimeError(
            f"audio.input_device {override!r} matched no input device. "
            f"Available: {names}"
        )

    for needle in _candidates():
        for d in devices:
            if needle in str(d["name"]).lower():
                return d
    raise RuntimeError(setup_hint())


def current_default_output_name() -> str | None:
    """Best-effort current default output name. Never raises.

    PortAudio caches its device list at init, so this can lag a mid-session
    default-device switch. `audio.device_check_seconds` is 0 (off) by default,
    and unplug/disconnect is covered by read-error recovery instead.
    """
    try:
        import sounddevice as sd

        info = sd.query_devices(kind="output")
        return str(info["name"]) if info else None
    except Exception:  # noqa: BLE001
        return None


class SounddeviceLoopbackStream:
    """Captures from a virtual-loopback / monitor input device."""

    def __init__(self, cfg, device_name_override: str | None = None):
        self._cfg = cfg
        self._override = device_name_override
        self._stream: sd.InputStream | None = None
        self.rate = 0
        self.channels = 0
        self.device_name = ""
        self.default_output_name: str | None = None

    def open(self, frame_ms: int) -> int:
        import sounddevice as sd

        self.close()
        dev = _pick_device(self._override)

        self.rate = int(dev.get("default_samplerate") or 48000)
        self.channels = max(1, min(MAX_CHANNELS, int(dev["max_input_channels"])))
        self.device_name = str(dev["name"])
        self.default_output_name = current_default_output_name()

        frames_per_buffer = max(1, int(self.rate * frame_ms / 1000))
        self._stream = sd.InputStream(
            device=int(dev["index"]),
            channels=self.channels,
            samplerate=self.rate,
            dtype="float32",
            blocksize=frames_per_buffer,
        )
        self._stream.start()
        return frames_per_buffer

    def read(self, frames: int) -> bytes:
        """Read interleaved float32 bytes. Raises OSError if the device is lost."""
        import sounddevice as sd

        if self._stream is None:
            raise OSError("stream is not open")
        try:
            data, _overflowed = self._stream.read(frames)
        except sd.PortAudioError as e:
            # Normalize to OSError so AudioCapture's recovery path is uniform.
            raise OSError(f"PortAudio read failed: {e}") from e
        # sounddevice hands back (frames, channels) float32; tobytes() is the
        # interleaved layout the preprocessor expects.
        return np.ascontiguousarray(data, dtype=np.float32).tobytes()

    def stop(self) -> None:
        """Unblock a pending read so the worker thread can exit safely."""
        if self._stream is not None:
            with contextlib.suppress(Exception):
                self._stream.abort()

    def close(self) -> None:
        if self._stream is not None:
            with contextlib.suppress(Exception):
                self._stream.abort()
                self._stream.close()
            self._stream = None
