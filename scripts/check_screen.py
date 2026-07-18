r"""Screen-analysis check.

Captures the target monitor, sends it to GPT-4o vision, and prints a short
description. Proves the screenshot -> vision path end-to-end with your key.
(This DOES send a screenshot of your screen to OpenAI.)

Run:
    .venv\Scripts\python.exe scripts\check_screen.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # import src.*

from dotenv import load_dotenv  # noqa: E402
from src.config import load_config  # noqa: E402
from src.ai.screen import analyze_screen, capture_monitor_png  # noqa: E402


def main() -> int:
    load_dotenv()
    cfg = load_config()
    model = str(cfg.get("ai.model", "gpt-4o"))
    monitor = int(cfg.get("screen.target_monitor", cfg.get("overlay.target_monitor", 0)))

    print("=" * 64)
    print("Screen analysis check")
    print("=" * 64)

    try:
        png = capture_monitor_png(monitor)
        print(f"captured monitor {monitor}: {len(png)} bytes PNG")
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] screenshot: {type(e).__name__}: {e}")
        return 1

    try:
        from openai import OpenAI
        client = OpenAI()
        text = analyze_screen(
            client, model, png,
            question="In one or two sentences, what is currently on this screen?",
            max_tokens=120,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] vision request: {type(e).__name__}: {e}")
        return 1

    ok = bool(text.strip())
    print(f"[{'PASS' if ok else 'FAIL'}] vision answer:")
    print(f"       {text.strip()!r}")
    print("=" * 64)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
