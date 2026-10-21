r"""M3 - audio capture + ring buffer checks.

Two independent checks:
  A. Real capture: run the loopback capture briefly and confirm audio bytes flow
     into the ring buffer (loopback delivers silence frames even with nothing
     playing, so this passes without you playing anything).
  B. Drop-oldest / backlog: use a tiny ring buffer and DON'T drain it, forcing
     overflow, and confirm the ring drops oldest bytes and a "backlog" status
     fires (the guarantee that a slow consumer never wedges capture).

Run:
    .venv\Scripts\python.exe scripts\check_capture.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # import src.*

from src.audio.capture import AudioCapture
from src.config import load_config


def _run_for(seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        time.sleep(0.05)


def check_real_capture(cfg) -> tuple[bool, str]:
    events: list[tuple[str, str]] = []
    errors: list[str] = []
    cap = AudioCapture(
        cfg, on_status=lambda f, s: events.append((f, s)), on_error=errors.append
    )
    cap.start()
    if errors:
        return False, errors[0]
    _run_for(3.0)
    data = cap.read()
    cap.stop()

    bytes_per_sec = cap.rate * cap.channels * AudioCapture.SAMPLE_BYTES
    secs = len(data) / bytes_per_sec if bytes_per_sec else 0
    got_active = ("capture", "active") in events
    ok = len(data) > 0 and got_active
    detail = (
        f"device={cap.device_name!r} {cap.rate}Hz x{cap.channels}; "
        f"captured {len(data)} bytes (~{secs:.1f}s); active_event={got_active}"
    )
    return ok, detail


def check_drop_oldest(cfg) -> tuple[bool, str]:
    events: list[tuple[str, str]] = []
    errors: list[str] = []
    # Tiny buffer (~8 KB) and we never drain -> guaranteed overflow.
    cap = AudioCapture(
        cfg,
        on_status=lambda f, s: events.append((f, s)),
        on_error=errors.append,
        ring_bytes_override=8000,
    )
    cap.start()
    if errors:
        return False, errors[0]
    _run_for(2.0)
    dropped = cap.ring.dropped_bytes if cap.ring is not None else 0
    cap.stop()

    backlog_fired = ("backlog", "warning") in events
    ok = dropped > 0 and backlog_fired
    detail = f"dropped {dropped} bytes (oldest); backlog_warning_fired={backlog_fired}"
    return ok, detail


def main() -> int:
    cfg = load_config()
    print("=" * 64)
    print("M3 - audio capture + ring buffer")
    print("=" * 64)

    results = []
    for name, fn in (
        ("real capture", check_real_capture),
        ("drop-oldest / backlog", check_drop_oldest),
    ):
        try:
            ok, detail = fn(cfg)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"{type(e).__name__}: {e}"
        results.append(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        print(f"       {detail}")

    print("=" * 64)
    n = sum(results)
    print(f"{n}/{len(results)} checks passed")
    return 0 if n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
