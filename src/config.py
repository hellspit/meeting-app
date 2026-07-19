"""Configuration loading with code defaults.

config.yaml is optional and partial: anything it omits falls back to DEFAULTS
here, so the app always has a complete, valid config. Access is via a plain
nested dict wrapped in `Config`, with dotted-path lookup for convenience.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict[str, Any] = {
    "overlay": {
        "width": 460,
        "height": 520,
        "margin": 24,
        "anchor": "top-right",
        "target_monitor": 0,
        "opacity": 0.92,
        "font_point_size": 12,
        "click_through": False,
    },
    "stt": {
        "provider": "openai",
        "model": "gpt-4o-mini-transcribe",
        "language": "en",
    },
    "audio": {
        "frame_ms": 30,
        "target_sample_rate": 16000,
        "silence_timeout_ms": 700,
        "min_speech_ms": 250,
        "max_utterance_s": 18,
        "ring_buffer_seconds": 30,
        # Proactive default-device-switch polling (0 = off). Off by default:
        # unplug/disconnect is already covered by read-error recovery, and the
        # poll spins up a throwaway PyAudio which can be flaky. Opt in if you
        # frequently switch the default output while both devices stay present.
        "device_check_seconds": 0,
        # Pin capture to a specific input device by name substring. Empty = auto
        # (Windows: the loopback for your default output; macOS: a virtual driver
        # such as BlackHole; Linux: a PulseAudio/PipeWire '.monitor' source).
        "input_device": "",
    },
    "ai": {
        "provider": "openai",
        "model": "gpt-5.2",  # best available; supports vision + code
        "max_answer_tokens": 1500,  # full answers (+ gpt-5 reasoning headroom)
        "max_context_tokens": 2500,
        "auto_answer": True,  # answer automatically when they stop talking
        "auto_answer_delay_ms": 900,  # silence to wait for before auto-answering
    },
    "screen": {
        "enabled": True,
        "target_monitor": 0,
        "question": "Look at my screen and help me respond. What should I say?",
    },
    "privacy": {
        "debug_content_logging": False,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge `override` into a copy of `base`."""
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, data: dict[str, Any]):
        self._data = data

    def get(self, dotted: str, default: Any = None) -> Any:
        """Look up a value by dotted path, e.g. cfg.get('overlay.opacity')."""
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, name: str) -> dict[str, Any]:
        return dict(self._data.get(name, {}))

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)


def load_config(path: Path | None = None) -> Config:
    """Load config.yaml (if present) merged over DEFAULTS."""
    if path is None:
        path = PROJECT_ROOT / "config.yaml"
    data = DEFAULTS
    if path.exists():
        with open(path, encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{path} must contain a YAML mapping at top level")
        data = _deep_merge(DEFAULTS, loaded)
    return Config(data)
