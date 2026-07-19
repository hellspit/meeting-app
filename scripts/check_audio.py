r"""Live loopback level meter — proves we can hear the meeting.

Captures your system OUTPUT audio (what the meeting app plays through your
speakers/headphones) and shows a live level meter. Uses the exact same device
resolution as the real capture path (src/audio/capture.py), so it doubles as a
device-selection smoke test.

PASS = real signal detected (peak rises above the noise floor while audio plays).

Run (plays for ~15s, then reports):
    python scripts/check_audio.py
    python scripts/check_audio.py --duration 30
    python scripts/check_audio.py --list        # just enumerate input devices

Play ANY audio (music, a video, a test call) while it runs. In an interactive
terminal you get a live bar; when output is redirected it prints periodic lines.

macOS: this FAILS until you install a virtual audio driver (BlackHole) and route
output through a Multi-Output Device — macOS has no system loopback. The failure
message spells out the setup.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # import src.*

import numpy as np  # noqa: E402

from src.audio.loopback import (  # noqa: E402
    list_input_devices, open_loopback, setup_hint,
)
from src.config import load_config  # noqa: E402
from src.platform import os_name  # noqa: E402

# A frame ~= 30 ms of audio, matching the VAD frame size the pipeline uses.
FRAME_MS = 30
# Peak must exceed this (dBFS) at least once to count as "real audio captured".
SIGNAL_FLOOR_DBFS = -60.0


def dbfs(x: float) -> float:
    """Convert a 0..1 amplitude to dBFS (-inf floored to -120)."""
    if x <= 1e-6:
        return -120.0
    return 20.0 * math.log10(x)


def render_bar(level: float, width: int = 40) -> str:
    filled = int(max(0.0, min(1.0, level)) * width)
    return "#" * filled + "-" * (width - filled)


def print_devices() -> int:
    devices = list_input_devices()
    print("=" * 66)
    print(f"Input devices — {os_name()}")
    print("=" * 66)
    if not devices:
        print("  (none found)")
        return 1
    for d in devices:
        tag = "  <-- loopback-capable" if d.get("loopback") else ""
        print(f"  [{d['index']:>2}] {d['name']}  ({d['channels']} ch){tag}")
    print()
    print("Pin one by putting part of its name in config.yaml as")
    print("audio.input_device, e.g.  input_device: \"BlackHole\"")
    print("=" * 66)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=15.0,
                    help="seconds to run (default 15)")
    ap.add_argument("--list", action="store_true",
                    help="list capturable input devices and exit")
    args = ap.parse_args()

    if args.list:
        return print_devices()

    cfg = load_config()
    interactive = sys.stdout.isatty()
    stream = open_loopback(cfg)
    try:
        frames_per_buffer = stream.open(FRAME_MS)
        print("=" * 66)
        print(f"Loopback level meter — {os_name()}")
        print(f"device : {stream.device_name}")
        print(f"format : {stream.rate} Hz, {stream.channels} ch, float32, "
              f"{FRAME_MS}ms frames")
        print(f"running: {args.duration:.0f}s - play some audio now")
        print("=" * 66)
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] could not open loopback stream: {type(e).__name__}: {e}")
        print()
        print(setup_hint())
        stream.close()
        return 1

    peak_seen = 0.0
    last_print = 0.0
    start = time.monotonic()
    try:
        while time.monotonic() - start < args.duration:
            raw = stream.read(frames_per_buffer)
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
        stream.close()

    if interactive:
        print()
    print("=" * 66)
    ok = dbfs(peak_seen) > SIGNAL_FLOOR_DBFS
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] max peak {dbfs(peak_seen):.1f} dBFS "
          f"(floor {SIGNAL_FLOOR_DBFS:.0f} dBFS)")
    if not ok:
        print("       No signal captured. Was audio actually playing through")
        print("       the device shown above?")
        print()
        print(setup_hint())
    print("=" * 66)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
