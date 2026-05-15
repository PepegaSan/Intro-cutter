# Intro Cutter

Trim a fixed **intro** (seconds from the start) and **outro** (seconds from the end) off videos — via **FFmpeg** or **DaVinci Resolve Studio**.

Useful for removing channel bumpers, slates, or tail padding in bulk.

## Modes

| Mode | You control quality via | Needs |
|------|-------------------------|--------|
| **FFmpeg** | Codec + video/audio bitrate in the GUI | `ffmpeg`, `ffprobe` on `PATH` |
| **DaVinci Resolve** | Deliver preset name in Resolve | Resolve **Studio**, external scripting = Local, `davinci_api.py` in this folder |

## Features

- **GUI** with drag & drop (`start_intro_cutter_gui.bat`)
- **Batch files** for drag-drop or file picker (`intro_cut_dragdrop.bat`, `start_intro_cutter.bat`)
- Optional shared **output folder** in settings (gear icon)
- GUI settings stored under `%LOCALAPPDATA%\IntroCutter\settings.json` (not in the repo)

## Install

```bat
install.bat
```

Then open `start_intro_cutter_gui.bat`.

`intro_cut_defaults.json` in the project folder stores last-used values when you use the PowerShell/CLI path; the GUI uses its own settings file in AppData.

## License

MIT
