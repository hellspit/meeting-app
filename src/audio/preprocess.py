"""Turn raw loopback audio into 16 kHz mono float32 for VAD + STT.

Loopback is typically 48 kHz stereo float32 (interleaved). Silero VAD and the
transcription models want 16 kHz mono. We downmix by averaging channels and
resample with linear interpolation — cheap, dependency-free, and good enough for
speech (content is well under the 8 kHz Nyquist of 16 kHz).
"""

from __future__ import annotations

import numpy as np

TARGET_RATE = 16000


def resample(mono: np.ndarray, sr_in: int, sr_out: int = TARGET_RATE) -> np.ndarray:
    if len(mono) == 0 or sr_in == sr_out:
        return mono.astype(np.float32, copy=False)
    n_out = int(round(len(mono) * sr_out / sr_in))
    if n_out <= 0:
        return np.zeros(0, dtype=np.float32)
    x_old = np.arange(len(mono), dtype=np.float64)
    x_new = np.linspace(0, len(mono) - 1, n_out, dtype=np.float64)
    return np.interp(x_new, x_old, mono).astype(np.float32)


def bytes_to_mono16k(raw: bytes, channels: int, rate_in: int,
                     rate_out: int = TARGET_RATE) -> np.ndarray:
    """Convert interleaved float32 loopback bytes to 16 kHz mono float32."""
    if not raw:
        return np.zeros(0, dtype=np.float32)
    x = np.frombuffer(raw, dtype=np.float32)
    if channels > 1:
        usable = (len(x) // channels) * channels
        x = x[:usable].reshape(-1, channels).mean(axis=1)
    return resample(x, rate_in, rate_out)
