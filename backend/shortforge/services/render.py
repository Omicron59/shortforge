"""Sous-titres et montage final : un MP4 vertical 1080x1920 (H.264 + AAC) assemble par FFmpeg.

Pour chaque scene, on prend son dernier clip video (sinon son image, en plan fixe), on le recadre
en 9:16, on l'ajuste a la duree de la scene, puis on enchaine les scenes, on incruste les
sous-titres et on ajoute le son (voix off et musique si elles existent, sinon une piste muette
pour que la video reste lisible partout).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.models import Asset, Project, Render, Scene, Subtitle
from shortforge.services.production import ProductionError, project_scenes, scene_asset

WIDTH, HEIGHT, FPS = 1080, 1920, 30
MAX_SHORT_DURATION_S = 180  # limite YouTube Shorts
WORDS_PER_SUBTITLE = 4
FADE_S = 0.4

DEFAULT_STYLE: dict[str, Any] = {"font": "Arial", "size": 78, "color": "#FFFFFF", "outline_color": "#000000",
                                 "outline": 5, "position": "bottom", "uppercase": True}
ALIGNMENTS = {"bottom": 2, "middle": 5, "top": 8}
MARGINS_V = {"bottom": 380, "middle": 0, "top": 260}


class RenderError(ProductionError):
    """Erreur de montage ; le message est destine a l'utilisateur."""


# ── Sous-titres ──


def build_segments(scenes: list[Scene]) -> list[dict[str, Any]]:
    """Sous-titres de 4 mots au plus, repartis regulierement sur la duree de chaque scene."""
    segments: list[dict[str, Any]] = []
    start = 0.0
    for scene in scenes:
        words = scene.text.split()
        chunks = [" ".join(words[i:i + WORDS_PER_SUBTITLE]) for i in range(0, len(words), WORDS_PER_SUBTITLE)]
        step = scene.duration_s / len(chunks) if chunks else 0
        for i, chunk in enumerate(chunks):
            segments.append({"start": round(start + i * step, 3), "end": round(start + (i + 1) * step, 3),
                             "text": chunk})
        start += scene.duration_s
    return segments


def _timestamp(seconds: float, sep: str) -> str:
    ms = round(seconds * 1000)
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    if sep == ",":
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    return f"{h:d}:{m:02d}:{s:02d}.{ms // 10:02d}"


def to_srt(segments: list[dict[str, Any]]) -> str:
    blocks = [f"{i}\n{_timestamp(seg['start'], ',')} --> {_timestamp(seg['end'], ',')}\n{seg['text']}\n"
              for i, seg in enumerate(segments, 1)]
    return "\n".join(blocks)


def _ass_color(hex_color: str) -> str:
    value = hex_color.lstrip("#")
    if len(value) != 6:
        value = "FFFFFF"
    r, g, b = value[0:2], value[2:4], value[4:6]
    return f"&H00{b}{g}{r}".upper()


def to_ass(segments: list[dict[str, Any]], style: dict[str, Any] | None = None) -> str:
    """Sous-titres ASS a l'echelle exacte de la video 1080x1920."""
    st = {**DEFAULT_STYLE, **(style or {})}
    position = st["position"] if st["position"] in ALIGNMENTS else "bottom"
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{st['font']},{int(st['size'])},{_ass_color(st['color'])},&H000000FF,"
        f"{_ass_color(st['outline_color'])},&H80000000,-1,0,0,0,100,100,0,0,1,{int(st['outline'])},2,"
        f"{ALIGNMENTS[position]},80,80,{MARGINS_V[position]},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = []
    for seg in segments:
        text = str(seg["text"]).replace("\n", " ").replace("{", "(").replace("}", ")")
        if st.get("uppercase"):
            text = text.upper()
        start, end = _timestamp(seg["start"], "."), _timestamp(seg["end"], ".")
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    return header + "\n".join(lines) + "\n"


def create_subtitles(session: Session, data_dir: Path, project: Project) -> dict[str, Any]:
    """Etape create_subtitles : sous-titres calcules depuis le texte des scenes (fichier .srt garde)."""
    scenes = project_scenes(session, project.id)
    segments = build_segments(scenes)
    subtitle = current_subtitle(session, project.id)
    if subtitle is None:
        subtitle = Subtitle(project_id=project.id, style=dict(DEFAULT_STYLE), position="bottom")
        session.add(subtitle)
    subtitle.segments = segments
    out_dir = data_dir / "projects" / project.id / "render"
    out_dir.mkdir(parents=True, exist_ok=True)
    srt = out_dir / "sous-titres.srt"
    srt.write_text(to_srt(segments), encoding="utf-8")
    session.add(Asset(project_id=project.id, kind="subtitle", path=str(srt), mime_type="application/x-subrip",
                      origin="generated", rights_confirmed=True, sha256=_sha256(srt)))
    session.flush()
    return {"segments": len(segments), "source": "texte du script (minutage par scène)"}


def current_subtitle(session: Session, project_id: str) -> Subtitle | None:
    return session.scalars(select(Subtitle).where(Subtitle.project_id == project_id)
                           .order_by(Subtitle.created_at.desc())).first()


# ── Montage ──


@dataclass(slots=True)
class ClipInput:
    path: Path
    duration_s: float
    is_image: bool
    transition: str = "cut"


@dataclass(slots=True)
class RenderPlan:
    clips: list[ClipInput]
    output: Path
    subtitles: Path | None = None
    voice: Path | None = None
    music: Path | None = None
    music_volume: float = 0.15
    warnings: list[str] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return round(sum(c.duration_s for c in self.clips), 3)


def _clip_filter(index: int, clip: ClipInput) -> str:
    chain = [f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase", f"crop={WIDTH}:{HEIGHT}",
             "setsar=1", f"fps={FPS}", "format=yuv420p",
             f"tpad=stop_mode=clone:stop_duration={clip.duration_s:g}",
             f"trim=duration={clip.duration_s:g}", "setpts=PTS-STARTPTS"]
    if clip.transition == "fondu":
        chain.append(f"fade=t=in:st=0:d={FADE_S}")
    elif clip.transition == "flash":
        chain.append(f"fade=t=in:st=0:d={FADE_S}:color=white")
    return f"[{index}:v]{','.join(chain)}[v{index}]"


def build_command(ffmpeg: str, plan: RenderPlan) -> list[str]:
    """Commande FFmpeg complete. A lancer depuis le dossier du rendu (chemin des sous-titres relatif)."""
    cmd = [ffmpeg, "-hide_banner", "-y"]
    for clip in plan.clips:
        if clip.is_image:
            cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{clip.duration_s:g}", "-i", str(clip.path)]
        else:
            cmd += ["-i", str(clip.path)]
    n = len(plan.clips)
    audio_inputs: list[int] = []
    if plan.voice:
        cmd += ["-i", str(plan.voice)]
        audio_inputs.append(n + len(audio_inputs))
    if plan.music:
        cmd += ["-stream_loop", "-1", "-i", str(plan.music)]
        audio_inputs.append(n + len(audio_inputs))
    if not audio_inputs:  # piste muette : certains lecteurs refusent une video sans son
        cmd += ["-f", "lavfi", "-t", f"{plan.duration_s:g}", "-i", "anullsrc=r=48000:cl=stereo"]
        audio_inputs.append(n)

    parts = [_clip_filter(i, c) for i, c in enumerate(plan.clips)]
    parts.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vcat]")
    if plan.subtitles:
        parts.append(f"[vcat]ass={plan.subtitles.name}[vout]")
    else:
        parts.append("[vcat]null[vout]")
    if plan.voice and plan.music:
        parts.append(f"[{audio_inputs[1]}:a]volume={plan.music_volume}[music]")
        parts.append(f"[{audio_inputs[0]}:a][music]amix=inputs=2:duration=first:normalize=0[aout]")
    else:
        parts.append(f"[{audio_inputs[0]}:a]aformat=sample_rates=48000:channel_layouts=stereo[aout]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-t", f"{plan.duration_s:g}", "-movflags", "+faststart", str(plan.output.name)]
    return cmd


def plan_render(session: Session, data_dir: Path, project: Project) -> RenderPlan:
    scenes = project_scenes(session, project.id)
    out_dir = data_dir / "projects" / project.id / "render"
    out_dir.mkdir(parents=True, exist_ok=True)
    clips: list[ClipInput] = []
    warnings: list[str] = []
    for scene in scenes:
        video = scene_asset(session, scene.id, "video")
        image = scene_asset(session, scene.id, "image")
        if video and Path(video.path).is_file():
            clips.append(ClipInput(Path(video.path), scene.duration_s, False, scene.transition))
        elif image and Path(image.path).is_file():
            clips.append(ClipInput(Path(image.path), scene.duration_s, True, scene.transition))
            warnings.append(f"Scène {scene.position + 1} : pas de clip vidéo, image fixe utilisée.")
        else:
            raise RenderError(f"Scène {scene.position + 1} : ni vidéo ni image à monter. Refais sa génération.")
    plan = RenderPlan(clips=clips, output=out_dir / "short_1080x1920.mp4", warnings=warnings)
    if plan.duration_s > MAX_SHORT_DURATION_S:
        raise RenderError(f"Le Short dure {plan.duration_s:g} s : YouTube Shorts accepte "
                          f"{MAX_SHORT_DURATION_S} s au plus.")

    subtitle = current_subtitle(session, project.id)
    if subtitle and subtitle.segments:
        ass = out_dir / "sous-titres.ass"
        ass.write_text(to_ass(subtitle.segments, {**subtitle.style, "position": subtitle.position}), encoding="utf-8")
        plan.subtitles = ass
    voice = _latest(session, project.id, "audio")
    music = _latest(session, project.id, "music")
    plan.voice = Path(voice.path) if voice else None
    plan.music = Path(music.path) if music else None
    if plan.voice is None:
        warnings.append("Pas de voix off : la vidéo est exportée avec une piste son muette.")
    return plan


def _latest(session: Session, project_id: str, kind: str) -> Asset | None:
    asset = session.scalars(select(Asset).where(Asset.project_id == project_id, Asset.kind == kind)
                            .order_by(Asset.created_at.desc())).first()
    return asset if asset and Path(asset.path).is_file() else None


def ffmpeg_binary(settings: Settings) -> str:
    found = shutil.which(settings.ffmpeg_path)
    if not found:
        raise RenderError("FFmpeg introuvable : installe-le (winget install Gyan.FFmpeg) ou renseigne FFMPEG_PATH.")
    return found


def run_ffmpeg(cmd: list[str], cwd: Path, timeout_s: float = 1800) -> None:
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RenderError("Le montage FFmpeg a pris trop de temps : abandon.") from exc
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-6:])
        raise RenderError(f"FFmpeg a échoué :\n{tail}")


def probe(path: Path, settings: Settings) -> dict[str, Any]:
    """Caracteristiques reelles du fichier (via ffprobe, a cote de ffmpeg)."""
    ffmpeg = Path(ffmpeg_binary(settings))
    ffprobe = shutil.which("ffprobe") or str(ffmpeg.with_name(ffmpeg.name.replace("ffmpeg", "ffprobe")))
    try:
        out = subprocess.run([ffprobe, "-v", "error", "-show_entries",
                              "stream=codec_type,codec_name,width,height,pix_fmt:format=duration,size",
                              "-of", "json", str(path)], capture_output=True, text=True, timeout=60, check=True)
    except (subprocess.SubprocessError, OSError) as exc:
        raise RenderError(f"Impossible d'analyser la vidéo : {exc}") from exc
    data = json.loads(out.stdout or "{}")
    video: dict[str, Any] = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    audio: dict[str, Any] = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    return {"width": video.get("width"), "height": video.get("height"), "video_codec": video.get("codec_name"),
            "pix_fmt": video.get("pix_fmt"), "audio_codec": audio.get("codec_name"),
            "duration_s": round(float(data.get("format", {}).get("duration", 0) or 0), 2),
            "size_bytes": int(data.get("format", {}).get("size", 0) or 0)}


def spec_problems(info: dict[str, Any]) -> list[str]:
    """Ecarts entre le fichier et le format attendu pour un Short."""
    problems = []
    if (info.get("width"), info.get("height")) != (WIDTH, HEIGHT):
        problems.append(f"format {info.get('width')}x{info.get('height')} au lieu de {WIDTH}x{HEIGHT}")
    if info.get("video_codec") != "h264":
        problems.append(f"codec vidéo {info.get('video_codec')} au lieu de H.264")
    if info.get("audio_codec") != "aac":
        problems.append("piste son AAC absente")
    duration = float(info.get("duration_s") or 0)
    if not 0 < duration <= MAX_SHORT_DURATION_S:
        problems.append(f"durée {duration:g} s hors limites (1 à {MAX_SHORT_DURATION_S} s)")
    return problems


def render_video(session: Session, settings: Settings, project: Project) -> dict[str, Any]:
    """Etape render_video : monte le Short et verifie le fichier obtenu."""
    plan = plan_render(session, settings.shortforge_data_dir, project)
    ffmpeg = ffmpeg_binary(settings)
    run_ffmpeg(build_command(ffmpeg, plan), cwd=plan.output.parent)
    info = probe(plan.output, settings)
    problems = spec_problems(info)
    if problems:
        raise RenderError("Vidéo exportée non conforme : " + ", ".join(problems) + ".")
    asset = Asset(project_id=project.id, kind="render", path=str(plan.output), mime_type="video/mp4",
                  origin="generated", rights_confirmed=True, sha256=_sha256(plan.output))
    session.add(asset)
    session.flush()
    render = Render(project_id=project.id, kind="final", width=WIDTH, height=HEIGHT, codec="h264",
                    asset_id=asset.id, status="done")
    session.add(render)
    session.flush()
    return {"render_id": render.id, "asset_id": asset.id, **info, "warnings": plan.warnings}


def latest_render(session: Session, project_id: str) -> Render | None:
    return session.scalars(select(Render).where(Render.project_id == project_id, Render.kind == "final")
                           .order_by(Render.created_at.desc())).first()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_sha256(path: Path) -> str:
    return _sha256(path)
