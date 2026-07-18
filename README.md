# Real-Time Meeting Answer Assistant

A Windows desktop tool that listens to your meeting, transcribes what others say,
and shows Claude-generated suggested answers on an overlay that is **hidden from
most screen-capture paths** (Zoom / Teams / Meet). Goal: support your own
communication in real time without the overlay leaking into a shared screen.

> Invisibility is **best-effort**, not a security boundary — see `plan.md`.

## Known-good environment

Verified on:

| | |
|---|---|
| OS | Windows 11 (10.0.26200) |
| Python | 3.12.5, 64-bit |
| GPU | NVIDIA RTX 4050 Laptop, 6 GB VRAM |
| Driver | 610.74 |
| Key deps | PySide6 6.11.1 · faster-whisper 1.2.1 / ctranslate2 4.8.1 · torch 2.13.0+cpu · silero-vad 6.2.1 · anthropic 0.116.0 |

Full pinned set in `requirements.txt`.

### CUDA note (the #1 install risk)
faster-whisper's GPU path needs `nvidia-cublas-cu12` + `nvidia-cudnn-cu12`
(both in `requirements.txt`). Their DLLs live in `site-packages/nvidia/*/bin`,
which is **not** on the default DLL search path. The code makes them loadable at
runtime by registering each `bin` dir with **both** `os.add_dll_directory` and
`PATH` (cuBLAS is loaded lazily via a plain `LoadLibrary`, which searches PATH
but not `add_dll_directory` dirs). See `scripts/check_env.py`.

## Setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env   # then paste your ANTHROPIC_API_KEY
```

## Diagnostics (milestone M0)

```powershell
.\.venv\Scripts\python.exe scripts\check_env.py        # M0a env & devices (VAD/GPU/STT/WASAPI)
.\.venv\Scripts\python.exe scripts\check_affinity.py   # M0b capture-shield read-back
.\.venv\Scripts\python.exe scripts\check_audio.py      # M0d live loopback level meter
.\.venv\Scripts\python.exe scripts\check_api.py        # M0c Claude auth (needs .env)  [pending]
```

## Run the overlay (M1)

```powershell
.\.venv\Scripts\python.exe -m src.main --demo --hold   # keep open; share screen to test invisibility
.\.venv\Scripts\python.exe -m src.main --demo --seconds 3   # quick self-check
```
Press **Esc** to close.

## Status

- **M0a** env & devices — ✅ 4/4
- **M0b** capture-shield read-back — ✅
- **M0d** loopback level meter — ✅
- **M0c** Claude auth — ⏸ needs API key
- **M1** hidden overlay window — ✅ built; visual screen-share gate pending
- M2+ — hotkeys, audio capture, VAD+STT, context, Claude answers (see `plan.md`)

Personal context goes in `context/*.md` (gitignored). See `context/README.md`.
