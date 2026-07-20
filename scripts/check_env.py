r"""Environment & device checks.

Each check is INDEPENDENT: it catches its own errors, prints PASS/FAIL with a
short reason, and never lets one failure hide the others. Exit code is 0 only if
every check passes.

Checks:
  1. torch imports; Silero VAD loads and runs on CPU against the fixture.
  2. A loopback-capable input device exists (the meeting's audio).
  3. OPENAI_API_KEY is present in the environment / .env.
Plus an informational report on whether this platform can hide the overlay from
screen capture — that one is NOT a pass/fail, since UNAVAILABLE is the correct
and expected answer off Windows.

Run:  python scripts/check_env.py
"""

from __future__ import annotations

import contextlib
import os
import platform
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # import src.*

FIXTURE = Path(__file__).parent / "fixtures" / "test.wav"


class CheckResult:
    def __init__(self, name: str):
        self.name = name
        self.ok = False
        self.detail = ""

    def passed(self, detail: str) -> CheckResult:
        self.ok, self.detail = True, detail
        return self

    def failed(self, detail: str) -> CheckResult:
        self.ok, self.detail = False, detail
        return self


def check_torch_and_vad() -> CheckResult:
    r = CheckResult("torch + Silero VAD (CPU)")
    try:
        import numpy as np
        import soundfile as sf
        import torch
        from silero_vad import get_speech_timestamps, load_silero_vad

        # torch is intentionally the CPU build — VAD is its only consumer here,
        # and transcription/answers are cloud calls. cuda=False is EXPECTED.
        cuda_note = "cuda=False (expected: torch is CPU-only)"
        if torch.cuda.is_available():
            cuda_note = "cuda=True (unexpected but harmless)"

        # Load via soundfile rather than silero's read_audio(): torchaudio 2.11
        # file I/O needs torchcodec, and the real pipeline feeds VAD numpy frames
        # from the capture backend anyway — so exercise that path here.
        data, sr = sf.read(str(FIXTURE), dtype="float32")
        if data.ndim > 1:  # downmix to mono
            data = data.mean(axis=1)
        if sr != 16000:
            return r.failed(f"fixture sample rate {sr} != 16000")
        wav = torch.from_numpy(np.ascontiguousarray(data))

        model = load_silero_vad()  # loads onto CPU
        stamps = get_speech_timestamps(wav, model, sampling_rate=16000)
        if not stamps:
            return r.failed("VAD ran but found no speech in fixture")
        return r.passed(
            f"torch {torch.__version__}, {cuda_note}; "
            f"VAD found {len(stamps)} speech segment(s)"
        )
    except Exception as e:  # noqa: BLE001 - report, don't crash the whole run
        return r.failed(f"{type(e).__name__}: {e}")


def check_loopback_devices() -> CheckResult:
    r = CheckResult("system-audio loopback device")
    try:
        from src.audio.loopback import list_input_devices, setup_hint

        devices = list_input_devices()
        if not devices:
            return r.failed("no input devices found at all")
        loopbacks = [d for d in devices if d.get("loopback")]
        if not loopbacks:
            names = ", ".join(d["name"] for d in devices[:4])
            return r.failed(
                f"no loopback-capable device among {len(devices)} input(s): "
                f"{names}\n       {setup_hint()}"
            )
        names = ", ".join(d["name"] for d in loopbacks[:3])
        return r.passed(f"{len(loopbacks)} loopback-capable device(s): {names}")
    except Exception as e:  # noqa: BLE001
        return r.failed(f"{type(e).__name__}: {e}")


def check_api_key() -> CheckResult:
    r = CheckResult("OPENAI_API_KEY present")
    # dotenv is optional for this check.
    with contextlib.suppress(Exception):
        from dotenv import load_dotenv

        load_dotenv()
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return r.failed("not set. Copy .env.example to .env and paste your key.")
    # Never print the key; just enough to confirm it's a plausible value.
    return r.passed(f"set ({len(key)} chars, starts {key[:3]}…)")


def report_shield() -> None:
    from src.platform import os_name, shield_capability

    cap = shield_capability()
    label = "AVAILABLE" if cap.hides_from_screen_share else "UNAVAILABLE"
    print(f"[INFO] capture shield on {os_name()}: {label}")
    print(f"       {cap.detail}")
    if not cap.hides_from_screen_share:
        print("       The app will refuse to start without --i-know-its-visible.")


def main() -> int:
    print("=" * 68)
    print("environment & device checks")
    print(
        f"Python {platform.python_version()} ({platform.architecture()[0]}) "
        f"on {platform.system()} {platform.release()}"
    )
    print(f"Executable: {sys.executable}")
    if not FIXTURE.exists():
        print(f"\nFATAL: fixture not found at {FIXTURE}")
        return 2
    print("=" * 68)

    results = [
        check_torch_and_vad(),
        check_loopback_devices(),
        check_api_key(),
    ]

    print()
    for res in results:
        mark = "PASS" if res.ok else "FAIL"
        print(f"[{mark}] {res.name}")
        print(f"       {res.detail}")
    print()
    report_shield()
    print("=" * 68)

    n_pass = sum(1 for r in results if r.ok)
    print(f"{n_pass}/{len(results)} checks passed")
    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted")
        sys.exit(130)
    except Exception:  # noqa: BLE001 - last-resort so we always see a traceback
        traceback.print_exc()
        sys.exit(2)
