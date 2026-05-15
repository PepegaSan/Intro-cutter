#!/usr/bin/env python3
"""Intro/Outro über DaVinci Resolve Studio schneiden und per Render-Preset ausgeben.

Bitrate und Codec steuert ihr in Resolve im gewählten Deliver-Preset — die API
erlaubt hier nur Zielordner, Dateiname und Preset-Auswahl (siehe davinci_api).

Optionale Pfade (Umgebungsvariablen, z. B. von der GUI gesetzt):
  INTRO_CUTTER_RESOLVE_EXE          — Resolve.exe
  INTRO_CUTTER_FUSIONSCRIPT_DLL     — fusionscript.dll
  INTRO_CUTTER_SCRIPTING_MODULES   — Ordner mit DaVinciResolveScript
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API_DIR = ROOT
if not (API_DIR / "davinci_api.py").is_file():
    print(
        "Error: davinci_api.py must be in the project folder "
        f"({API_DIR}).",
        file=sys.stderr,
    )
    sys.exit(2)
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

import davinci_api as da  # noqa: E402


def _norm_uniq_front(value: str, candidates: tuple) -> tuple:
    value = os.path.abspath(os.path.normpath(value.strip().strip('"')))
    rest = tuple(
        x for x in candidates if os.path.normpath(x).lower() != value.lower()
    )
    return (value,) + rest


def apply_intro_cutter_path_overrides() -> None:
    """Vor connect_resolve/bootstrap: benutzerdefinierte Installationspfade setzen."""
    exe = os.environ.get("INTRO_CUTTER_RESOLVE_EXE", "").strip().strip('"')
    dll = os.environ.get("INTRO_CUTTER_FUSIONSCRIPT_DLL", "").strip().strip('"')
    mods = os.environ.get("INTRO_CUTTER_SCRIPTING_MODULES", "").strip().strip('"')

    if exe:
        da._RESOLVE_EXE_CANDIDATES = _norm_uniq_front(exe, da._RESOLVE_EXE_CANDIDATES)  # type: ignore[attr-defined]
    if dll:
        da._RESOLVE_LIB_CANDIDATES = _norm_uniq_front(dll, da._RESOLVE_LIB_CANDIDATES)  # type: ignore[attr-defined]
    if mods:
        da._RESOLVE_MODULE_DIRS = _norm_uniq_front(mods, da._RESOLVE_MODULE_DIRS)  # type: ignore[attr-defined]

    # Laufende Resolve-EXE darf eigene DLL bevorzugen — bei manueller DLL/Modul-Angabe abschalten
    if dll or mods:
        da.running_resolve_dir = lambda: None  # type: ignore[assignment]


apply_intro_cutter_path_overrides()


def _ffprobe_duration_sec(path: Path) -> float:
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            stderr=subprocess.STDOUT,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"ffprobe fehlgeschlagen: {exc}") from exc
    text = out.decode("utf-8", errors="replace").strip()
    try:
        return float(text.replace(",", "."))
    except ValueError as exc:
        raise RuntimeError(f"Ungültige Dauer von ffprobe: {text!r}") from exc


def _parse_fps_float(fps_raw: object) -> float:
    s = str(fps_raw or "25").strip().replace(",", ".")
    try:
        return float(s.split()[0])
    except (ValueError, IndexError):
        return 25.0


def _clip_duration_sec(clip: object, fps_raw: object, fallback_file: Path) -> float:
    fps = _parse_fps_float(fps_raw)
    frames_prop = clip.GetClipProperty("Frames")
    if frames_prop not in (None, ""):
        try:
            n = int(frames_prop)
            if n > 0 and fps > 0:
                return n / fps
        except (TypeError, ValueError):
            pass
    fp = clip.GetClipProperty("File Path")
    path = Path(str(fp)) if fp else fallback_file
    return _ffprobe_duration_sec(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Intro/Outro per Resolve subclip + Render-Preset exportieren."
    )
    parser.add_argument("--input", required=True, help="Quell-Videodatei")
    parser.add_argument("--intro", type=float, default=0.0, help="Sekunden am Anfang entfernen")
    parser.add_argument("--outro", type=float, default=0.0, help="Sekunden am Ende entfernen")
    parser.add_argument(
        "--preset",
        default=None,
        help="Name des Deliver-Presets in Resolve (exakt, case-sensitiv)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Ausgabeordner (Standard: Ordner der Quelldatei)",
    )
    parser.add_argument(
        "--output-name",
        default=None,
        help="Dateiname ohne Endung (Standard: <name>_resolve_cut)",
    )
    parser.add_argument(
        "--timeline-prefix",
        default="IntroCut_",
        help="Nur Timelines mit diesem Namenspräfix werden vorher gelöscht",
    )
    args = parser.parse_args()

    src = Path(args.input).expanduser().resolve()
    if not src.is_file():
        print(f"Datei nicht gefunden: {src}", file=sys.stderr)
        return 1

    if args.intro < 0 or args.outro < 0:
        print("Intro und Outro müssen >= 0 sein.", file=sys.stderr)
        return 1

    out_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else src.parent
    out_name = args.output_name or f"{src.stem}_resolve_cut"

    def log(msg: str) -> None:
        print(f"[Resolve] {msg}")

    try:
        with da.scripting_thread():
            _resolve, project, media_pool, _root = da.connect_resolve(
                status_callback=log,
                auto_launch=True,
            )
            clips = media_pool.ImportMedia([da.to_forward(str(src))])
            if not clips:
                print("ImportMedia lieferte keine Clips.", file=sys.stderr)
                return 1
            clip = clips[0]
            time.sleep(da.APPEND_SUBCLIP_SLEEP_AFTER_IMPORT_SEC)

            fps_raw = clip.GetClipProperty("FPS") or "25"
            res_raw = clip.GetClipProperty("Resolution") or "1920x1080"
            total_sec = _clip_duration_sec(clip, fps_raw, src)
            t0 = float(args.intro)
            t1 = total_sec - float(args.outro)
            if t1 - t0 <= 0:
                print(
                    f"Bereich ungültig: Dauer {total_sec:.3f}s, Intro {args.intro}s, "
                    f"Outro {args.outro}s.",
                    file=sys.stderr,
                )
                return 1

            fps = _parse_fps_float(fps_raw)
            start_i = round(t0 * fps)
            duration_frames = max(1, round((t1 - t0) * fps))
            last_i = start_i + duration_frames - 1

            frames_prop = clip.GetClipProperty("Frames")
            if frames_prop not in (None, ""):
                try:
                    tf = int(frames_prop)
                    last_i = min(last_i, max(0, tf - 1))
                    start_i = min(start_i, last_i)
                except (TypeError, ValueError):
                    pass

            sub = da.append_dict_for_subclip(clip, start_i, last_i)
            if sub is None:
                print("Subclip-Bereich leer (start/end).", file=sys.stderr)
                return 1

            da.cleanup_timelines(project, media_pool, name_prefix=args.timeline_prefix)
            da.apply_project_timeline_settings(project, fps_raw, res_raw)

            timeline = media_pool.CreateEmptyTimeline(f"{args.timeline_prefix}{int(time.time())}")
            if not timeline:
                print("Timeline konnte nicht angelegt werden.", file=sys.stderr)
                return 1
            project.SetCurrentTimeline(timeline)
            media_pool.AppendToTimeline([sub])

            preset = args.preset
            known = da.list_render_presets(project)
            if preset and known and preset not in known:
                log(
                    f"Hinweis: Preset {preset!r} nicht in der gelieferten Liste — "
                    "Resolve versucht es trotzdem (Fallback-Kette aktiv)."
                )

            da.render_with_preset(
                project,
                output_dir=str(out_dir),
                output_name=out_name,
                preset_name=preset,
                status_callback=log,
            )
    except da.ResolveError as err:
        print(str(err), file=sys.stderr)
        return 1
    except RuntimeError as err:
        print(str(err), file=sys.stderr)
        return 1

    print(json.dumps({"ok": True, "outputDir": str(out_dir), "outputBase": out_name}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
