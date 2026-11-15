"""Controle qualite du rendu, image par image et seconde par seconde, avec une note sur 10.

FFmpeg analyse chaque image (passages noirs, image figee) et le son (silences, volume
integre en LUFS). La note sert a la verification finale avant publication.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from shortforge.config import Settings
from shortforge.media import MediaToolError, ffmpeg_path, run

TARGET_LUFS = (-20.0, -9.0)  # plage acceptable pour les plateformes de Shorts (~ -14 LUFS)


def _filters(expect_speech: bool) -> tuple[str, str]:
    video = "blackdetect=d=0.4:pix_th=0.10,freezedetect=n=0.003:d=2"
    audio = "ebur128=peak=true"
    if expect_speech:
        audio = "silencedetect=n=-45dB:d=1.5," + audio
    return video, audio


def parse_report(stderr: str) -> dict[str, Any]:
    black = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", stderr)]
    freezes = [float(d) for d in re.findall(r"freeze_duration: ([\d.]+)", stderr)]
    silences = [float(d) for d in re.findall(r"silence_duration: ([\d.]+)", stderr)]
    lufs_match = re.findall(r"I:\s+(-?[\d.]+) LUFS", stderr)
    peak_match = re.findall(r"Peak:\s+(-?[\d.]+|-inf) dBFS", stderr)
    lufs = float(lufs_match[-1]) if lufs_match else None
    peak = None if not peak_match or peak_match[-1] == "-inf" else float(peak_match[-1])
    return {"black": black, "freezes": freezes, "silences": silences, "lufs": lufs, "peak_dbfs": peak}


def score(report: dict[str, Any], *, expect_speech: bool, has_subtitles: bool,
          info: dict[str, Any] | None = None) -> dict[str, Any]:
    points = 10.0
    issues: list[str] = []
    black = report["black"]
    if black:
        first = black[0][0] < 0.5
        lost = min(4.0, 2.0 * len(black) + (1.0 if first else 0.0))
        points -= lost
        issues.append(f"{len(black)} passage(s) noir(s)" + (" dès le début (le hook est perdu)" if first else ""))
    long_freezes = [f for f in report["freezes"] if f >= 2]
    if long_freezes:
        points -= min(2.0, 0.5 * len(long_freezes))
        issues.append(f"{len(long_freezes)} image(s) figée(s) de 2 s ou plus")
    if expect_speech and report["silences"]:
        points -= min(2.0, 0.5 * len(report["silences"]))
        issues.append(f"{len(report['silences'])} silence(s) de plus de 1,5 s")
    lufs = report["lufs"]
    if lufs is None or lufs < -60:
        if expect_speech:
            points -= 2.0
            issues.append("son absent ou inaudible")
    elif not TARGET_LUFS[0] <= lufs <= TARGET_LUFS[1]:
        points -= 1.0
        issues.append(f"volume {'trop faible' if lufs < TARGET_LUFS[0] else 'trop fort'} ({lufs:g} LUFS, "
                      "vise environ -14)")
    if report.get("peak_dbfs") is not None and report["peak_dbfs"] > -0.5:
        points -= 0.5
        issues.append("son qui sature")
    if expect_speech and not has_subtitles:
        points -= 1.0
        issues.append("pas de sous-titres alors qu'il y a de la parole")
    if info and float(info.get("duration_s") or 0) < 5:
        points -= 1.0
        issues.append("vidéo de moins de 5 secondes")
    return {"score": round(max(0.0, points), 1), "issues": issues, "report": report}


def analyse(settings: Settings, path: Path, *, expect_speech: bool, has_subtitles: bool,
            info: dict[str, Any] | None = None) -> dict[str, Any]:
    video, audio = _filters(expect_speech)
    try:
        result = run([ffmpeg_path(settings), "-hide_banner", "-nostats", "-i", str(path), "-vf", video,
                      "-af", audio, "-f", "null", "-"], timeout_s=900, what="Le contrôle qualité")
    except MediaToolError as exc:
        return {"score": 0.0, "issues": [str(exc)], "report": {}}
    return score(parse_report(result.stderr), expect_speech=expect_speech, has_subtitles=has_subtitles, info=info)
