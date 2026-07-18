# Real-Time Meeting Answer Assistant

A Windows desktop tool that listens to your meeting, transcribes what the other
people say, and shows AI-generated suggested answers on an overlay that is
**hidden from most screen-capture paths** (Zoom / Teams / Meet). The goal is to
support your own communication in real time without the overlay leaking into a
shared screen.

> **Invisibility is best-effort, not a security boundary.** The overlay uses
> `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`, which the OS honors for
> most capture paths — but always verify inside your actual meeting app before
> relying on it.

> **Privacy note:** with the default config, your microphone-side system audio
> and (on demand) a screenshot of your monitor are sent to OpenAI for
> transcription and answers. Nothing is written to disk unless you enable debug
> logging. See [Privacy & data flow](#privacy--data-flow).

---

## What it does

- **Hears the meeting.** Captures system output audio (what you hear through
  your speakers/headphones — *not* your own mic) via WASAPI loopback.
- **Transcribes speech only.** A local Silero VAD trims silence so only actual
  speech is uploaded to OpenAI transcription (saves cost and latency).
- **Answers automatically.** When the speaker stops and the last utterance looks
  like a question, it streams a concise, speakable answer onto the overlay.
- **Answers on demand.** Press a hotkey to answer the last spoken question, type
  a question in the chat box, or screenshot your screen and ask about it.
- **Stays off shared screens.** The overlay window is excluded from screen
  capture and confirms the exclusion via an OS read-back.
- **Recovers from real conditions.** If your audio device is unplugged or the
  default output changes mid-meeting, capture reopens on the new device.

---

## Requirements

| | |
|---|---|
| OS | Windows 10 2004+ or Windows 11 (capture exclusion needs this) |
| Python | 3.12, 64-bit |
| API key | An **OpenAI** API key (used for both transcription and answers) |
| Audio | A WASAPI loopback-capable default output device (standard on Windows) |

Everything runs on CPU. `torch` is pinned to the **CPU build** — it's used only
for the Silero VAD, and transcription/answers are cloud calls to OpenAI, so no
GPU is required. Full pinned dependency set is in `requirements.txt`.

---

## Setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env      # then open .env and paste your OpenAI key
```

Your `.env` should contain:

```
OPENAI_API_KEY=sk-...your key here...
```

Get a key at <https://platform.openai.com/api-keys>. The `.env` file is
gitignored and never committed.

---

## Run it

```powershell
# Live: overlay + global hotkeys + audio capture + auto-answer + chat
.\.venv\Scripts\python.exe -m src.main

# Demo: placeholder transcript/answer, no audio or API calls (test the overlay)
.\.venv\Scripts\python.exe -m src.main --demo --hold      # stays open
.\.venv\Scripts\python.exe -m src.main --demo --seconds 3 # quick self-check
```

Run from the project root so the `src` package is importable. Only one live
instance can run at a time (it holds a named mutex so hotkeys don't clash).

In live mode the overlay appears immediately; the audio pipeline loads the VAD
on a background thread, so the status row shows `stt: loading → ready` as it
comes up.

---

## Hotkeys

All hotkeys are **global** — they fire even while the meeting app is the focused
window, so you never have to click the overlay (which would look obvious on a
shared screen). Full reference in [`HOTKEYS.md`](HOTKEYS.md).

| Hotkey | Action |
|---|---|
| **Ctrl + Alt + A** | Answer the last spoken question (or focus the chat box if nothing was heard) |
| **Ctrl + Alt + Space** | Toggle auto-answer on/off |
| **Ctrl + Alt + S** | Analyze the screen — screenshots your monitor and answers about it |
| **Ctrl + Alt + [ / ]** | Previous / next answer in history |
| **Ctrl + Alt + H** | Hide / show the overlay |
| **Ctrl + Alt + T** | Toggle click-through (mouse passes through the panel) |
| **Ctrl + Alt + ← ↑ → ↓** | Move the overlay around the screen |
| **Ctrl + Shift + E** | Emergency erase — wipe transcript, answer, and history, then quit |
| **Ctrl + Alt + Q** | Quit |

The overlay also has a chat box (type + Enter) and follow-up buttons
(Shorter / Deeper / Example / Code / Natural) that refine the current answer.

---

## Configuration

`config.yaml` is optional and partial — anything it omits falls back to the code
defaults in `src/config.py`. Notable settings:

| Key | Default | Meaning |
|---|---|---|
| `ai.model` | `gpt-5.2` | Model used for answers (supports vision for screen analysis) |
| `ai.auto_answer` | `true` | Auto-answer when the speaker stops (toggle with Ctrl+Alt+Space) |
| `ai.auto_answer_delay_ms` | `900` | Silence to wait for before auto-answering |
| `stt.model` | `gpt-4o-mini-transcribe` | Transcription model (`gpt-4o-transcribe` is higher quality) |
| `stt.language` | `en` | Transcription language |
| `overlay.anchor` | `top-right` | Corner the overlay anchors to |
| `overlay.opacity` | `0.92` | Window opacity (0–1) |
| `screen.enabled` | `true` | Allow Ctrl+Alt+S screen analysis (sends a screenshot to OpenAI) |
| `privacy.debug_content_logging` | `false` | Opt-in, redacted debug logging |

---

## Diagnostics

Optional checks under `scripts/` to verify your environment before a real
meeting:

```powershell
.\.venv\Scripts\python.exe scripts\check_env.py        # env, VAD, audio devices
.\.venv\Scripts\python.exe scripts\check_affinity.py   # capture-shield read-back
.\.venv\Scripts\python.exe scripts\check_audio.py      # live loopback level meter
.\.venv\Scripts\python.exe scripts\check_api.py        # OpenAI auth: chat + transcription (needs .env)
```

---

## How it works

```
WASAPI loopback capture ──► 16 kHz mono ──► Silero VAD ──► OpenAI transcription
   (src/audio/capture.py)   (preprocess)    (audio/vad)     (stt/transcriber.py)
                                                                     │
                                                              transcript text
                                                                     │
                                                                     ▼
        overlay panel ◄── streamed answer ◄── OpenAI chat ◄── Conversation
     (overlay/window.py)                     (ai/conversation.py, keeps context)
```

- **`src/main.py`** — entry point; wires the pipeline, hotkeys, overlay, and the
  auto-answer logic together. OpenAI clients are built lazily on first use.
- **`src/core/pipeline.py`** — background worker: drains the capture ring
  buffer, runs VAD to cut complete utterances, and transcribes each in order.
  Delivers results to the UI as Qt signals.
- **`src/audio/`** — WASAPI loopback capture with drop-oldest ring buffer and
  device-recovery, audio preprocessing, and the Silero VAD.
- **`src/ai/conversation.py`** — stateful chat that keeps history so follow-ups
  (including questions about a captured screenshot) stay in context.
- **`src/overlay/`** — the frameless always-on-top window with capture exclusion,
  the global Win32 hotkey manager, click-through, and the status row.

---

## Privacy & data flow

- **Audio** heard in the meeting is uploaded to OpenAI for transcription (only
  detected speech, not silence).
- **Screenshots** are sent to OpenAI only when you press Ctrl+Alt+S.
- **Nothing is written to disk** by default. `logs/`, `.env`, and your personal
  `context/*.md` files are all gitignored.
- Set `privacy.debug_content_logging: true` only if you want opt-in, redacted
  debug logs.

Personal context you want the assistant to know goes in `context/*.md`
(gitignored) — see `context/README.md`.

---

## Troubleshooting

- **`[needs OPENAI_API_KEY: ...]` on the overlay** — your `.env` is missing or
  the key is invalid. Run `scripts\check_api.py` to confirm.
- **No transcript appears** — no audio is being captured. Make sure something is
  actually playing through your default output device; check the `capture`
  status in the overlay's status row.
- **Overlay still shows on a shared screen** — capture exclusion is best-effort
  and depends on the capture method the meeting app uses. Verify with
  `scripts\check_affinity.py` and test inside your actual meeting app.
- **A hotkey does nothing** — another app may already own that global chord. The
  console prints a warning listing any hotkeys that failed to register.
