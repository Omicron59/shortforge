"""Sous-titres et montage final : un MP4 vertical 1080x1920 (H.264 + AAC) assemble par FFmpeg.

Pour chaque scene, on prend son dernier clip video (sinon son image, avec un lent zoom), on le
recadre en 9:16 et on l'ajuste a la duree de la scene (allongee si la voix off est plus longue).
On enchaine les scenes, on incruste les sous-titres animes et le logo, puis on ajoute la voix off
et la musique (sinon une piste muette, pour que la video reste lisible partout).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.media import MediaToolError, ffmpeg_path, probe_json, run
from shortforge.models import Asset, MusicTrack, Project, Render, Subtitle
from shortforge.services import subtitles as subs
from shortforge.services.app_settings import get_value
from shortforge.services.production import ProductionError, project_scenes, scene_asset

WIDTH, HEIGHT, FPS = 1080, 1920, 30
MAX_SHORT_DURATION_S = 180  # limite YouTube Shorts
FADE_S = 0.4
ZOOM_OVERSAMPLE = 3  # agrandissement avant le zoom lent (fluidite)
ZOOM_AMOUNT = 0.10  # zoom total sur la duree d'une scene (10 %)
LOUDNESS = "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000"  # volume des plateformes (-14 LUFS)
DEFAULT_PRESET = "classique_jaune"
LOGO_POSITIONS = {"haut_droite": "W-w-48:64", "haut_gauche": "48:64", "bas_droite": "W-w-48:H-h-140",
                  "bas_gauche": "48:H-h-140"}

# Gardes pour compatibilite avec l'ancien nom des fonctions.
to_srt = subs.to_srt


class RenderError(ProductionError):
    """Erreur de montage ; le message est destine a l'utilisateur."""


def brand_settings(session: Session) -> dict[str, Any]:
    defaults = {"logo_path": "", "logo_position": "haut_droite", "logo_scale": 0.16, "logo_opacity": 0.9,
                "subtitle_preset": DEFAULT_PRESET}
    return {**defaults, **(get_value(session, "brand", {}) or {})}


# ── Sous-titres ──


def current_subtitle(session: Session, project_id: str) -> Subtitle | None:
    return session.scalars(select(Subtitle).where(Subtitle.project_id == project_id)
                           .order_by(Subtitle.created_at.desc())).first()


def subtitle_style(session: Session, subtitle: Subtitle | None) -> dict[str, Any]:
    stored = dict(subtitle.style or {}) if subtitle else {}
    preset = stored.get("preset") or brand_settings(session)["subtitle_preset"]
    style = subs.preset_style(preset, stored)
    if subtitle and subtitle.position in subs.ALIGNMENTS and "position" not in stored:
        style["position"] = subtitle.position
    return {**style, "preset": preset}


def save_subtitles(session: Session, data_dir: Path, project: Project, words: list[dict[str, Any]],
                   source: str) -> dict[str, Any]:
    subtitle = current_subtitle(session, project.id)
    if subtitle is None:
        subtitle = Subtitle(project_id=project.id, style={"preset": brand_settings(session)["subtitle_preset"]},
                            position="bottom")
        session.add(subtitle)
    style = subtitle_style(session, subtitle)
    segments = subs.group_lines(words, style["words_per_line"])
    subtitle.segments = segments
    out_dir = data_dir / "projects" / project.id / "render"
    out_dir.mkdir(parents=True, exist_ok=True)
    srt = out_dir / "sous-titres.srt"
    srt.write_text(subs.to_srt(segments), encoding="utf-8")
    session.add(Asset(project_id=project.id, kind="subtitle", path=str(srt), mime_type="application/x-subrip",
                      origin="generated", rights_confirmed=True, sha256=file_sha256(srt)))
    session.flush()
    return {"segments": len(segments), "source": source, "style": style["preset"]}


def create_subtitles(session: Session, data_dir: Path, project: Project) -> dict[str, Any]:
    """Etape create_subtitles : mots minutes sur la voix off si elle existe, sinon sur la duree des scenes."""
    from shortforge.services.voice import current_word_timings

    scenes = project_scenes(session, project.id)
    timings = current_word_timings(session, project.id)
    words = [w for scene in timings for w in scene.get("words", [])]
    source = "voix off" if words else "texte du script (minutage par scène)"
    return save_subtitles(session, data_dir, project, words or subs.words_from_scenes(scenes), source)


# ── Montage ──


@dataclass(slots=True)
class ClipInput:
    path: Path
    duration_s: float
    is_image: bool
    transition: str = "cut"
    start_s: float = 0.0  # debut dans le fichier source (extraits de videos longues)


@dataclass(slots=True)
class RenderPlan:
    clips: list[ClipInput]
    output: Path
    subtitles: Path | None = None
    voice: Path | None = None
    music: Path | None = None
    music_volume: float = 0.15
    source_audio: bool = False  # garder le son d'origine des clips (video longue importee)
    screen_texts: int = 0  # nombre de textes a l'ecran incrustes
    logo: Path | None = None
    logo_position: str = "haut_droite"
    logo_scale: float = 0.16
    logo_opacity: float = 0.9
    warnings: list[str] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return round(sum(c.duration_s for c in self.clips), 3)


def _clip_filter(index: int, clip: ClipInput) -> str:
    if clip.is_image:  # lent zoom avant (evite une image figee)
        # Image agrandie 3x avant le zoom : les deplacements se font au tiers de pixel, sans tremblement.
        frames = max(1, round(clip.duration_s * FPS))
        chain = [f"scale={WIDTH * ZOOM_OVERSAMPLE}:{HEIGHT * ZOOM_OVERSAMPLE}:force_original_aspect_ratio=increase"
                 ":flags=lanczos",
                 f"crop={WIDTH * ZOOM_OVERSAMPLE}:{HEIGHT * ZOOM_OVERSAMPLE}",
                 f"zoompan=z='1+{ZOOM_AMOUNT}*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                 f":d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS}"]
    else:
        chain = [f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase:flags=lanczos", f"crop={WIDTH}:{HEIGHT}"]
    chain += ["setsar=1", f"fps={FPS}", "format=yuv420p",
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
            if clip.start_s:
                cmd += ["-ss", f"{clip.start_s:g}", "-t", f"{clip.duration_s:g}"]
            cmd += ["-i", str(clip.path)]
    n = len(plan.clips)
    next_input = n
    voice_in = music_in = logo_in = silent_in = None
    if plan.voice:
        cmd += ["-i", str(plan.voice)]
        voice_in, next_input = next_input, next_input + 1
    if plan.music:
        cmd += ["-stream_loop", "-1", "-i", str(plan.music)]
        music_in, next_input = next_input, next_input + 1
    if plan.logo:
        cmd += ["-i", str(plan.logo)]
        logo_in, next_input = next_input, next_input + 1
    if not (plan.voice or plan.music or plan.source_audio):  # piste muette
        cmd += ["-f", "lavfi", "-t", f"{plan.duration_s:g}", "-i", "anullsrc=r=48000:cl=stereo"]
        silent_in, next_input = next_input, next_input + 1

    parts = [_clip_filter(i, c) for i, c in enumerate(plan.clips)]
    parts.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vcat]")
    video = "vcat"
    if plan.subtitles:
        parts.append(f"[{video}]ass={plan.subtitles.name}[vsub]")
        video = "vsub"
    if logo_in is not None:
        parts.append(f"[{logo_in}:v]scale={round(WIDTH * plan.logo_scale)}:-1,format=rgba,"
                     f"colorchannelmixer=aa={plan.logo_opacity:g}[logo]")
        position = LOGO_POSITIONS.get(plan.logo_position, LOGO_POSITIONS["haut_droite"])
        parts.append(f"[{video}][logo]overlay={position}[vlogo]")
        video = "vlogo"
    parts.append(f"[{video}]null[vout]")

    audio = []
    if plan.source_audio:
        parts.append("".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[src]")
        audio.append("[src]")
    if voice_in is not None:
        parts.append(f"[{voice_in}:a]aformat=sample_rates=48000:channel_layouts=stereo[voice]")
        audio.append("[voice]")
    if music_in is not None:
        parts.append(f"[{music_in}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                     f"volume={plan.music_volume:g}[music]")
        audio.append("[music]")
    if silent_in is not None:
        audio.append(f"[{silent_in}:a]")
    if len(audio) > 1:
        parts.append("".join(audio) + f"amix=inputs={len(audio)}:duration=first:normalize=0,"
                     f"{LOUDNESS},aformat=sample_rates=48000:channel_layouts=stereo[aout]")
    else:
        parts.append(f"{audio[0]}{LOUDNESS},aformat=sample_rates=48000:channel_layouts=stereo[aout]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-t", f"{plan.duration_s:g}", "-movflags", "+faststart", str(plan.output.name)]
    return cmd


def _latest(session: Session, project_id: str, kind: str) -> Asset | None:
    asset = session.scalars(select(Asset).where(Asset.project_id == project_id, Asset.kind == kind)
                            .order_by(Asset.created_at.desc())).first()
    return asset if asset and Path(asset.path).is_file() else None


def add_finishing(session: Session, plan: RenderPlan, project: Project,
                  screen: list[dict[str, Any]] | None = None) -> None:
    """Sous-titres, textes a l'ecran, logo et musique (communs aux Shorts et aux extraits de videos longues)."""
    out_dir = plan.output.parent
    subtitle = current_subtitle(session, project.id)
    segments = subtitle.segments if subtitle and subtitle.segments else []
    if segments or screen:
        ass = out_dir / "sous-titres.ass"
        ass.write_text(subs.to_ass(segments, subtitle_style(session, subtitle), screen), encoding="utf-8")
        plan.subtitles = ass
    plan.screen_texts = len(screen or [])
    brand = brand_settings(session)
    if brand["logo_path"] and Path(brand["logo_path"]).is_file():
        plan.logo = Path(brand["logo_path"])
        plan.logo_position = brand["logo_position"]
        plan.logo_scale = float(brand["logo_scale"])
        plan.logo_opacity = float(brand["logo_opacity"])
    music = _latest(session, project.id, "music")
    if music:
        plan.music = Path(music.path)
        track = session.scalars(select(MusicTrack).where(MusicTrack.path == music.path)).first()
        plan.music_volume = track.volume if track else plan.music_volume


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
            warnings.append(f"Scène {scene.position + 1} : pas de clip vidéo, image animée (zoom lent).")
        else:
            raise RenderError(f"Scène {scene.position + 1} : ni vidéo ni image à monter. Refais sa génération.")
    plan = RenderPlan(clips=clips, output=out_dir / "short_1080x1920.mp4", warnings=warnings)
    if plan.duration_s > MAX_SHORT_DURATION_S:
        raise RenderError(f"Le Short dure {plan.duration_s:g} s : YouTube Shorts accepte "
                          f"{MAX_SHORT_DURATION_S} s au plus.")
    voice = _latest(session, project.id, "audio")
    plan.voice = Path(voice.path) if voice else None
    add_finishing(session, plan, project, subs.screen_texts(scenes))
    if plan.voice is None and plan.music is None:
        warnings.append("Pas de voix off ni de musique : la vidéo est exportée avec une piste son muette.")
    return plan


def ffmpeg_binary(settings: Settings) -> str:
    try:
        return ffmpeg_path(settings)
    except MediaToolError as exc:
        raise RenderError(str(exc)) from exc


def run_ffmpeg(cmd: list[str], cwd: Path, timeout_s: float = 1800) -> None:
    try:
        run(cmd, cwd=cwd, timeout_s=timeout_s, what="FFmpeg")
    except MediaToolError as exc:
        raise RenderError(str(exc)) from exc


def probe(path: Path, settings: Settings) -> dict[str, Any]:
    """Caracteristiques reelles du fichier (via ffprobe)."""
    try:
        data = probe_json(settings, path)
    except MediaToolError as exc:
        raise RenderError(f"Impossible d'analyser la vidéo : {exc}") from exc
    streams = data.get("streams", [])
    video: dict[str, Any] = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio: dict[str, Any] = next((s for s in streams if s.get("codec_type") == "audio"), {})
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


def execute_plan(session: Session, settings: Settings, project: Project, plan: RenderPlan) -> dict[str, Any]:
    """Lance FFmpeg, verifie le fichier, controle sa qualite et enregistre le rendu."""
    from shortforge.services.quality import analyse

    run_ffmpeg(build_command(ffmpeg_binary(settings), plan), cwd=plan.output.parent)
    info = probe(plan.output, settings)
    problems = spec_problems(info)
    if problems:
        raise RenderError("Vidéo exportée non conforme : " + ", ".join(problems) + ".")
    quality = analyse(settings, plan.output, expect_speech=bool(plan.voice or plan.source_audio),
                      has_subtitles=plan.subtitles is not None, info=info)
    asset = Asset(project_id=project.id, kind="render", path=str(plan.output), mime_type="video/mp4",
                  origin="generated", rights_confirmed=True, sha256=file_sha256(plan.output))
    session.add(asset)
    session.flush()
    render = Render(project_id=project.id, kind="final", width=WIDTH, height=HEIGHT, codec="h264",
                    asset_id=asset.id, status="done")
    session.add(render)
    session.flush()
    return {"render_id": render.id, "asset_id": asset.id, **info, "warnings": plan.warnings, "quality": quality,
            "screen_texts": plan.screen_texts}


def render_video(session: Session, settings: Settings, project: Project) -> dict[str, Any]:
    """Etape render_video : monte le Short et verifie le fichier obtenu."""
    return execute_plan(session, settings, project, plan_render(session, settings.shortforge_data_dir, project))


def latest_render(session: Session, project_id: str) -> Render | None:
    return session.scalars(select(Render).where(Render.project_id == project_id, Render.kind == "final")
                           .order_by(Render.created_at.desc())).first()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
