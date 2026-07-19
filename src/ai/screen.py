"""Screen analysis via GPT-4o vision.

Grabs a screenshot of the target monitor and asks the answer model what's on it,
so suggestions can account for a shared slide, a coding prompt, a document, etc.

On Windows the overlay is excluded from OS capture, so it does not appear in
these screenshots — the model sees only what's underneath. Where that exclusion
is unavailable (macOS/Linux), the caller hides the overlay for the duration of
the grab instead; otherwise the model would be shown its own previous answer.
See `_grab_screen_png` in src/main.py.

Uses `mss` for a fast grab and encodes a PNG as a base64 data URL in the chat
`image_url` content block (the standard OpenAI vision format).
"""

from __future__ import annotations

import base64
from typing import Callable, Iterator

import mss
import mss.tools

# Keep the screenshot from being huge: cap the long edge. GPT-4o downsamples
# anyway, and smaller images are cheaper + faster to upload.
MAX_EDGE = 1600


def capture_monitor_png(monitor_index: int = 0) -> bytes:
    """Return a PNG screenshot of the given monitor (0 = primary).

    mss monitor list is 1-based with index 0 = "all monitors" virtual screen;
    we map our 0-based primary to mss index 1.
    """
    with mss.mss() as sct:
        monitors = sct.monitors  # [all, mon1, mon2, ...]
        idx = monitor_index + 1
        if idx >= len(monitors):
            idx = 1
        shot = sct.grab(monitors[idx])
        return mss.tools.to_png(shot.rgb, shot.size)


def _downscale_png_if_needed(png: bytes) -> bytes:
    """Best-effort shrink so the long edge <= MAX_EDGE. Falls back to original."""
    try:
        import io
        from PIL import Image  # Pillow may not be installed; optional
    except Exception:  # noqa: BLE001
        return png
    try:
        img = Image.open(io.BytesIO(png))
        w, h = img.size
        long_edge = max(w, h)
        if long_edge <= MAX_EDGE:
            return png
        scale = MAX_EDGE / long_edge
        img = img.resize((int(w * scale), int(h * scale)))
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()
    except Exception:  # noqa: BLE001
        return png


def _data_url(png: bytes) -> str:
    b64 = base64.b64encode(png).decode("ascii")
    return f"data:image/png;base64,{b64}"


def analyze_screen_stream(
    client,
    model: str,
    png: bytes,
    question: str,
    max_tokens: int = 320,
) -> Iterator[str]:
    """Yield answer text chunks for `question` about the screenshot `png`."""
    png = _downscale_png_if_needed(png)
    messages = [
        {
            "role": "system",
            "content": (
                "You help the user during a live meeting. Look at their screen "
                "and answer concisely, leading with a ready-to-say line. Write "
                "PLAIN TEXT only: no Markdown (**, *, backticks, #) and no LaTeX "
                "(\\( \\), \\log); write math in plain words like O(log n). Never "
                "invent facts you can't see."
            ),
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": _data_url(png)}},
            ],
        },
    ]
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        max_completion_tokens=max_tokens,  # gpt-5.x rejects max_tokens
        stream=True,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def analyze_screen(
    client,
    model: str,
    png: bytes,
    question: str,
    max_tokens: int = 320,
    on_chunk: Callable[[str], None] | None = None,
) -> str:
    """Non-streaming convenience wrapper; returns the full answer text."""
    parts: list[str] = []
    for chunk in analyze_screen_stream(client, model, png, question, max_tokens):
        parts.append(chunk)
        if on_chunk:
            on_chunk(chunk)
    return "".join(parts)
