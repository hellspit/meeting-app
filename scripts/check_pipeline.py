r"""M4 - VAD + transcription check (deterministic, offline).

Feeds the speech fixture through the real StreamingVAD and Transcriber (OpenAI),
confirming the utterance is detected and transcribed. No live capture needed.

Run:
    .venv\Scripts\python.exe scripts\check_pipeline.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # import src.*

import soundfile as sf
from dotenv import load_dotenv

from src.audio.vad import StreamingVAD
from src.config import load_config
from src.stt.transcriber import Transcriber

FIXTURE = Path(__file__).parent / "fixtures" / "test.wav"
EXPECTED = ("fox", "dog", "quick", "lazy", "brown")


def main() -> int:
    load_dotenv()
    cfg = load_config()

    data, sr = sf.read(str(FIXTURE), dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    print("=" * 64)
    print("M4 - VAD + transcription")
    print(f"fixture: {len(data)} samples @ {sr} Hz")
    print("=" * 64)

    if sr != 16000:
        from src.audio.preprocess import resample

        data = resample(data, sr, 16000)

    vad = StreamingVAD(cfg)
    utts = []
    # Feed in ~100 ms chunks to exercise the streaming path.
    chunk = 1600
    for i in range(0, len(data), chunk):
        utts.extend(vad.feed(data[i : i + chunk]))
    final = vad.flush_final()
    if final is not None:
        utts.append(final)

    print(f"[{'PASS' if utts else 'FAIL'}] VAD detected {len(utts)} utterance(s)")
    if not utts:
        return 1

    from openai import OpenAI

    tr = Transcriber(
        OpenAI(),
        model=str(cfg.get("stt.model")),
        language=str(cfg.get("stt.language", "en")),
    )
    texts = []
    for i, utt in enumerate(utts):
        secs = len(utt) / 16000
        text = tr.transcribe(utt)
        texts.append(text)
        print(f"       utt {i}: {secs:.1f}s -> {text!r}")

    joined = " ".join(texts).lower()
    hits = [w for w in EXPECTED if w in joined]
    ok = bool(hits)
    print(f"[{'PASS' if ok else 'FAIL'}] transcription matched {hits}")
    print("=" * 64)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
