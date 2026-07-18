"""Transcribe an utterance with the OpenAI transcription API.

Takes 16 kHz mono float32, encodes an in-memory 16-bit WAV, and sends it to
audio.transcriptions.create (default gpt-4o-mini-transcribe). Filters out empty
results and a few common silence/hallucination artifacts.
"""

from __future__ import annotations

import io

import numpy as np
import soundfile as sf

SR = 16000

# Whisper-family models sometimes emit these on near-silence; drop them.
_HALLUCINATIONS = {
    "you", "thank you.", "thanks for watching!", "thank you for watching.",
    ".", ". .", "bye.", "you.",
}


def utterance_to_wav_bytes(mono16k: np.ndarray) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, mono16k, SR, format="WAV", subtype="PCM_16")
    return buf.getvalue()


class Transcriber:
    def __init__(self, client, model: str, language: str = "en"):
        self.client = client
        self.model = model
        self.language = language

    def transcribe(self, mono16k: np.ndarray) -> str:
        wav = utterance_to_wav_bytes(mono16k)
        tr = self.client.audio.transcriptions.create(
            model=self.model,
            file=("utterance.wav", wav),
            language=self.language,
        )
        text = (getattr(tr, "text", "") or "").strip()
        if text.lower() in _HALLUCINATIONS:
            return ""
        return text
