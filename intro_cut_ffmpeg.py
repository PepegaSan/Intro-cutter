"""FFmpeg: Intro/Outro in Sekunden schneiden (genutzt von GUI und optional CLI)."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional


LogFn = Optional[Callable[[str], None]]


def _log(fn: LogFn, msg: str) -> None:
    if fn:
        fn(msg)


def _which(name: str) -> Optional[str]:
    return shutil.which(name)


def ffprobe_duration_sec(path: Path, log: LogFn = None) -> float:
    exe = _which("ffprobe")
    if not exe:
        raise RuntimeError("ffprobe nicht im PATH. FFmpeg installieren und PATH setzen.")
    try:
        out = subprocess.check_output(
            [
                exe,
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


def _ffprobe_text(
    path: Path,
    *,
    select_streams: Optional[str],
    show_entries: str,
) -> str:
    exe = _which("ffprobe")
    if not exe:
        raise RuntimeError("ffprobe nicht im PATH.")
    cmd = [exe, "-v", "error"]
    if select_streams:
        cmd.extend(["-select_streams", select_streams])
    cmd.extend(
        [
            "-show_entries",
            show_entries,
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    try:
        out = subprocess.check_output(
            cmd,
            stderr=subprocess.STDOUT,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"ffprobe fehlgeschlagen: {exc}") from exc
    return out.decode("utf-8", errors="replace").strip()


def _parse_bitrate_field(text: str) -> Optional[int]:
    line = (text or "").strip().split("\n", 1)[0].strip()
    if not line or line.upper() == "N/A":
        return None
    try:
        v = int(float(line))
    except ValueError:
        return None
    return v if v > 1000 else None


def ffprobe_video_bitrate_bps(path: Path, log: LogFn = None) -> Optional[int]:
    """Video-Bitrate in Bit/s (ffprobe), sonst Container-Bitrate, sonst Schätzung."""
    # 1) Videostream nominal
    try:
        raw = _ffprobe_text(path, select_streams="v:0", show_entries="stream=bit_rate")
        b = _parse_bitrate_field(raw)
        if b:
            _log(log, f"Video-Bitrate (Stream): {b} bit/s (~{b / 1_000_000:.2f} Mbit/s)")
            return b
    except RuntimeError:
        pass

    # 2) Container / Datei (kann Audio enthalten — Hinweis im Log)
    try:
        raw = _ffprobe_text(path, select_streams=None, show_entries="format=bit_rate")
        b = _parse_bitrate_field(raw)
        if b:
            _log(
                log,
                f"Video-Bitrate (Format gesamt, ggf. mit Audio): {b} bit/s "
                f"(~{b / 1_000_000:.2f} Mbit/s)",
            )
            return b
    except RuntimeError:
        pass

    # 3) Schätzung aus Dateigröße und Dauer (gesamte Datei)
    try:
        dur = ffprobe_duration_sec(path, log)
        raw = _ffprobe_text(path, select_streams=None, show_entries="format=size")
        size = _parse_bitrate_field(raw)
        if size and dur > 0.01:
            est = int((size * 8) / dur)
            if est > 10_000:
                _log(
                    log,
                    f"Video-Bitrate geschätzt aus Dateigröße/Dauer: {est} bit/s "
                    f"(~{est / 1_000_000:.2f} Mbit/s) — prüfen, ob sinnvoll.",
                )
                return est
    except (RuntimeError, ValueError, ZeroDivisionError):
        pass

    return None


def has_audio_stream(path: Path) -> bool:
    exe = _which("ffprobe")
    if not exe:
        return False
    try:
        subprocess.check_call(
            [
                exe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                str(path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def resolve_output_directory(custom_dir: Optional[str], src: Path) -> Path:
    """Leerer Pfad → Ordner der Quelldatei; sonst Zielordner (wird bei Bedarf angelegt)."""
    if not (custom_dir or "").strip():
        return src.parent
    out = Path(str(custom_dir).strip()).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    return out


def output_extension(video_codec: str, src_path: Path) -> str:
    if video_codec.strip().lower() == "copy":
        return src_path.suffix or ".mp4"
    c = video_codec.lower()
    if "vp9" in c or "vpx" in c:
        return ".webm"
    if "av1" in c or "svtav1" in c or "aom" in c:
        return ".mkv"
    return ".mp4"


def run_ffmpeg_cut(
    src: Path,
    intro_sec: float,
    outro_sec: float,
    video_codec: str,
    video_bitrate: str,
    audio_codec: str,
    audio_bitrate: str,
    *,
    video_bitrate_auto: bool = False,
    output_dir: Optional[str] = None,
    log: LogFn = None,
) -> Path:
    if intro_sec < 0 or outro_sec < 0:
        raise ValueError("Intro und Outro muessen >= 0 sein.")
    ffmpeg = _which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg nicht im PATH.")

    dur = ffprobe_duration_sec(src, log)
    new_dur = dur - intro_sec - outro_sec
    if new_dur <= 0:
        raise RuntimeError(
            f"Ergebnis zu kurz: Gesamtdauer {dur:.3f}s, Intro {intro_sec}s, Outro {outro_sec}s."
        )

    ext = output_extension(video_codec, src)
    out_base = resolve_output_directory(output_dir, src)
    out_path = out_base / f"{src.stem}_introcut{ext}"

    _log(log, f"Quelle: {src}")
    _log(
        log,
        f"Dauer: {dur:.3f}s → neu {new_dur:.3f}s (Intro {intro_sec}s, Outro {outro_sec}s)",
    )
    _log(log, f"Ziel: {out_path}")

    v_codec = video_codec.strip()
    if v_codec.lower() == "copy":
        v_args = ["-c:v", "copy"]
    else:
        if video_bitrate_auto:
            bps = ffprobe_video_bitrate_bps(src, log)
            if not bps:
                raise RuntimeError(
                    "Automatische Video-Bitrate: ffprobe liefert keine nutzbare Rate "
                    "(und Schätzung fehlgeschlagen). Bitte manuelle Bitrate wählen."
                )
            v_args = ["-c:v", v_codec, "-b:v", str(bps)]
        else:
            if not (video_bitrate or "").strip():
                raise RuntimeError(
                    "Video-Bitrate fehlt (oder Automatisch bzw. Codec 'copy' waehlen)."
                )
            v_args = ["-c:v", v_codec, "-b:v", video_bitrate.strip()]

    has_audio = has_audio_stream(src)
    if has_audio:
        a_codec = audio_codec.strip()
        if a_codec.lower() == "copy":
            a_args = ["-map", "0:a:0", "-c:a", "copy"]
        else:
            a_args = ["-map", "0:a:0", "-c:a", a_codec, "-b:a", audio_bitrate.strip()]
    else:
        a_args = ["-an"]

    mov = []
    if ext.lower() in (".mp4", ".m4v", ".mov"):
        mov = ["-movflags", "+faststart"]

    args = [
        ffmpeg,
        "-hide_banner",
        "-y",
        "-i",
        str(src),
        "-ss",
        str(intro_sec).replace(",", "."),
        "-t",
        str(new_dur).replace(",", "."),
        "-map",
        "0:v:0",
    ] + a_args + v_args + mov + [str(out_path)]

    p = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if p.returncode != 0:
        err = (p.stderr or p.stdout or "").strip()
        raise RuntimeError(f"ffmpeg Fehler (Code {p.returncode}):\n{err[:4000]}")

    return out_path
