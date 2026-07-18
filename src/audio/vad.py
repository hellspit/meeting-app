"""Streaming voice-activity detection with Silero (CPU).

Feeds 16 kHz mono audio through Silero VAD frame by frame and emits COMPLETE
spoken utterances (numpy float32) once a speech run ends in enough silence. This
means we only send actual speech to the transcription API — not silence — which
saves cost and latency and avoids Whisper's silence hallucinations.

State machine per 512-sample frame (~32 ms at 16 kHz, the size Silero requires):
- Not in speech: keep a small pre-roll ring; when a frame scores as speech,
  start an utterance (including the pre-roll so we don't clip the first word).
- In speech: append frames; reset the silence timer on speech; when trailing
  silence exceeds `silence_timeout`, flush the utterance. Also hard-flush when
  it exceeds `max_utterance` so a monologue still gets transcribed in chunks.
"""

from __future__ import annotations

from collections import deque

import numpy as np
import torch
from silero_vad import load_silero_vad

from src.config import Config

SR = 16000
WINDOW = 512  # samples Silero requires at 16 kHz (~32 ms)


class StreamingVAD:
    def __init__(self, cfg: Config, threshold: float = 0.5):
        self.threshold = threshold
        self.min_speech = int(cfg.get("audio.min_speech_ms", 250)) * SR // 1000
        self.silence_timeout = int(cfg.get("audio.silence_timeout_ms", 700)) * SR // 1000
        self.max_utt = int(cfg.get("audio.max_utterance_s", 18)) * SR
        pad_ms = 96
        self._pad_frames = max(1, pad_ms * SR // 1000 // WINDOW)

        self.model = load_silero_vad()
        self.model.reset_states()

        self._tail = np.zeros(0, dtype=np.float32)  # leftover < one window
        self._pre: deque[np.ndarray] = deque(maxlen=self._pad_frames)
        self._cur: list[np.ndarray] = []
        self._in_speech = False
        self._silence = 0
        self._cur_len = 0

    def feed(self, mono: np.ndarray) -> list[np.ndarray]:
        """Feed 16 kHz mono audio; return any utterances that completed."""
        out: list[np.ndarray] = []
        if len(mono) == 0:
            return out
        data = np.concatenate([self._tail, mono]) if len(self._tail) else mono
        n = (len(data) // WINDOW) * WINDOW
        self._tail = data[n:].copy()
        with torch.no_grad():
            for i in range(0, n, WINDOW):
                frame = data[i:i + WINDOW]
                prob = float(self.model(
                    torch.from_numpy(np.ascontiguousarray(frame)), SR).item())
                self._step(frame, prob >= self.threshold, out)
        return out

    def _step(self, frame: np.ndarray, speech: bool, out: list) -> None:
        if not self._in_speech:
            self._pre.append(frame)
            if speech:
                self._in_speech = True
                self._silence = 0
                self._cur = list(self._pre)  # include pre-roll
                self._cur_len = sum(len(f) for f in self._cur)
        else:
            self._cur.append(frame)
            self._cur_len += len(frame)
            if speech:
                self._silence = 0
            else:
                self._silence += WINDOW
                if self._silence >= self.silence_timeout:
                    utt = self._flush()
                    if utt is not None:
                        out.append(utt)
                    return
            if self._cur_len >= self.max_utt:
                utt = self._flush()
                if utt is not None:
                    out.append(utt)

    def _flush(self) -> np.ndarray | None:
        frames = self._cur
        self._in_speech = False
        self._silence = 0
        self._cur = []
        self._cur_len = 0
        self._pre.clear()
        self.model.reset_states()  # reset LSTM state between utterances
        if not frames:
            return None
        utt = np.concatenate(frames)
        if len(utt) < self.min_speech:
            return None
        return utt

    def flush_final(self) -> np.ndarray | None:
        """Flush any in-progress utterance (e.g., at shutdown or end of file)."""
        if self._in_speech and self._cur:
            return self._flush()
        return None
