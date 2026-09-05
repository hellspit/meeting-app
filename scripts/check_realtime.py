"""Time a generated speech fixture through transcription and streamed answers.

With --loopback, play the fixture through the speakers and capture it using the
actual audio backend. Uploads only the test recording; run in a quiet session.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import soundfile as sf
from dotenv import load_dotenv
from openai import OpenAI

from src.ai.conversation import Conversation
from src.audio.capture import AudioCapture
from src.audio.preprocess import bytes_to_mono16k
from src.audio.vad import StreamingVAD
from src.config import load_config
from src.stt.transcriber import Transcriber


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loopback", action="store_true")
    args = parser.parse_args()
    load_dotenv()
    cfg = load_config()
    fixture = Path(__file__).parent / "fixtures" / "test.wav"
    data, rate = sf.read(fixture, dtype="float32")
    if rate != 16000 or data.ndim != 1:
        raise ValueError("Generate a 16 kHz mono fixture first")
    vad = StreamingVAD(cfg)
    if args.loopback:
        import winsound

        capture = AudioCapture(cfg)
        capture.start()
        try:
            if capture.last_error:
                raise RuntimeError(capture.last_error)
            winsound.PlaySound(str(fixture), winsound.SND_FILENAME | winsound.SND_ASYNC)
            time.sleep(len(data) / rate + 1.0)
            data = bytes_to_mono16k(capture.read(), capture.channels, capture.rate)
            print(f"Captured {len(data) / 16000:.2f}s from {capture.device_name}")
        finally:
            winsound.PlaySound(None, 0)
            capture.stop()
    utterances = vad.feed(np.concatenate([data, np.zeros(16000, dtype=np.float32)]))
    if not utterances:
        print("FAIL: no speech detected")
        return 1
    client = OpenAI(timeout=25.0, max_retries=1)
    transcriber = Transcriber(client, str(cfg.get("stt.model")))
    started = time.perf_counter()
    transcript = " ".join(transcriber.transcribe(utt) for utt in utterances)
    transcribed = time.perf_counter()
    print(
        f"Speech segments: {len(utterances)}; transcription: {transcribed-started:.2f}s"
    )
    if "tuple" not in transcript.lower() or "list" not in transcript.lower():
        print("FAIL: test question was not transcribed correctly")
        return 1
    conv = Conversation(
        client, str(cfg.get("ai.model")), int(cfg.get("ai.max_answer_tokens"))
    )
    first = None
    answer = []
    for chunk in conv.ask_stream(transcript):
        if first is None:
            first = time.perf_counter()
        answer.append(chunk)
    finished = time.perf_counter()
    if first is None:
        print("FAIL: empty answer")
        return 1
    print(
        f"Answer first text: {first-transcribed:.2f}s; "
        f"full answer: {finished-transcribed:.2f}s"
    )
    waiting = (
        cfg.get("audio.silence_timeout_ms") + cfg.get("ai.auto_answer_delay_ms")
    ) / 1000
    print(f"Estimated end-of-speech to first text: {waiting+first-started:.2f}s")
    print("Test answer: " + "".join(answer))
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
