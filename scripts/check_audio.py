r"""M0d - live WASAPI loopback level meter.

Captures your system OUTPUT audio (what the meeting app plays through your
speakers/headphones) via WASAPI loopback and shows a live level meter. This is
the same default-output -> loopback device resolution the real capture path
(src/audio/capture.py) will use, so it doubles as a device-selection smoke test.

PASS = real signal detected (peak rises above the noise floor while audio plays).

Run (plays for ~15s, then reports):
    .venv\Scripts\python.exe scripts\check_audio.py
    .venv\Scripts\python.exe scripts\check_audio.py --duration 30

Play ANY audio (music, a video, a test call) while it runs. In an interactive
terminal you get a live bar; when output is redirected it prints periodic lines.
"""

from __future__ import annotations

import argparse
import math
import sys
import time

import numpy as np
import pyaudiowpatch as pyaudio

# A frame ~= 30 ms of audio, matching the VAD frame size the pipeline will use.
FRAME_MS = 30
# Peak must exceed this (dBFS) at least once to count as "real audio captured".
SIGNAL_FLOOR_DBFS = -60.0


def resolve_loopback_device(p: "pyaudio.PyAudio") -> dict:
    """Return the loopback device matching the current default output.

    WASAPI loopback captures a render (output) endpoint as if it were an input.
    We start from the default output device and find its loopback twin.
    """
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


def dbfs(x: float) -> float:
    """Convert a 0..1 amplitude to dBFS (-inf floored to -120)."""
    if x <= 1e-6:
        return -120.0
    return 20.0 * math.log10(x)


def render_bar(level: float, width: int = 40) -> str:
    filled = int(max(0.0, min(1.0, level)) * width)
    return "#" * filled + "-" * (width - filled)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=15.0,
                    help="seconds to run (default 15)")
    args = ap.parse_args()

    interactive = sys.stdout.isatty()
    p = pyaudio.PyAudio()
    try:
        dev = resolve_loopback_device(p)
        rate = int(dev["defaultSampleRate"])
        channels = int(dev["maxInputChannels"])
        frames_per_buffer = max(1, int(rate * FRAME_MS / 1000))

        print("=" * 60)
        print("M0d - WASAPI loopback level meter")
        print(f"device : {dev['name']}")
        print(f"format : {rate} Hz, {channels} ch, float32, {FRAME_MS}ms frames")
        print(f"running: {args.duration:.0f}s - play some audio now")
        print("=" * 60)

        stream = p.open(
            format=pyaudio.paFloat32,
            channels=channels,
            rate=rate,
            input=True,
            frames_per_buffer=frames_per_buffer,
            input_device_index=dev["index"],
        )
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] could not open loopback stream: {type(e).__name__}: {e}")
        p.terminate()
        return 1

    peak_seen = 0.0
    last_print = 0.0
    start = time.monotonic()
    try:
        while time.monotonic() - start < args.duration:
            raw = stream.read(frames_per_buffer, exception_on_overflow=False)
            samples = np.frombuffer(raw, dtype=np.float32)
            if samples.size == 0:
                continue
            rms = float(np.sqrt(np.mean(samples * samples)))
            peak = float(np.max(np.abs(samples)))
            peak_seen = max(peak_seen, peak)

            if interactive:
                sys.stdout.write(
                    f"\r[{render_bar(rms * 3)}] "
                    f"rms {dbfs(rms):6.1f} dBFS  peak {dbfs(peak):6.1f} dBFS  "
                )
                sys.stdout.flush()
            else:
                now = time.monotonic()
                if now - last_print >= 0.5:  # periodic lines when redirected
                    last_print = now
                    print(f"t={now - start:4.1f}s  rms {dbfs(rms):6.1f} dBFS  "
                          f"peak {dbfs(peak):6.1f} dBFS")
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

    if interactive:
        print()
    print("=" * 60)
    ok = dbfs(peak_seen) > SIGNAL_FLOOR_DBFS
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] max peak {dbfs(peak_seen):.1f} dBFS "
          f"(floor {SIGNAL_FLOOR_DBFS:.0f} dBFS)")
    if not ok:
        print("       No signal captured. Was audio actually playing through "
              "the default output device?")
    print("=" * 60)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
