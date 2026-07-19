# Meeting Assistant — Hotkeys

All hotkeys are **global**: they work even while Zoom / Teams / Meet is the
focused window, so you never have to click the overlay (which would look
obvious on a shared screen).

> **On macOS**, `Alt` is the **Option** key — the app displays these as
> `Ctrl+Opt+A` and so on. Global hotkeys also require **Accessibility**
> permission (System Settings → Privacy & Security → Accessibility); without it
> they silently never fire. The app warns you at startup when it detects this.

| Hotkey | Action |
|---|---|
| **Ctrl + Alt + A** | **Answer the last spoken question** (from what it heard). If nothing was heard, jumps to the chat box so you can type. |
| **Ctrl + Alt + S** | **Analyze the screen** — screenshots your monitor and answers about what's on it (shared slide, coding question, doc). |
| **Ctrl + Alt + [** | Previous answer (scroll back through answer history). |
| **Ctrl + Alt + ]** | Next answer (forward; past the newest returns you to live). |
| **Ctrl + Alt + H** | Hide / show the overlay. |
| **Ctrl + Alt + T** | Toggle click-through (mouse passes through the panel; toggle off to type/move). |
| **Ctrl + Alt + ← ↑ → ↓** | Move the overlay around the screen. |
| **Ctrl + Shift + E** | **Emergency erase** — instantly wipe transcript, answer, and history, then quit. |
| **Ctrl + Alt + Q** | Quit the app. |

### Chat box
- Click the box at the bottom of the panel, type a question, press **Enter** — the answer streams in.
- To type, **click-through must be off** (it is by default; toggle with Ctrl + Alt + T).

### The typical interview flow
1. The interviewer speaks → the transcript panel fills in automatically.
2. Press **Ctrl + Alt + A** → a concise answer streams in.
3. Use **Ctrl + Alt + [ / ]** to look back at earlier answers.
4. **Ctrl + Alt + S** for anything shown on screen (a coding prompt, slides).

### Notes
- Answers are concise for concept questions and full (with code) when you ask it to write code.
- It hears **output** audio (the other people through your speakers/headphones), not your own mic.
- **On Windows** the overlay is hidden from screen sharing, but that is
  best-effort — verify in your meeting app.
- **On macOS and Linux the overlay is NOT hidden.** No API exists to do it there,
  so anyone you share your screen with can see the panel. The app refuses to
  start unless you pass `--i-know-its-visible`, and then shows a permanent red
  banner. See "Platform support" in the README.
