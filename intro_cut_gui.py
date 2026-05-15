#!/usr/bin/env python3
"""Intro Cutter — tkinter-GUI mit Drag & Drop (Windows: windnd)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, simpledialog, ttk
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent

if sys.platform == "win32":
    try:
        import windnd  # type: ignore
    except ImportError:
        windnd = None
else:
    windnd = None

from intro_cut_ffmpeg import run_ffmpeg_cut  # noqa: E402


def settings_file() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    d = Path(base) / "IntroCutter"
    d.mkdir(parents=True, exist_ok=True)
    return d / "settings.json"


DEFAULT_SETTINGS: Dict[str, Any] = {
    "geometry": "780x720+80+60",
    "intro_sec": 3.0,
    "outro_sec": 2.0,
    "mode": "ffmpeg",
    "video_codec": "libx264",
    "video_bitrate": "8M",
    "video_bitrate_auto": False,
    "audio_codec": "aac",
    "audio_bitrate": "192k",
    "render_preset": "YouTube - 1080p",
    "resolve_exe": "",
    "fusionscript_dll": "",
    "scripting_modules": "",
    "output_dir": "",
    "intro_outro_presets": {
        "Standard": {"intro_sec": 3.0, "outro_sec": 2.0},
    },
    "selected_intro_outro_preset": "Standard",
}

VIDEO_EXT = {
    ".mp4",
    ".mkv",
    ".mov",
    ".m4v",
    ".avi",
    ".webm",
    ".mts",
    ".m2ts",
    ".mpg",
    ".mpeg",
    ".wmv",
}

# Dropdown: Encoder-Namen wie bei ffmpeg -c:v
FFMPEG_VIDEO_CODECS = (
    "libx264",
    "libx265",
    "libvpx-vp9",
    "libsvtav1",
    "libaom-av1",
    "h264_nvenc",
    "hevc_nvenc",
    "av1_nvenc",
    "mpeg4",
    "copy",
)


def load_settings() -> Dict[str, Any]:
    path = settings_file()
    if not path.is_file():
        return dict(DEFAULT_SETTINGS)
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        out = dict(DEFAULT_SETTINGS)
        if isinstance(data, dict):
            out.update({k: data[k] for k in DEFAULT_SETTINGS if k in data})
        return out
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_SETTINGS)


def save_settings(data: Dict[str, Any]) -> None:
    path = settings_file()
    try:
        merged = dict(DEFAULT_SETTINGS)
        merged.update(data)
        with path.open("w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        messagebox.showwarning("Speichern", f"Einstellungen konnten nicht gespeichert werden:\n{exc}")


def clamp_geometry(root: tk.Tk, w: int, h: int, x: int, y: int) -> str:
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    w = max(480, min(w, sw - 40))
    h = max(400, min(h, sh - 60))
    x = max(0, min(x, sw - 80))
    y = max(0, min(y, sh - 80))
    return f"{w}x{h}+{x}+{y}"


def parse_geometry(geo: str, root: tk.Tk) -> str:
    try:
        wh, xy = geo.split("+", 1)
        w_s, h_s = wh.split("x", 1)
        x_s, y_s = xy.split("+", 1)
        return clamp_geometry(root, int(w_s), int(h_s), int(x_s), int(y_s))
    except (ValueError, TypeError):
        return clamp_geometry(root, 780, 720, 80, 60)


def place_window_near_parent(
    parent: tk.Misc,
    child: tk.Toplevel,
    *,
    pad: int = 12,
    dy: int = 28,
) -> None:
    """Kindfenster direkt neben dem Elternfenster platzieren (rechts, sonst links)."""
    parent.update_idletasks()
    child.update_idletasks()
    px = int(parent.winfo_rootx())
    py = int(parent.winfo_rooty())
    pw = int(parent.winfo_width())
    ph = int(parent.winfo_height())
    ww = max(int(child.winfo_reqwidth()), int(child.winfo_width()))
    wh = max(int(child.winfo_reqheight()), int(child.winfo_height()))
    sw = int(parent.winfo_screenwidth())
    sh = int(parent.winfo_screenheight())

    x = px + pw + pad
    y = py + dy
    if x + ww > sw - 16:
        x = px - ww - pad
    if x < 8:
        x = min(px + pad, sw - ww - 8)
    if x < 8:
        x = 8
    if y + wh > sh - 24:
        y = max(8, sh - wh - 24)
    if y < 8:
        y = 8
    child.geometry(f"+{x}+{y}")


class IntroCutterApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Intro Cutter")
        self.minsize(520, 440)

        self._settings = load_settings()
        if not isinstance(self._settings.get("intro_outro_presets"), dict):
            self._settings["intro_outro_presets"] = dict(DEFAULT_SETTINGS["intro_outro_presets"])
        self._files: List[Path] = []

        self._build_style()
        self._build_menu_bar()
        self._build_main()

        self.update_idletasks()
        geo = parse_geometry(str(self._settings.get("geometry", "")), self)
        self.geometry(geo)

        self._geo_save_after_id: Any = None
        self.bind("<Configure>", self._on_main_configure)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        if sys.platform == "win32":
            style.theme_use("vista")
        # Kein option_add("*Font", "Segoe UI 10") — Tcl splittet beim Leerzeichen,
        # dann entsteht z. B. TclError: expected integer but got "UI".
        for font_name in ("TkDefaultFont", "TkTextFont", "TkFixedFont", "TkMenuFont"):
            try:
                tkfont.nametofont(font_name).configure(family="Segoe UI", size=10)
            except tk.TclError:
                pass
        try:
            style.configure(".", font=("Segoe UI", 10))
        except tk.TclError:
            pass

    def _build_menu_bar(self) -> None:
        menubar = tk.Menu(self)
        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label="Beenden", command=self._on_close)
        menubar.add_cascade(label="Datei", menu=m_file)
        m_help = tk.Menu(menubar, tearoff=0)
        m_help.add_command(label="Über…", command=self._about)
        menubar.add_cascade(label="Hilfe", menu=m_help)
        self.config(menu=menubar)

    def _about(self) -> None:
        messagebox.showinfo(
            "Intro Cutter",
            "Intro- und Outro-Anteile in Sekunden abschneiden.\n"
            "FFmpeg: freie Codec- und Bitrate-Wahl.\n"
            "DaVinci Resolve Studio: Deliver-Preset steuert Codec und Bitrate.",
        )

    def _on_main_configure(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        if self._geo_save_after_id is not None:
            try:
                self.after_cancel(self._geo_save_after_id)
            except tk.TclError:
                pass
        self._geo_save_after_id = self.after(500, self._save_geometry_only)

    def _save_geometry_only(self) -> None:
        self._geo_save_after_id = None
        try:
            g = self.geometry()
        except tk.TclError:
            return
        self._settings["geometry"] = g
        try:
            disk = load_settings()
        except OSError:
            disk = {}
        merged = {**DEFAULT_SETTINGS, **disk, **self._settings, "geometry": g}
        try:
            save_settings(merged)
        except OSError:
            pass
        self._settings.update(merged)

    def _info_button(self, parent: tk.Widget, title: str, text: str) -> ttk.Button:
        return ttk.Button(
            parent,
            text="(i)",
            width=3,
            command=lambda: messagebox.showinfo(title, text),
        )

    def _build_main(self) -> None:
        pad = {"padx": 8, "pady": 6}
        outer = ttk.Frame(self, padding=10)
        outer.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(6, weight=1)

        top = ttk.Frame(outer)
        top.grid(row=0, column=0, sticky="ew", **pad)
        top.columnconfigure(0, weight=1)
        ttk.Label(top, text="Intro Cutter", font=("Segoe UI", 14)).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(top, text="⚙ Einstellungen", command=self._open_settings).grid(
            row=0, column=1, sticky="e", padx=(12, 0)
        )

        # Dateien
        lf_files = ttk.LabelFrame(outer, text="Dateien", padding=8)
        lf_files.grid(row=1, column=0, sticky="nsew", **pad)
        lf_files.columnconfigure(0, weight=1)
        lf_files.rowconfigure(1, weight=1)

        hint = (
            "Videodateien hierher ziehen"
            if windnd
            else "„Hinzufügen“ nutzen (Drag & Drop: pip install windnd)"
        )
        self._drop_frame = ttk.Frame(lf_files, relief="solid", borderwidth=1, padding=16)
        self._drop_frame.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        ttk.Label(self._drop_frame, text=hint, foreground="#444").pack()

        if windnd:
            try:
                windnd.hook_dropfiles(self._drop_frame, self._on_windnd_drop)  # type: ignore[attr-defined]
            except Exception:
                pass

        list_fr = ttk.Frame(lf_files)
        list_fr.grid(row=1, column=0, columnspan=3, sticky="nsew")
        list_fr.columnconfigure(0, weight=1)
        list_fr.rowconfigure(0, weight=1)
        self._list = tk.Listbox(list_fr, height=5, selectmode=tk.EXTENDED)
        self._list.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(list_fr, orient="vertical", command=self._list.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self._list.configure(yscrollcommand=sb.set)

        bf = ttk.Frame(lf_files)
        bf.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        ttk.Button(bf, text="Hinzufügen…", command=self._add_files_dialog).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(bf, text="Entfernen", command=self._remove_selected).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(bf, text="Liste leeren", command=self._clear_list).pack(side=tk.LEFT)

        # Schnitt
        lf_cut = ttk.LabelFrame(outer, text="Schnitt", padding=8)
        lf_cut.grid(row=2, column=0, sticky="ew", **pad)
        lf_cut.columnconfigure(1, weight=1)

        ttk.Label(lf_cut, text="Intro (Sekunden)").grid(row=0, column=0, sticky="w")
        self._intro_var = tk.StringVar(value=str(self._settings["intro_sec"]))
        ttk.Entry(lf_cut, textvariable=self._intro_var, width=14).grid(
            row=0, column=1, sticky="w", padx=(6, 0)
        )
        self._info_button(
            lf_cut,
            "Intro",
            "So viele Sekunden werden am Anfang des Videos entfernt "
            "(ab dieser Zeit beginnt die Ausgabe).",
        ).grid(row=0, column=2, padx=4)

        ttk.Label(lf_cut, text="Outro (Sekunden)").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self._outro_var = tk.StringVar(value=str(self._settings["outro_sec"]))
        ttk.Entry(lf_cut, textvariable=self._outro_var, width=14).grid(
            row=1, column=1, sticky="w", padx=(6, 0), pady=(8, 0)
        )
        self._info_button(
            lf_cut,
            "Outro",
            "So viele Sekunden werden am Ende des Videos abgeschnitten.",
        ).grid(row=1, column=2, padx=4, pady=(8, 0))

        ttk.Label(lf_cut, text="Preset").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self._intro_outro_preset_var = tk.StringVar(
            value=str(self._settings.get("selected_intro_outro_preset", "Standard"))
        )
        self._preset_combo = ttk.Combobox(
            lf_cut,
            textvariable=self._intro_outro_preset_var,
            state="readonly",
            width=22,
        )
        self._preset_combo.grid(row=2, column=1, sticky="w", padx=(6, 0), pady=(10, 0))
        self._preset_combo.bind("<<ComboboxSelected>>", self._on_intro_outro_preset_selected)
        preset_btns = ttk.Frame(lf_cut)
        preset_btns.grid(row=2, column=2, sticky="w", padx=4, pady=(10, 0))
        ttk.Button(preset_btns, text="Speichern", command=self._save_intro_outro_preset).pack(
            side=tk.LEFT
        )
        ttk.Button(
            preset_btns,
            text="Löschen",
            command=self._delete_intro_outro_preset,
        ).pack(side=tk.LEFT, padx=(6, 0))
        self._info_button(
            lf_cut,
            "Intro/Outro-Presets",
            "Presets speichern Intro/Outro-Zeiten für schnellen Wechsel. "
            "Beim Auswählen werden die Werte direkt übernommen.",
        ).grid(row=2, column=3, padx=4, pady=(10, 0), sticky="w")
        self._refresh_intro_outro_presets()

        # Modus
        lf_mode = ttk.LabelFrame(outer, text="Modus", padding=8)
        lf_mode.grid(row=3, column=0, sticky="ew", **pad)
        self._mode_var = tk.StringVar(value=self._settings["mode"])
        r1 = ttk.Radiobutton(
            lf_mode,
            text="FFmpeg (Codec & Bitrate)",
            variable=self._mode_var,
            value="ffmpeg",
            command=self._toggle_mode_frames,
        )
        r1.grid(row=0, column=0, sticky="w")
        self._info_button(
            lf_mode,
            "FFmpeg",
            "Schneidet direkt mit ffmpeg. Video- und Audio-Codec sowie Bitraten "
            "sind frei wählbar. Kein DaVinci nötig.",
        ).grid(row=0, column=1, padx=4)
        r2 = ttk.Radiobutton(
            lf_mode,
            text="DaVinci Resolve (Deliver-Preset)",
            variable=self._mode_var,
            value="resolve",
            command=self._toggle_mode_frames,
        )
        r2.grid(row=0, column=2, sticky="w", padx=(16, 0))
        self._info_button(
            lf_mode,
            "DaVinci Resolve",
            "Nutzt DaVinci Resolve Studio mit der Skripting-API. "
            "Codec und Bitrate kommen aus dem gewählten Deliver-Preset, nicht aus diesem Tool.",
        ).grid(row=0, column=3, padx=4)

        self._ffmpeg_frame = ttk.LabelFrame(outer, text="FFmpeg-Optionen", padding=8)
        self._ffmpeg_frame.grid(row=4, column=0, sticky="ew", **pad)
        self._build_ffmpeg_options(self._ffmpeg_frame)

        self._resolve_frame = ttk.LabelFrame(outer, text="Resolve", padding=8)
        self._resolve_frame.grid(row=5, column=0, sticky="ew", **pad)
        self._build_resolve_options(self._resolve_frame)

        # Log + Start
        lf_log = ttk.LabelFrame(outer, text="Protokoll", padding=8)
        lf_log.grid(row=6, column=0, sticky="nsew", **pad)
        lf_log.columnconfigure(0, weight=1)
        lf_log.rowconfigure(0, weight=1)
        outer.rowconfigure(6, weight=1)

        self._log = tk.Text(lf_log, height=10, wrap="word", state="disabled", font=("Consolas", 9))
        self._log.grid(row=0, column=0, sticky="nsew")
        lsb = ttk.Scrollbar(lf_log, orient="vertical", command=self._log.yview)
        lsb.grid(row=0, column=1, sticky="ns")
        self._log.configure(yscrollcommand=lsb.set)

        bot = ttk.Frame(outer)
        bot.grid(row=7, column=0, sticky="ew", **pad)
        self._progress = ttk.Progressbar(bot, mode="indeterminate")
        self._progress.pack(side=tk.LEFT, fill="x", expand=True, padx=(0, 8))
        self._start_btn = ttk.Button(bot, text="Start", command=self._on_start)
        self._start_btn.pack(side=tk.RIGHT)

        self._toggle_mode_frames()

    def _build_ffmpeg_options(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        ttk.Label(parent, text="Video-Codec").grid(row=0, column=0, sticky="w")
        vc_saved = (self._settings.get("video_codec") or "").strip()
        codec_values = list(FFMPEG_VIDEO_CODECS)
        if vc_saved and vc_saved not in codec_values:
            codec_values = [vc_saved] + codec_values
        self._vcodec_var = tk.StringVar(
            value=vc_saved if vc_saved in codec_values else FFMPEG_VIDEO_CODECS[0]
        )
        self._vcodec_combo = ttk.Combobox(
            parent,
            textvariable=self._vcodec_var,
            values=codec_values,
            state="readonly",
            width=26,
        )
        self._vcodec_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self._info_button(
            parent,
            "Video-Codec",
            "Vordefinierte ffmpeg-Encoder. „copy“ übernimmt den Videostream ohne Neuencodierung "
            "(Schnitte nur an Keyframes genau).\n"
            "Hardware-Encoder (nvenc) nur mit passender GPU/Treiber.",
        ).grid(row=0, column=2, padx=4)

        ttk.Label(parent, text="Video-Bitrate").grid(row=1, column=0, sticky="nw", pady=(6, 0))
        vbit_fr = ttk.Frame(parent)
        vbit_fr.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))
        vbit_fr.columnconfigure(0, weight=1)
        self._vbit_var = tk.StringVar(value=self._settings["video_bitrate"])
        self._vbit_entry = ttk.Entry(vbit_fr, textvariable=self._vbit_var)
        self._vbit_entry.grid(row=0, column=0, sticky="ew")
        self._vbit_auto_var = tk.BooleanVar(
            value=bool(self._settings.get("video_bitrate_auto", False))
        )
        self._vbit_auto_chk = ttk.Checkbutton(
            vbit_fr,
            text="Automatisch je Datei (ffprobe)",
            variable=self._vbit_auto_var,
            command=self._sync_vbit_widgets,
        )
        self._vbit_auto_chk.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self._info_button(
            parent,
            "Video-Bitrate",
            "Manuell: z. B. 8M oder 5000k.\n\n"
            "Automatisch: Für jede Datei wird die Bitrate mit ffprobe ermittelt "
            "(zuerst Videostream, sonst Format, sonst Schätzung aus Größe und Dauer). "
            "Sinnvoll bei mehreren Clips mit unterschiedlicher Bitrate.",
        ).grid(row=1, column=2, padx=4, pady=(6, 0), sticky="nw")

        self._vcodec_var.trace_add("write", lambda *_: self._sync_vbit_widgets())
        self._vbit_auto_var.trace_add("write", lambda *_: self._sync_vbit_widgets())
        self._sync_vbit_widgets()

        ttk.Label(parent, text="Audio-Codec").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self._acodec_var = tk.StringVar(value=self._settings["audio_codec"])
        ttk.Entry(parent, textvariable=self._acodec_var).grid(
            row=2, column=1, sticky="ew", padx=(8, 0), pady=(6, 0)
        )
        self._info_button(
            parent,
            "Audio-Codec",
            "z. B. aac oder copy.",
        ).grid(row=2, column=2, padx=4, pady=(6, 0))

        ttk.Label(parent, text="Audio-Bitrate").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self._abit_var = tk.StringVar(value=self._settings["audio_bitrate"])
        ttk.Entry(parent, textvariable=self._abit_var).grid(
            row=3, column=1, sticky="ew", padx=(8, 0), pady=(6, 0)
        )
        self._info_button(
            parent,
            "Audio-Bitrate",
            "z. B. 192k. Bei „copy“ nicht relevant.",
        ).grid(row=3, column=2, padx=4, pady=(6, 0))

    def _sync_vbit_widgets(self, *_args: object) -> None:
        copy_mode = self._vcodec_var.get().strip().lower() == "copy"
        auto = bool(self._vbit_auto_var.get())
        if copy_mode:
            try:
                self._vbit_auto_chk.state(["disabled"])
            except tk.TclError:
                pass
            self._vbit_entry.configure(state=tk.DISABLED)
            return
        try:
            self._vbit_auto_chk.state(["!disabled"])
        except tk.TclError:
            pass
        if auto:
            self._vbit_entry.configure(state=tk.DISABLED)
        else:
            self._vbit_entry.configure(state=tk.NORMAL)

    def _build_resolve_options(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        ttk.Label(parent, text="Deliver-Preset").grid(row=0, column=0, sticky="w")
        self._preset_var = tk.StringVar(value=self._settings["render_preset"])
        ttk.Entry(parent, textvariable=self._preset_var).grid(
            row=0, column=1, sticky="ew", padx=(8, 0)
        )
        self._info_button(
            parent,
            "Deliver-Preset",
            "Exakt der Name aus der Deliver-Seite in Resolve (Groß-/Kleinschreibung beachten). "
            "Leer lassen für die Fallback-Kette im Skript.",
        ).grid(row=0, column=2, padx=4)

    def _preset_map(self) -> Dict[str, Dict[str, float]]:
        raw = self._settings.get("intro_outro_presets")
        if not isinstance(raw, dict):
            raw = {}
        out: Dict[str, Dict[str, float]] = {}
        for name, vals in raw.items():
            if not isinstance(name, str) or not isinstance(vals, dict):
                continue
            try:
                intro = float(vals.get("intro_sec", 0.0))
                outro = float(vals.get("outro_sec", 0.0))
            except (TypeError, ValueError):
                continue
            out[name] = {"intro_sec": max(0.0, intro), "outro_sec": max(0.0, outro)}
        if not out:
            out = dict(DEFAULT_SETTINGS["intro_outro_presets"])
        self._settings["intro_outro_presets"] = out
        return out

    def _refresh_intro_outro_presets(self) -> None:
        presets = self._preset_map()
        names = sorted(presets.keys(), key=str.lower)
        self._preset_combo.configure(values=names)
        current = self._intro_outro_preset_var.get().strip()
        if current not in presets:
            current = names[0]
            self._intro_outro_preset_var.set(current)
        self._settings["selected_intro_outro_preset"] = current

    def _apply_intro_outro_preset(self, name: str) -> None:
        presets = self._preset_map()
        if name not in presets:
            return
        p = presets[name]
        self._intro_var.set(str(p["intro_sec"]))
        self._outro_var.set(str(p["outro_sec"]))
        self._settings["selected_intro_outro_preset"] = name

    def _on_intro_outro_preset_selected(self, _event: tk.Event) -> None:
        self._apply_intro_outro_preset(self._intro_outro_preset_var.get().strip())

    def _save_intro_outro_preset(self) -> None:
        try:
            intro = float(str(self._intro_var.get()).replace(",", "."))
            outro = float(str(self._outro_var.get()).replace(",", "."))
        except ValueError:
            messagebox.showwarning("Preset", "Intro und Outro müssen Zahlen sein.")
            return
        if intro < 0 or outro < 0:
            messagebox.showwarning("Preset", "Intro und Outro dürfen nicht negativ sein.")
            return

        name = simpledialog.askstring(
            "Preset speichern",
            "Name für Intro/Outro-Preset:",
            parent=self,
            initialvalue=self._intro_outro_preset_var.get().strip() or "",
        )
        if name is None:
            return
        name = name.strip()
        if not name:
            messagebox.showwarning("Preset", "Bitte einen Namen eingeben.")
            return
        presets = self._preset_map()
        presets[name] = {"intro_sec": intro, "outro_sec": outro}
        self._settings["intro_outro_presets"] = presets
        self._intro_outro_preset_var.set(name)
        self._settings["selected_intro_outro_preset"] = name
        self._refresh_intro_outro_presets()
        self._persist()

    def _delete_intro_outro_preset(self) -> None:
        name = self._intro_outro_preset_var.get().strip()
        presets = self._preset_map()
        if name not in presets:
            return
        if not messagebox.askyesno("Preset löschen", f"Preset '{name}' wirklich löschen?"):
            return
        del presets[name]
        if not presets:
            presets = dict(DEFAULT_SETTINGS["intro_outro_presets"])
        self._settings["intro_outro_presets"] = presets
        self._refresh_intro_outro_presets()
        current = self._intro_outro_preset_var.get().strip()
        self._apply_intro_outro_preset(current)
        self._persist()

    def _toggle_mode_frames(self) -> None:
        if self._mode_var.get() == "ffmpeg":
            self._ffmpeg_frame.grid()
            self._resolve_frame.grid_remove()
        else:
            self._ffmpeg_frame.grid_remove()
            self._resolve_frame.grid()

    def _on_windnd_drop(self, paths: Any) -> None:
        normalized: List[str] = []
        for p in paths or []:
            if isinstance(p, bytes):
                for enc in ("utf-8", sys.getfilesystemencoding() or "mbcs", "cp1252"):
                    try:
                        normalized.append(p.decode(enc))
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    normalized.append(p.decode("utf-8", errors="replace"))
            else:
                normalized.append(str(p))
        self._add_paths([Path(x) for x in normalized])

    def _add_paths(self, paths: List[Path]) -> None:
        for p in paths:
            try:
                r = p.expanduser().resolve()
            except OSError:
                continue
            if not r.is_file():
                continue
            if r.suffix.lower() not in VIDEO_EXT:
                continue
            if r not in self._files:
                self._files.append(r)
                self._list.insert(tk.END, str(r))
        if paths:
            self._log_line(f"{len(paths)} Datei(en) zur Liste hinzugefügt.")

    def _add_files_dialog(self) -> None:
        files = filedialog.askopenfilenames(
            title="Videos auswählen",
            filetypes=[
                ("Video", "*.mp4 *.mkv *.mov *.m4v *.avi *.webm"),
                ("Alle", "*.*"),
            ],
        )
        if files:
            self._add_paths([Path(f) for f in files])

    def _remove_selected(self) -> None:
        sel = list(self._list.curselection())
        if not sel:
            return
        for i in reversed(sel):
            self._list.delete(i)
            del self._files[i]

    def _clear_list(self) -> None:
        self._list.delete(0, tk.END)
        self._files.clear()

    def _log_line(self, msg: str) -> None:
        self._log.configure(state="normal")
        self._log.insert(tk.END, msg + "\n")
        self._log.see(tk.END)
        self._log.configure(state="disabled")

    def _collect_ui_settings(self) -> Dict[str, Any]:
        return {
            "geometry": self.geometry(),
            "intro_sec": float(str(self._intro_var.get()).replace(",", ".")),
            "outro_sec": float(str(self._outro_var.get()).replace(",", ".")),
            "mode": self._mode_var.get(),
            "video_codec": self._vcodec_var.get().strip(),
            "video_bitrate": self._vbit_var.get().strip(),
            "video_bitrate_auto": bool(self._vbit_auto_var.get()),
            "audio_codec": self._acodec_var.get().strip(),
            "audio_bitrate": self._abit_var.get().strip(),
            "render_preset": self._preset_var.get().strip(),
            "resolve_exe": self._settings.get("resolve_exe", ""),
            "fusionscript_dll": self._settings.get("fusionscript_dll", ""),
            "scripting_modules": self._settings.get("scripting_modules", ""),
            "output_dir": self._settings.get("output_dir", ""),
            "intro_outro_presets": self._preset_map(),
            "selected_intro_outro_preset": self._intro_outro_preset_var.get().strip(),
        }

    def _on_start(self) -> None:
        if not self._files:
            messagebox.showwarning("Dateien", "Bitte mindestens eine Videodatei hinzufügen.")
            return
        try:
            intro = float(str(self._intro_var.get()).replace(",", "."))
            outro = float(str(self._outro_var.get()).replace(",", "."))
        except ValueError:
            messagebox.showwarning("Eingabe", "Intro und Outro müssen Zahlen sein.")
            return
        if intro < 0 or outro < 0:
            messagebox.showwarning("Eingabe", "Intro und Outro dürfen nicht negativ sein.")
            return

        vcodec = self._vcodec_var.get().strip()
        vbit_auto = bool(self._vbit_auto_var.get())
        vbit = self._vbit_var.get().strip()
        if self._mode_var.get() == "ffmpeg" and vcodec.lower() != "copy":
            if not vbit_auto and not vbit:
                messagebox.showwarning(
                    "Video-Bitrate",
                    "Bitte eine manuelle Bitrate eingeben oder „Automatisch je Datei“ aktivieren.",
                )
                return

        out_custom = (self._settings.get("output_dir") or "").strip()
        if out_custom:
            try:
                Path(out_custom).expanduser().resolve().mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showwarning(
                    "Ausgabe-Ordner",
                    f"Ausgabe-Ordner kann nicht angelegt oder nicht verwendet werden:\n{exc}",
                )
                return

        self._start_btn.configure(state="disabled")
        self._progress.start(12)
        snap = {
            "mode": self._mode_var.get(),
            "vcodec": vcodec,
            "vbit": vbit,
            "vbit_auto": vbit_auto,
            "acodec": self._acodec_var.get().strip(),
            "abit": self._abit_var.get().strip(),
            "preset": self._preset_var.get().strip(),
            "output_dir": out_custom,
        }
        threading.Thread(
            target=self._worker,
            args=(intro, outro, snap),
            daemon=True,
        ).start()

    def _worker(self, intro: float, outro: float, snap: Dict[str, Any]) -> None:
        mode = snap["mode"]
        try:
            for src in list(self._files):
                self.after(0, lambda s=src: self._log_line(f"--- {s.name} ---"))
                if mode == "ffmpeg":
                    self._run_ffmpeg_one(src, intro, outro, snap)
                else:
                    self._run_resolve_one(src, intro, outro, snap)
            self.after(0, lambda: self._log_line("Fertig."))
            self.after(0, lambda: messagebox.showinfo("Fertig", "Alle Aufträge abgeschlossen."))
        except Exception as exc:
            self.after(
                0,
                lambda e=exc: messagebox.showerror("Fehler", str(e)),
            )
            self.after(0, lambda e=exc: self._log_line(f"FEHLER: {e}"))
        finally:
            self.after(0, self._job_done)

    def _run_ffmpeg_one(
        self, src: Path, intro: float, outro: float, snap: Dict[str, Any]
    ) -> None:
        def log(msg: str) -> None:
            self.after(0, lambda m=msg: self._log_line(m))

        out = run_ffmpeg_cut(
            src,
            intro,
            outro,
            snap["vcodec"],
            snap["vbit"],
            snap["acodec"],
            snap["abit"],
            video_bitrate_auto=snap["vbit_auto"],
            output_dir=snap["output_dir"] or None,
            log=log,
        )
        self.after(0, lambda o=out: self._log_line(f"Gespeichert: {o}"))

    def _run_resolve_one(
        self, src: Path, intro: float, outro: float, snap: Dict[str, Any]
    ) -> None:
        env = os.environ.copy()
        exe = (self._settings.get("resolve_exe") or "").strip()
        dll = (self._settings.get("fusionscript_dll") or "").strip()
        mods = (self._settings.get("scripting_modules") or "").strip()
        if exe:
            env["INTRO_CUTTER_RESOLVE_EXE"] = exe
        if dll:
            env["INTRO_CUTTER_FUSIONSCRIPT_DLL"] = dll
        if mods:
            env["INTRO_CUTTER_SCRIPTING_MODULES"] = mods

        preset = snap["preset"]
        cmd = [
            sys.executable,
            str(ROOT / "intro_cut_resolve.py"),
            "--input",
            str(src),
            "--intro",
            str(intro),
            "--outro",
            str(outro),
        ]
        if preset:
            cmd += ["--preset", preset]
        od = (snap.get("output_dir") or "").strip()
        if od:
            cmd += ["--output-dir", str(Path(od).expanduser().resolve())]

        self.after(0, lambda: self._log_line("Resolve-Job startet…"))
        p = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(ROOT),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if p.stdout:
            for line in p.stdout.splitlines():
                self.after(0, lambda ln=line: self._log_line(ln))
        if p.returncode != 0:
            err = (p.stderr or "").strip() or p.stdout or "Unbekannter Fehler"
            raise RuntimeError(err[:8000])

    def _job_done(self) -> None:
        self._progress.stop()
        self._start_btn.configure(state="normal")
        self._persist()

    def _persist(self) -> None:
        geo = self.geometry()
        try:
            s = self._collect_ui_settings()
        except ValueError:
            s = {}
        merged = {**DEFAULT_SETTINGS, **self._settings, **s, "geometry": geo}
        save_settings(merged)
        self._settings.update(merged)

    def _on_close(self) -> None:
        if self._geo_save_after_id is not None:
            try:
                self.after_cancel(self._geo_save_after_id)
            except tk.TclError:
                pass
            self._geo_save_after_id = None
        self._persist()
        self.destroy()

    def _open_settings(self) -> None:
        win = tk.Toplevel(self)
        win.title("Einstellungen")
        win.transient(self)
        win.columnconfigure(1, weight=1)

        pad = {"padx": 8, "pady": 6}
        ttk.Label(
            win,
            text="Ausgabe und optionale DaVinci-Pfade.",
            wraplength=520,
        ).grid(row=0, column=0, columnspan=4, sticky="w", **pad)

        def row_browse(r: int, label: str, var: tk.StringVar, is_dir: bool, info_title: str, info_text: str):
            ttk.Label(win, text=label).grid(row=r, column=0, sticky="nw", **pad)

            def browse():
                if is_dir:
                    d = filedialog.askdirectory(title=label)
                    if d:
                        var.set(d)
                else:
                    d = filedialog.askopenfilename(
                        title=label,
                        filetypes=[("Datei", "*.*")],
                    )
                    if d:
                        var.set(d)

            e = ttk.Entry(win, textvariable=var, width=52)
            e.grid(row=r, column=1, sticky="ew", **pad)
            ttk.Button(win, text="Durchsuchen…", command=browse).grid(row=r, column=2, **pad)
            self._info_button(win, info_title, info_text).grid(row=r, column=3, **pad)

        v_out = tk.StringVar(value=self._settings.get("output_dir", ""))
        v_exe = tk.StringVar(value=self._settings.get("resolve_exe", ""))
        v_dll = tk.StringVar(value=self._settings.get("fusionscript_dll", ""))
        v_mod = tk.StringVar(value=self._settings.get("scripting_modules", ""))

        row_browse(
            1,
            "Ausgabe-Ordner",
            v_out,
            True,
            "Ausgabe-Ordner",
            "Ordner für fertige Videos (FFmpeg und Resolve).\n"
            "Leer lassen: Dateien landen im gleichen Ordner wie die jeweilige Quelldatei.\n"
            "Wenn gesetzt, wird der Ordner bei Bedarf angelegt.",
        )
        row_browse(
            2,
            "Resolve.exe",
            v_exe,
            False,
            "Resolve.exe",
            "Vollständiger Pfad zu Resolve.exe der gewünschten Installation.\n"
            "Wird u. a. genutzt, wenn Resolve noch nicht läuft und gestartet werden soll.\n"
            "Leer lassen für automatische Suche.",
        )
        row_browse(
            3,
            "fusionscript.dll",
            v_dll,
            False,
            "fusionscript.dll",
            "Liegt im Installationsordner von DaVinci Resolve (Fusion-Scripting).\n"
            "Muss exakt zur laufenden Resolve-Version passen.\n"
            "Wenn gesetzt, wird die automatische Erkennung über die laufende EXE deaktiviert.",
        )
        row_browse(
            4,
            "Scripting-Module",
            v_mod,
            True,
            "Scripting-Module",
            "Ordner, der die Datei DaVinciResolveScript.py enthält "
            "(z. B. …\\Support\\Developer\\Scripting\\Modules).\n"
            "Entspricht RESOLVE_SCRIPT_API / den Blackmagic-Modulen.\n"
            "Wenn gesetzt, wird die automatische Erkennung über die laufende EXE deaktiviert.",
        )

        def save_and_close():
            self._settings["output_dir"] = v_out.get().strip()
            self._settings["resolve_exe"] = v_exe.get().strip()
            self._settings["fusionscript_dll"] = v_dll.get().strip()
            self._settings["scripting_modules"] = v_mod.get().strip()
            try:
                merged = self._collect_ui_settings()
            except ValueError:
                merged = {**DEFAULT_SETTINGS, **self._settings}
            merged["output_dir"] = self._settings["output_dir"]
            merged["resolve_exe"] = self._settings["resolve_exe"]
            merged["fusionscript_dll"] = self._settings["fusionscript_dll"]
            merged["scripting_modules"] = self._settings["scripting_modules"]
            merged["geometry"] = self.geometry()
            save_settings(merged)
            self._settings.update(merged)
            win.destroy()

        bf = ttk.Frame(win)
        bf.grid(row=5, column=0, columnspan=4, sticky="e", **pad)
        ttk.Button(bf, text="Abbrechen", command=win.destroy).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(bf, text="Speichern", command=save_and_close).pack(side=tk.RIGHT)

        win.update_idletasks()
        place_window_near_parent(self, win)
        win.grab_set()


def main() -> None:
    app = IntroCutterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
