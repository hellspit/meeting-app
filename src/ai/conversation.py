"""Stateful chat with OpenAI that remembers context across turns.

Keeps a running message history so follow-ups work: analyze the screen once,
then when the interviewer asks a question *about it*, the model still has the
image and prior exchange in context. Typed questions (the overlay chat box),
screen analyses, and (later) spoken questions all flow through one Conversation.

Tuned for interviews/meetings: give a COMPLETE, correct, well-structured answer
the user can read aloud — including real code for technical questions.
"""

from __future__ import annotations

from collections.abc import Iterator

from src.ai.screen import _data_url, _downscale_png_if_needed

SYSTEM_PROMPT = (
    "You are a real-time interview and meeting assistant. Answer the way a "
    "strong candidate would SPEAK OUT LOUD — natural, concise, first person, "
    "and to the point. The user reads your answer aloud, so brevity matters.\n"
    "\n"
    "LENGTH — match a real spoken answer, not documentation:\n"
    "- Conceptual, verbal, or behavioral questions ('what is X', 'difference "
    "between X and Y', 'tell me about...'): answer in about 2 to 4 sentences, "
    "or at most 2-3 short bullets. Give the direct answer plus one or two key "
    "points. Do NOT list every subtopic, framework, tradeoff, or edge case.\n"
    "- ONLY give a long, detailed answer when the question explicitly asks you "
    "to WRITE CODE, implement, or solve a coding problem — then include the "
    "concrete, correct code.\n"
    "- You may end with one short line like 'I can go deeper on X if useful.' "
    "when real depth exists, but keep it to a single line.\n"
    "\n"
    "FORMAT — shown in a plain-text box and read aloud:\n"
    "- PLAIN TEXT only. No Markdown (no **bold**, *italics*, backticks, # "
    "headers, or ``` fences) and no LaTeX (never \\( \\), \\[ \\], \\log). "
    "Write math in words, e.g. 'O(log(min(m, n)))'.\n"
    "- Short sentences; use a couple of hyphen bullets only if it genuinely "
    "helps. When you do give code, write it as plain indented lines.\n"
    "\n"
    "If a screenshot is provided, answer about what is actually shown and keep "
    "it as context for follow-ups. Never invent facts; if unsure, say so briefly."
)

# Cap history so token cost stays bounded in a long session. We always keep the
# system prompt and trim the oldest turns beyond this many messages.
MAX_HISTORY_MESSAGES = 24


class Conversation:
    def __init__(
        self, client, model: str, max_tokens: int = 900, system: str | None = None
    ):
        self.client = client
        self.model = model
        self.max_tokens = max_tokens
        self._system = {"role": "system", "content": system or SYSTEM_PROMPT}
        self.messages: list[dict] = [self._system]

    def add_screen(self, png: bytes, note: str | None = None) -> None:
        """Attach a screenshot as context for subsequent questions."""
        self.messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": note or "Here is my current screen."},
                    {
                        "type": "image_url",
                        "image_url": {"url": _data_url(_downscale_png_if_needed(png))},
                    },
                ],
            }
        )
        self._trim()

    def ask_stream(self, question: str) -> Iterator[str]:
        """Append `question`, stream the answer, and record it in history."""
        self.messages.append({"role": "user", "content": question})
        self._trim()
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=self.messages,
            max_completion_tokens=self.max_tokens,  # gpt-5.x rejects max_tokens
            stream=True,
        )
        parts: list[str] = []
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                parts.append(delta)
                yield delta
        self.messages.append({"role": "assistant", "content": "".join(parts)})

    def reset(self) -> None:
        self.messages = [self._system]

    def _trim(self) -> None:
        if len(self.messages) <= MAX_HISTORY_MESSAGES:
            return
        # Keep system + the most recent (MAX_HISTORY_MESSAGES - 1) messages.
        self.messages = [self._system, *self.messages[-(MAX_HISTORY_MESSAGES - 1) :]]
