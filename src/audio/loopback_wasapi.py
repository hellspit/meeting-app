"""Windows loopback backend: WASAPI via PyAudioWPatch.

Windows exposes a real loopback endpoint for each output device, so capturing
"what the meeting sounds like" needs no virtual cable and no user setup — we just
open the loopback device that matches the current default output.
"""

from __future__ import annotations

import pyaudiowpatch as pyaudio

SAMPLE_FORMAT_BYTES = 4  # paFloat32


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


def setup_hint() -> str:
    return ("No WASAPI loopback device was found. This is unusual on Windows — "
            "check that your default output device is working.")


def list_input_devices() -> list[dict]:
    """Capturable devices as {'index', 'name', 'channels', 'loopback'}."""
    p = None
    try:
        p = pyaudio.PyAudio()
        out = []
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if int(info.get("maxInputChannels", 0)) > 0:
                out.append({
                    "index": i,
                    "name": str(info["name"]),
                    "channels": int(info["maxInputChannels"]),
                    "loopback": bool(info.get("isLoopbackDevice", False)),
                })
        return out
    except Exception:  # noqa: BLE001
        return []
    finally:
        if p is not None:
            try:
                p.terminate()
            except Exception:  # noqa: BLE001
                pass


class WasapiLoopbackStream:
    """Opens the loopback endpoint for the current default output device."""

    def __init__(self, cfg, device_name_override: str | None = None):
        self._cfg = cfg
        self._override = device_name_override
        self._pa: pyaudio.PyAudio | None = None
        self._stream = None
        self.rate = 0
        self.channels = 0
        self.device_name = ""
        self.default_output_name: str | None = None

    def open(self, frame_ms: int) -> int:
        """Open the stream; returns frames_per_buffer. Raises on failure."""
        self.close()
        self._pa = pyaudio.PyAudio()

        dev = None
        if self._override:
            for i in range(self._pa.get_device_count()):
                info = self._pa.get_device_info_by_index(i)
                if self._override.lower() in str(info["name"]).lower() \
                        and int(info["maxInputChannels"]) > 0:
                    dev = info
                    break
            if dev is None:
                raise RuntimeError(
                    f"audio.input_device {self._override!r} not found among input devices")
        if dev is None:
            dev = resolve_loopback_device(self._pa)

        self.rate = int(dev["defaultSampleRate"])
        self.channels = int(dev["maxInputChannels"])
        self.device_name = str(dev["name"])

        wasapi = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        self.default_output_name = self._pa.get_device_info_by_index(
            wasapi["defaultOutputDevice"])["name"]

        frames_per_buffer = max(1, int(self.rate * frame_ms / 1000))
        self._stream = self._pa.open(
            format=pyaudio.paFloat32,
            channels=self.channels,
            rate=self.rate,
            input=True,
            frames_per_buffer=frames_per_buffer,
            input_device_index=dev["index"],
        )
        return frames_per_buffer

    def read(self, frames: int) -> bytes:
        """Read interleaved float32 bytes. Raises OSError if the device is lost."""
        return self._stream.read(frames, exception_on_overflow=False)

    def stop(self) -> None:
        """Unblock a pending read so the worker thread can exit safely."""
        if self._stream is not None:
            try:
                self._stream.stop_stream()
            except Exception:  # noqa: BLE001
                pass

    def close(self) -> None:
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
