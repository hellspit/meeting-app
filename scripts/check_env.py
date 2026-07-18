r"""M0a environment & device checks for the meeting-answer overlay.

Each check is INDEPENDENT: it catches its own errors, prints PASS/FAIL with a
short reason, and never lets one failure hide the others. Exit code is 0 only
if every check passes.

Checks (per plan.md, milestone M0a):
  1. torch imports; Silero VAD loads and runs on CPU.
  2. faster-whisper loads with device="cuda" (the real GPU proof, not torch.cuda).
  3. faster-whisper transcribes scripts/fixtures/test.wav (deterministic STT).
  4. WASAPI loopback output devices enumerate.

Run:  .venv\Scripts\python.exe scripts\check_env.py
"""

from __future__ import annotations

import os
import platform
import sys
import traceback
from pathlib import Path

# --- Make CUDA/cuDNN DLLs from any pip `nvidia-*` packages loadable ----------
# ctranslate2 (faster-whisper's backend) needs cuBLAS + cuDNN 9 at runtime. When
# those ship as pip wheels their DLLs live under site-packages/nvidia/*/bin,
# which is NOT on the default Windows DLL search path. Register them explicitly
# BEFORE importing faster-whisper. This is the "#1 install failure point" the
# plan calls out; doing it here keeps it out of PATH hacking.
def _register_nvidia_dll_dirs() -> list[str]:
    registered: list[str] = []
    for entry in sys.path:
        nvidia_root = Path(entry) / "nvidia"
        if not nvidia_root.is_dir():
            continue
        for bindir in nvidia_root.glob("*/bin"):
            if bindir.is_dir():
                bindir_str = str(bindir)
                # os.add_dll_directory covers loads that use the user-dirs
                # search flag. ctranslate2 loads cuBLAS/cuDNN lazily with a
                # plain LoadLibrary("cublas64_12.dll"), which searches PATH but
                # NOT add_dll_directory dirs — so we must do BOTH.
                try:
                    os.add_dll_directory(bindir_str)
                except OSError:
                    pass
                if bindir_str not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = bindir_str + os.pathsep + os.environ.get("PATH", "")
                registered.append(bindir_str)
    return registered


FIXTURE = Path(__file__).parent / "fixtures" / "test.wav"

# Words we expect to see in the fixture transcript ("The quick brown fox jumps
# over the lazy dog."). We only require a couple to survive STT, not the whole
# sentence, so the check is robust but still meaningful.
EXPECTED_WORDS = ("fox", "dog", "quick", "lazy", "brown")


class CheckResult:
    def __init__(self, name: str):
        self.name = name
        self.ok = False
        self.detail = ""

    def passed(self, detail: str) -> "CheckResult":
        self.ok, self.detail = True, detail
        return self

    def failed(self, detail: str) -> "CheckResult":
        self.ok, self.detail = False, detail
        return self


def check_torch_and_vad() -> CheckResult:
    r = CheckResult("torch + Silero VAD (CPU)")
    try:
        import numpy as np
        import soundfile as sf
        import torch
        from silero_vad import load_silero_vad, get_speech_timestamps

        # torch is intentionally the CPU build (VAD only). cuda.is_available()
        # being False here is EXPECTED and not a failure — see plan reality #4.
        cuda_note = "cuda=False (expected: torch is CPU-only)"
        if torch.cuda.is_available():
            cuda_note = "cuda=True (unexpected but harmless)"

        # Load audio via soundfile rather than silero's read_audio(): torchaudio
        # 2.11 file I/O now needs torchcodec, and the real pipeline feeds VAD
        # numpy frames from PyAudio anyway — so exercise that path here.
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


def check_faster_whisper_cuda(state: dict) -> CheckResult:
    """Loads faster-whisper on CUDA. Caches the model in `state` for reuse by
    the transcription check so we don't load the model twice."""
    r = CheckResult("faster-whisper load on CUDA (GPU proof)")
    try:
        import ctranslate2
        from faster_whisper import WhisperModel

        n = ctranslate2.get_cuda_device_count()
        if n < 1:
            return r.failed("ctranslate2 sees 0 CUDA devices")

        # "base" is small/fast but still exercises the real CUDA path. float16
        # suits the RTX 4050 (6 GB). Model downloads from HF on first run.
        model = WhisperModel("base", device="cuda", compute_type="float16")
        state["whisper"] = model
        return r.passed(
            f"ctranslate2 {ctranslate2.__version__}, {n} CUDA device(s); "
            f"WhisperModel('base', cuda, float16) loaded"
        )
    except Exception as e:  # noqa: BLE001
        return r.failed(f"{type(e).__name__}: {e}")


def check_transcribe_fixture(state: dict) -> CheckResult:
    r = CheckResult("faster-whisper transcribe fixture (STT)")
    model = state.get("whisper")
    if model is None:
        return r.failed("skipped: CUDA model failed to load")
    try:
        segments, info = model.transcribe(str(FIXTURE), language="en", beam_size=1)
        text = " ".join(s.text for s in segments).strip()
        if not text:
            return r.failed("transcription returned empty text")
        hits = [w for w in EXPECTED_WORDS if w in text.lower()]
        if not hits:
            return r.failed(f"no expected words in transcript: {text!r}")
        return r.passed(f"matched {hits}; transcript={text!r}")
    except Exception as e:  # noqa: BLE001
        return r.failed(f"{type(e).__name__}: {e}")


def check_wasapi_loopback() -> CheckResult:
    r = CheckResult("WASAPI loopback enumeration")
    try:
        import pyaudiowpatch as pyaudio

        p = pyaudio.PyAudio()
        try:
            wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_out = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
            loopbacks = list(p.get_loopback_device_info_generator())
        finally:
            p.terminate()

        if not loopbacks:
            return r.failed("no WASAPI loopback devices found")
        names = ", ".join(d["name"] for d in loopbacks[:3])
        return r.passed(
            f"default output={default_out['name']!r}; "
            f"{len(loopbacks)} loopback device(s): {names}"
        )
    except Exception as e:  # noqa: BLE001
        return r.failed(f"{type(e).__name__}: {e}")


def main() -> int:
    print("=" * 68)
    print("M0a environment & device checks")
    print(f"Python {platform.python_version()} ({platform.architecture()[0]}) "
          f"on {platform.system()} {platform.release()}")
    print(f"Executable: {sys.executable}")
    if not FIXTURE.exists():
        print(f"\nFATAL: fixture not found at {FIXTURE}")
        return 2
    dll_dirs = _register_nvidia_dll_dirs()
    if dll_dirs:
        print(f"Registered {len(dll_dirs)} nvidia DLL dir(s) for CUDA runtime")
    print("=" * 68)

    state: dict = {}
    results = [
        check_torch_and_vad(),
        check_faster_whisper_cuda(state),
        check_transcribe_fixture(state),
        check_wasapi_loopback(),
    ]

    print()
    for res in results:
        mark = "PASS" if res.ok else "FAIL"
        print(f"[{mark}] {res.name}")
        print(f"       {res.detail}")
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
