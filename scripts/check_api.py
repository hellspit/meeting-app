r"""M0c - OpenAI auth + model check.

Confirms your OPENAI_API_KEY works for BOTH things the app needs:
  1. Chat answers  - a 1-token chat completion with the configured answer model.
  2. Transcription - transcribes scripts/fixtures/test.wav with the STT model.

Never prints your key. Reads models from config.yaml.

Run:
    .venv\Scripts\python.exe scripts\check_api.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # import src.*

from dotenv import load_dotenv  # noqa: E402
from src.config import load_config  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "test.wav"


def check_chat(client, model: str) -> tuple[bool, str]:
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with the word OK."}],
            max_tokens=1,
        )
        _ = resp.choices[0].message.content
        return True, f"model {model!r} responded"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def check_transcription(client, model: str) -> tuple[bool, str]:
    try:
        with open(FIXTURE, "rb") as f:
            tr = client.audio.transcriptions.create(model=model, file=f, language="en")
        text = (tr.text or "").strip()
        if not text:
            return False, f"model {model!r} returned empty transcript"
        return True, f"model {model!r} -> {text!r}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    load_dotenv()  # pulls OPENAI_API_KEY from .env into the environment
    cfg = load_config()

    try:
        from openai import OpenAI
        client = OpenAI()  # reads OPENAI_API_KEY from env
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] could not create OpenAI client: {type(e).__name__}: {e}")
        print("       Is OPENAI_API_KEY set in .env?")
        return 1

    print("=" * 64)
    print("M0c - OpenAI auth + models")
    print("=" * 64)

    results = []
    ok, detail = check_chat(client, str(cfg.get("ai.model", "gpt-4o")))
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] chat answers")
    print(f"       {detail}")

    ok, detail = check_transcription(client, str(cfg.get("stt.model", "gpt-4o-mini-transcribe")))
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] transcription")
    print(f"       {detail}")

    print("=" * 64)
    n = sum(results)
    print(f"{n}/{len(results)} checks passed")
    return 0 if n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
