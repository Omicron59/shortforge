"""Outils communs pour lancer FFmpeg, ffprobe et les moteurs locaux (voix, transcription).

Sous Windows, les processus sont lances sans ouvrir de fenetre de console (application de bureau).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from shortforge.config import Settings

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


class MediaToolError(RuntimeError):
    """Outil externe absent ou en echec ; le message est destine a l'utilisateur."""


def run(cmd: list[str], *, cwd: Path | None = None, timeout_s: float = 1800, input_text: str | None = None,
        what: str = "La commande") -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout_s, check=False,
                                input=input_text, creationflags=NO_WINDOW, encoding="utf-8", errors="replace")
    except FileNotFoundError as exc:
        raise MediaToolError(f"{what} : programme introuvable ({cmd[0]}).") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaToolError(f"{what} a pris trop de temps : abandon.") from exc
    if result.returncode != 0:
        tail = "\n".join((result.stderr or result.stdout).strip().splitlines()[-6:])
        raise MediaToolError(f"{what} a échoué :\n{tail}")
    return result


def ffmpeg_path(settings: Settings) -> str:
    found = shutil.which(settings.ffmpeg_path)
    if not found:
        hint = "brew install ffmpeg" if sys.platform == "darwin" else "winget install Gyan.FFmpeg"
        raise MediaToolError(f"FFmpeg introuvable : installe-le ({hint}) ou renseigne FFMPEG_PATH.")
    return found


def ffprobe_path(settings: Settings) -> str:
    ffmpeg = Path(ffmpeg_path(settings))
    sibling = ffmpeg.with_name(ffmpeg.name.replace("ffmpeg", "ffprobe"))
    if sibling.is_file():
        return str(sibling)
    found = shutil.which("ffprobe")
    if not found:
        raise MediaToolError("ffprobe introuvable (il est fourni avec FFmpeg).")
    return found


def probe_json(settings: Settings, path: Path) -> dict[str, Any]:
    out = run([ffprobe_path(settings), "-v", "error", "-show_entries",
               "stream=codec_type,codec_name,width,height,pix_fmt:format=duration,size", "-of", "json", str(path)],
              timeout_s=120, what="L'analyse du fichier")
    data: dict[str, Any] = json.loads(out.stdout or "{}")
    return data


def duration_of(settings: Settings, path: Path) -> float:
    return round(float(probe_json(settings, path).get("format", {}).get("duration", 0) or 0), 3)


def to_wav(settings: Settings, source: Path, dest: Path) -> Path:
    """Convertit un fichier audio en WAV 48 kHz stereo (format commun du montage)."""
    run([ffmpeg_path(settings), "-hide_banner", "-y", "-i", str(source), "-ar", "48000", "-ac", "2", str(dest)],
        timeout_s=300, what="La conversion audio")
    return dest
