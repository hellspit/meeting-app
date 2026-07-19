# Real-Time Meeting Answer Assistant

A desktop tool that listens to your meeting, transcribes what the other people
say, and shows AI-generated suggested answers on an overlay panel. On Windows
that overlay is **hidden from most screen-capture paths** (Zoom / Teams / Meet),
so it doesn't leak into a shared screen.

> **Read [Platform support](#platform-support) before using this on macOS or
> Linux.** The overlay can only be hidden on Windows. That isn't a missing
> feature — no API exists to do it anywhere else, so on those platforms the
> panel is visible to everyone you share your screen with. The app refuses to
> start there unless you explicitly acknowledge it.

> **Privacy:** with the default config, meeting audio and (on demand) a
> screenshot of your monitor are sent to OpenAI. Nothing is written to disk
> unless you enable debug logging. See [Privacy & data flow](#privacy--data-flow).

---

## What it does

- **Hears the meeting.** Captures system output audio — what you hear through
  your speakers/headphones, *not* your own mic.
- **Transcribes speech only.** A local Silero VAD trims silence so only actual
  speech is uploaded (saves cost and latency, and avoids Whisper's silence
  hallucinations).
- **Answers automatically.** When the speaker stops and the last utterance looks
  like a question, it streams a concise, speakable answer onto the overlay.
- **Answers on demand.** Hotkey to answer the last spoken question, a chat box
  to type one, or a hotkey to screenshot your screen and ask about it.
- **Stays off shared screens** — on Windows. See below.
- **Recovers from real conditions.** If your audio device is unplugged or the
  default output changes mid-meeting, capture reopens on the new device.

---

## Platform support

The core "hidden from screen share" guarantee is **Windows-only**, and cannot be
ported. This is the honest state of each OS:

| Platform | Overlay hidden from capture? | Why |
|---|---|---|
| **Windows** 10 2004+ / 11 | ✅ **Yes**, confirmed by read-back | `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` |
| **macOS ≤ 14** | ⚠️ Legacy capture only | `NSWindow.sharingType` blocks old CoreGraphics paths, but not ScreenCaptureKit |
| **macOS 15+** (Sequoia and later) | ❌ **No** | macOS composites all windows into one framebuffer that ScreenCaptureKit reads. Apple: *"there are no public APIs for preventing screen capture."* Electron and Tauri hit the same wall. |
| **Linux (X11)** | ❌ **No** | Any client can read the full framebuffer; no window-level exclusion exists |
| **Linux (Wayland)** | ❌ **No** | Screen sharing is consent-based via xdg-desktop-portal; no protocol lets a window exclude itself |

Since modern Zoom/Teams/Meet all use ScreenCaptureKit on macOS, **every current
Mac falls in the ❌ row.**

Everything *else* works cross-platform: audio capture, VAD, transcription,
answers, screen analysis, hotkeys, click-through. So the app is still useful off
Windows for solo interview prep, practice runs, and calls you aren't sharing —
just not as a hidden overlay.

To reflect that, the app **refuses to start** where the shield is unavailable:

```
  REFUSING TO START
  ----------------------------------------
  Platform: macOS 26.1
  Capture shield: UNAVAILABLE
  ...
  Re-run with --i-know-its-visible if that
  is acceptable for your use case.
```

Pass `--i-know-its-visible` to proceed. The panel then carries a permanent red
`⚠ VISIBLE IN SCREEN SHARE` banner, so you can never forget which mode you're in.

**Verification status:** Windows is verified end to end on real hardware. The
macOS and Linux paths are implemented and their logic is unit-tested, but have
**not** been run on real hardware — treat first-run there as a shakeout, and use
the diagnostics below.

---

## Requirements

| | |
|---|---|
| Python | 3.12, 64-bit |
| API key | An **OpenAI** key (used for both transcription and answers) |
| Windows | 10 2004+ / 11. Audio works out of the box (WASAPI loopback) |
| macOS | 12+. **Requires a virtual audio driver** — see setup. Needs Accessibility + Screen Recording permissions |
| Linux | PulseAudio or PipeWire (for `.monitor` sources). X11 for global hotkeys |

Everything runs on CPU — `torch` is pinned to the CPU build and is used only for
the Silero VAD; transcription and answers are cloud calls. No GPU needed.

---

## Setup

### 1. Install

```bash
# Windows
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env

# macOS / Linux
python3.12 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Then put your key in `.env`:

```
OPENAI_API_KEY=sk-...
```

Get one at <https://platform.openai.com/api-keys>. `.env` is gitignored.

### 2. macOS only — system audio

macOS has **no system-audio loopback**, so a virtual audio driver is required.
Without it the app cannot hear the meeting at all.

```bash
brew install --cask blackhole-2ch
```

Then, so you can capture the audio *and still hear it*:

1. Open **Audio MIDI Setup**.
2. Create a **Multi-Output Device** containing **both** your speakers/headphones
   **and** BlackHole 2ch.
3. Set that Multi-Output Device as your system output.
4. Verify with `python scripts/check_audio.py --list` — you should see
   `BlackHole 2ch` flagged loopback-capable.

If auto-detection picks the wrong device, pin it in `config.yaml`:

```yaml
audio:
  input_device: "BlackHole"
```

### 3. macOS only — permissions

- **Accessibility** (System Settings → Privacy & Security → Accessibility) —
  required for global hotkeys. Add your terminal or the Python binary. Without
  it, hotkeys silently never fire; the app warns you at startup if it detects this.
- **Screen Recording** — required for the Ctrl+Opt+S screen-analysis feature.

### 4. Linux only — system audio

PulseAudio/PipeWire already expose a `.monitor` source per output sink:

```bash
pactl list short sources | grep monitor
```

Set `audio.input_device` to part of that name if auto-detection misses it.

---

## Run it

```bash
# Windows
.\.venv\Scripts\python.exe -m src.main

# macOS / Linux (overlay is NOT hidden — see Platform support)
./.venv/bin/python -m src.main --i-know-its-visible
```

Other modes:

```bash
python -m src.main --demo --hold        # placeholder content, no audio/API calls
python -m src.main --demo --seconds 3   # quick self-check
```

Run from the project root so the `src` package is importable. Only one live
instance runs at a time (enforced with a lock file, so hotkeys can't clash).

The overlay appears immediately; the VAD loads on a background thread, so the
status row shows `stt: loading → ready` as it comes up.

---

## Hotkeys

Global — they fire even while the meeting app is focused, so you never alt-tab
(which is exactly the tell this tool exists to avoid). Full reference in
[`HOTKEYS.md`](HOTKEYS.md). On macOS, Alt is the **Option** key.

| Hotkey | Action |
|---|---|
| **Ctrl + Alt + A** | Answer the last spoken question (or focus the chat box if nothing was heard) |
| **Ctrl + Alt + Space** | Toggle auto-answer |
| **Ctrl + Alt + S** | Analyze the screen — screenshots your monitor and answers about it |
| **Ctrl + Alt + [ / ]** | Previous / next answer in history |
| **Ctrl + Alt + H** | Hide / show the overlay |
| **Ctrl + Alt + T** | Toggle click-through |
| **Ctrl + Alt + ← ↑ → ↓** | Move the overlay |
| **Ctrl + Shift + E** | Emergency erase — wipe everything and quit |
| **Ctrl + Alt + Q** | Quit |

The panel also has a chat box (type + Enter) and follow-up buttons
(Shorter / Deeper / Example / Code / Natural) that refine the current answer.

---

## Configuration

`config.yaml` is optional and partial — anything it omits falls back to the code
defaults in `src/config.py`.

| Key | Default | Meaning |
|---|---|---|
| `ai.model` | `gpt-5.2` | Answer model (needs vision for screen analysis) |
| `ai.auto_answer` | `true` | Auto-answer when the speaker stops |
| `ai.auto_answer_delay_ms` | `900` | Silence to wait for before auto-answering |
| `stt.model` | `gpt-4o-mini-transcribe` | Transcription model (`gpt-4o-transcribe` is higher quality) |
| `audio.input_device` | `""` | Pin capture to a device by name substring; empty = auto |
| `overlay.anchor` | `top-right` | Corner the overlay anchors to |
| `overlay.opacity` | `0.92` | Window opacity (0–1) |
| `screen.enabled` | `true` | Allow screen analysis (sends a screenshot to OpenAI) |
| `privacy.debug_content_logging` | `false` | Opt-in, redacted debug logging |

---

## Diagnostics

Run these before a real meeting — they're cross-platform and each explains how to
fix what it finds:

```bash
python scripts/check_env.py           # torch/VAD, loopback device, API key, shield status
python scripts/check_audio.py --list  # enumerate capturable devices
python scripts/check_audio.py         # live level meter (play audio while it runs)
python scripts/check_affinity.py      # capture-shield probe (--hold for a share test)
python scripts/check_api.py           # OpenAI auth: chat + transcription
```

---

## How it works

```
system audio ──► 16 kHz mono ──► Silero VAD ──► OpenAI transcription
 (audio/loopback_*)  (preprocess)   (audio/vad)     (stt/transcriber)
                                                            │
                                                     transcript text
                                                            ▼
       overlay panel ◄── streamed answer ◄── OpenAI chat ◄── Conversation
     (overlay/window.py)                    (ai/conversation.py, keeps context)
```

Platform-specific behavior is isolated behind three seams, so the shared logic
(ring buffer, device recovery, VAD, streaming, history) has no OS branches:

| Concern | Windows | macOS / Linux |
|---|---|---|
| Capture shield (`overlay/shield.py`) | `SetWindowDisplayAffinity` | `NSWindow.sharingType` (legacy only) / nothing |
| Audio (`audio/loopback.py`) | WASAPI via PyAudioWPatch | PortAudio via sounddevice |
| Hotkeys (`overlay/hotkeys.py`) | Win32 `RegisterHotKey` | pynput `GlobalHotKeys` |

`src/platform/__init__.py` is the single source of truth for what each OS can
actually promise, and drives both the startup gate and the in-panel banner.

---

## Privacy & data flow

- **Audio** heard in the meeting is uploaded to OpenAI for transcription (only
  detected speech, never silence).
- **Screenshots** are sent only when you press the screen-analysis hotkey.
- **Nothing is written to disk** by default. `logs/`, `.env`, and your personal
  `context/*.md` files are gitignored.
- If no loopback device is found, capture **fails rather than falling back to
  your microphone** — recording yourself instead of the meeting would be both
  useless and a privacy surprise.

Personal context for the assistant goes in `context/*.md` (gitignored) — see
`context/README.md`.

---

## Troubleshooting

- **"REFUSING TO START"** — expected on macOS/Linux. See
  [Platform support](#platform-support); re-run with `--i-know-its-visible`.
- **`[needs OPENAI_API_KEY: ...]` on the overlay** — `.env` missing or invalid.
  Run `scripts/check_api.py`.
- **No transcript appears** — nothing is being captured. Run
  `scripts/check_audio.py` with audio playing. On macOS this almost always means
  BlackHole isn't installed or isn't in your Multi-Output Device.
- **Hotkeys do nothing on macOS** — grant Accessibility permission and restart.
  The startup output warns when it detects this.
- **A hotkey does nothing on Windows** — another app owns that chord; the console
  lists any that failed to register.
- **Overlay still visible on a shared screen (Windows)** — verify with
  `scripts/check_affinity.py --hold` and test inside your actual meeting app.
  Exclusion is best-effort and depends on the capture method the app uses.
