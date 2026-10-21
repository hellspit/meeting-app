"""Transcribe an utterance with an audio-capable chat model via OpenRouter.

Takes 16 kHz mono float32, encodes an in-memory 16-bit WAV, and sends it as an
input_audio part to chat.completions (default google/gemini-3.5-flash-lite).
OpenRouter has no audio.transcriptions endpoint, so a chat model does the job.
Filters out empty results and a few common silence/hallucination artifacts.
"""

from __future__ import annotations

import base64
import io

import numpy as np
import soundfile as sf

SR = 16000

# Whisper-family models sometimes emit these on near-silence; drop them.
_HALLUCINATIONS = {
    "you",
    "thank you.",
    "thanks for watching!",
    "thank you for watching.",
    ".",
    ". .",
    "bye.",
    "you.",
}

_PROMPT = (
    "Transcribe this audio verbatim in {lang}. Output only the spoken words, "
    "with no commentary, labels or quotes. If there is no intelligible speech, "
    "output nothing."
)


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
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _PROMPT.format(lang=self.language)},
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": base64.b64encode(wav).decode("ascii"),
                                "format": "wav",
                            },
                        },
                    ],
                }
            ],
            temperature=0,
        )
        text = (resp.choices[0].message.content or "").strip() if resp.choices else ""
        if text.lower() in _HALLUCINATIONS:
            return ""
        return text
