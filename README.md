# Otter — The Desktop Quota Otter 🦦

> A tiny, always-on-top Windows desktop companion that visualizes your weekly AI token burn. Otter gets happier as you approach your quota, walks across your screen when bored, and sips a drink during breaks.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)
![License](https://img.shields.io/badge/License-MIT-green)

---

## ✨ What is Otter?

Otter is a **single-file, dependency-light Windows desktop widget** written in Python. He floats above your windows as a borderless, transparent otter and reflects how much of your weekly Claude / Codex / generic AI token budget you've used.

Built to stay out of the way but always be visible, Otter is:

- **Always on top** — never disappears behind VS Code or Chrome.
- **Draggable** — grab him by the body and reposition anywhere.
- **System-tray resident** — hide, show, or quit from the tray icon.
- **Privacy-first** — reads local logs and JSON files; no cloud API keys required.

---

## 🎬 Demo

<!-- Replace the placeholders below with your own recordings/images when you upload to GitHub -->

| Idle | Walking | Sipping |
|:--:|:--:|:--:|
| ![idle](docs/idle.png) | ![walk](docs/walk.png) | ![sip](docs/sip.png) |

> **Tip:** Add a short screen recording (`docs/demo.mp4` or GIF) to make the README stand out.

---

## 🚀 Quick Start

### Prerequisites

- Windows 10/11
- Python 3.10+ with Tcl/Tk (standard on most Windows Python installs)
- **Pillow** is optional but strongly recommended for smooth scaling and walking-direction flipping:

```bash
pip install Pillow
```

Without Pillow, Otter falls back to Tkinter's `subsample` scaler (blockier edges, no sprite flipping).

### Run Otter

```bash
python otter.py
```

That's it. No build step, no bundled executable, no `requirements.txt` needed for the base experience.

### Run the smoke test

```bash
python otter.py --self-test
```

---

## 🎮 Usage

### Interactions

| Action | Result |
| --- | --- |
| **Left-click + drag** on Otter | Reposition the window |
| **Left-click** (no drag) | Triggers a reaction animation (pat, celebrate, swim, float, or walk) |
| **Double-click** Otter | Opens Settings |
| **Right-click** Otter | Context menu: Settings / Reset Position / Quit |
| **Tray icon right-click** | Show / Hide / Settings / Exit |

### Automatic behaviors

- **Idle:** Otter mostly relaxes in place.
- **Walking:** He periodically strolls horizontally across the screen, flips direction at the edges, and pauses along the way.
- **Sipping:** During pauses he occasionally sips a drink (placeholder frames included — replace them with custom art!).

---

## ⚙️ Configuration

All settings live in `config.json`, created automatically on first run.

```json
{
  "window": {
    "x": 136,
    "y": 822,
    "width": 126,
    "height": 104
  },
  "quota": {
    "weekly_quota_tokens": 1000000,
    "tokens_used": 0,
    "data_source": "combined_local",
    "poll_interval_sec": 30
  },
  "appearance": {
    "otter_scale": 0.5,
    "show_percentage_badge": false
  }
}
```

### Data sources

| Source | Description |
| --- | --- |
| `manual` | Type your token count in Settings. |
| `local_json` | Watch a local `usage.json` file. |
| `claude_local` | Scan `~/.claude/projects` and `~/.claude/sessions` JSONL logs. |
| `codex_local` | Scan `~/.codex/sessions` JSONL logs. |
| `combined_local` | Aggregate Claude + Codex logs. |
| `auto_local` | Automatically prefer Codex logs, fall back to Claude. |
| `claude_api` | Reserved for future Anthropic API integration. |

### `usage.json` schema

Used when `data_source` is `local_json`:

```json
{
  "week_start": "2025-06-09",
  "tokens_used": 420000,
  "quota": 1000000
}
```

---

## 🏗️ Architecture

```
clauder/
├── otter.py            # Single runnable entry point
├── config.json         # User preferences & window position
├── usage.json          # Optional watched local usage data
├── assets/
│   └── otter_animations/
│       ├── idle/       # Standing still
│       ├── walk/       # Horizontal movement
│       ├── swim/       # Swimming
│       ├── float/      # Floating
│       ├── sleep/      # Sleeping
│       ├── pat/        # Patted by user
│       ├── celebrate/  # Click interaction only
│       └── sip/        # Pause/drink behavior
└── README.md
```

### Tech stack

| Layer | Choice |
| --- | --- |
| Language | Python 3.10+ |
| GUI | Tkinter + ttk |
| Image handling | Pillow (optional) / Tkinter PhotoImage fallback |
| System tray | Raw Win32 `ctypes` (`Shell_NotifyIconW`) |
| Animation | Tkinter `after()` loop at ~30 FPS |
| Persistence | `json`, `pathlib` |

### Design highlights

- **Standard-library-first:** Runs out of the box with only Python + Tkinter.
- **Optional Pillow path:** When Pillow is present, frames are converted to RGBA, the magenta background is masked, and LANCZOS resampling gives smooth edges at any scale.
- **State machine:** A lightweight `idle → walking → pausing → ...` behavior loop decides what Otter does, separate from the animation loop.
- **Flipped sprites:** Pillow transposes walk frames horizontally so Otter faces the direction he's walking.

---

## 🛣️ Roadmap / Future Scope

This project is intentionally a compact, focused widget, but there is plenty of room to grow. Below are ideas for the next iterations.

### More pets

- Add a **pet selection system** so users can choose between Otter (otter), a cat, a dog, a bird, etc.
- Each pet would live in its own `assets/<pet>_animations/` directory.
- A `pet` key in `config.json` switches the active asset pack on restart.
- Stretch: **community pet packs** loaded from a user-defined folder.

### Smoother, richer animations

- **Higher-resolution artwork** — replace the current pixel-art GIFs with smooth vector-rendered or hand-drawn frames.
- **Procedural animation** — add subtle breathing, ear twitches, and tail wagging using canvas transforms.
- **Transition blending** — cross-fade between mood states and animation states instead of snapping.
- **Direction-aware animations** — separate `walk_left` and `walk_right` frames for non-symmetric pets.
- **Sound effects** — tiny WAVs on interactions, mood transitions, or when reaching quota milestones (uses the built-in `winsound` module on Windows).

### Deeper integrations

- **Anthropic / Claude API polling** — real usage data with a user-supplied API key.
- **OpenAI, Gemini, and other providers** — pluggable usage sources.
- **Native Windows toast notifications** when crossing 50%, 75%, 100% burn.
- **macOS / Linux ports** — refactor the Win32 tray code behind a platform abstraction.

### Quality-of-life

- **Multi-monitor awareness** — constrain walking to the monitor Otter is currently on.
- **Snooze mode** — hide Otter for a configurable period.
- **Themes / colorways** — dark mode body tints, seasonal skins.
- **Auto-updater** — check GitHub releases on startup.

### Engineering

- **Single-file executable** — package with `PyInstaller` or `nuitka` so users without Python can run Otter.
- **Test suite** — expand the built-in self-test to cover walking behavior and sprite flipping.
- **CI/CD** — GitHub Actions for linting, testing, and release builds.

---

## 🤝 Contributing

Contributions are welcome! Some great first issues:

- Draw a proper `sip/` animation (current frames are placeholders copied from `idle/`).
- Add a second pet asset pack.
- Implement Windows toast notifications.
- Port the tray icon to macOS or Linux.

1. Fork the repo
2. Create a feature branch: `git checkout -b feature/amazing-idea`
3. Commit your changes
4. Open a pull request

---

## 📝 License

MIT — feel free to use, modify, and share.

---

## 🙏 Acknowledgements

- Built as a weekend exploration in writing friendly desktop UI with nothing but Python's standard library.
- Inspired by classic desktop pets and the need to keep AI usage visible without being intrusive.

---

> *"Let Otter keep an eye on your quota so you can keep coding."*
