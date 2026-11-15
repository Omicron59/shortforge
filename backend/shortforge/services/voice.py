"""Voix off : une piste par scene, puis une piste complete calee sur la duree des scenes.

Si la voix d'une scene est plus longue que la scene, la scene est allongee (le clip video est
prolonge au montage). Les mots sont minutes avec Whisper s'il est installe, sinon repartis
regulierement sur la duree reelle de la voix.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.integrations.tts import TTSEngine, TTSError, all_engines, pick_engine
from shortforge.media import MediaToolError, duration_of, ffmpeg_path, run
from shortforge.models import Asset, Cost, Project, Scene, VoiceTake
from shortforge.pipeline.handlers import ConfirmationRequired
from shortforge.runtime import Runtime
from shortforge.services.app_settings import get_value
from shortforge.services.budget import BudgetService, format_usd
from shortforge.services.production import ProductionError, project_scenes

PADDING_S = 0.3  # respiration apres chaque phrase
DEFAULT_VOICE = {"engine": "auto", "speed": 1.0, "enabled": True}
CONFIRM_LABEL = "Voix off ElevenLabs"


class VoiceError(ProductionError):
    """Erreur de voix off ; le message est destine a l'utilisateur."""


def voice_settings(session: Session) -> dict[str, Any]:
    return {**DEFAULT_VOICE, **(get_value(session, "voice", {}) or {})}


def engines_status(settings: Settings) -> list[dict[str, Any]]:
    return [{"id": s.id, "name": s.name, "local": s.local, "available": s.available, "detail": s.detail}
            for s in (e.status() for e in all_engines(settings))]


def _open_confirmation(session: Session, project_id: str, amount: float) -> Cost | None:
    rows = session.scalars(select(Cost).where(Cost.project_id == project_id, Cost.kind == "confirmation",
                                              Cost.scene_id.is_(None), Cost.description == CONFIRM_LABEL))
    return next((c for c in rows if c.amount_usd + 1e-9 >= amount), None)


def _script_text(scenes: list[Scene]) -> str:
    return " ".join(s.text for s in scenes if s.text.strip())


def voice_cost(engine: TTSEngine, scenes: list[Scene]) -> float | None:
    return engine.estimate_cost(_script_text(scenes))


def confirm_voice(session: Session, runtime: Runtime, project: Project) -> None:
    """Validation humaine de la depense ElevenLabs (budget reverifie)."""
    scenes = project_scenes(session, project.id)
    engine = runtime.tts_override or pick_engine(runtime.settings, voice_settings(session)["engine"],
                                                 transport=runtime.http_transport)
    amount = voice_cost(engine, scenes)
    if amount is None:
        raise VoiceError("Tarif ElevenLabs inconnu : renseigne ELEVENLABS_COST_PER_1000_CHARS.")
    decision = BudgetService(session, runtime.settings).check(amount, project_id=project.id, provider_name=engine.name)
    if not decision.allowed:
        raise VoiceError("Budget dépassé : " + "; ".join(decision.reasons) + ".")
    session.add(Cost(project_id=project.id, amount_usd=amount, kind="confirmation", description=CONFIRM_LABEL))
    session.flush()


def generate_voice(session: Session, runtime: Runtime, project: Project) -> dict[str, Any]:
    """Etape generate_voice."""
    prefs = voice_settings(session)
    if not prefs.get("enabled", True):
        return {"skipped": True, "message": "Voix off désactivée dans les réglages : vidéo sans voix."}
    scenes = project_scenes(session, project.id)
    if not _script_text(scenes):
        return {"skipped": True, "message": "Aucun texte à dire dans les scènes."}
    engine = runtime.tts_override or pick_engine(runtime.settings, prefs["engine"], transport=runtime.http_transport)
    status = engine.status()
    if not status.available:
        raise VoiceError(f"{engine.name} indisponible : {status.detail}.")

    confirmation: Cost | None = None
    if not engine.local:  # service payant : confirmation explicite et budget
        amount = voice_cost(engine, scenes)
        if amount is None:
            raise VoiceError(f"Tarif de {engine.name} inconnu : génération bloquée.")
        confirmation = _open_confirmation(session, project.id, amount)
        if confirmation is None:
            chars = len(_script_text(scenes))
            message = (f"La voix off utilisera {engine.name}.\nTexte : {chars} caractères.\n"
                       f"Coût estimé : {format_usd(amount)}.\nConfirmer la génération ?")
            raise ConfirmationRequired(message, [{"engine": engine.id, "estimated_cost_usd": amount,
                                                  "message": message, "characters": chars}])

    out_dir = runtime.project_dir(project.id) / "voice"
    out_dir.mkdir(parents=True, exist_ok=True)
    speed = float(prefs.get("speed", 1.0) or 1.0)
    clips: list[tuple[Scene, Path | None, float]] = []
    lengthened = []
    try:
        for scene in scenes:
            if not scene.text.strip():
                clips.append((scene, None, 0.0))
                continue
            wav = engine.synthesize(scene.text, out_dir / f"scene_{scene.position + 1:02d}.wav",
                                    language=project.language, speed=speed)
            length = duration_of(runtime.settings, wav)
            if length + PADDING_S > scene.duration_s:
                scene.duration_s = round(length + PADDING_S, 2)
                lengthened.append(scene.position + 1)
            session.add(Asset(project_id=project.id, scene_id=scene.id, kind="voice", path=str(wav),
                              mime_type="audio/wav", origin="generated", rights_confirmed=True))
            clips.append((scene, wav, length))
    except (TTSError, MediaToolError) as exc:
        raise VoiceError(str(exc)) from exc

    track = out_dir / "voix_off.wav"
    _assemble(runtime.settings, clips, track)
    session.add(Asset(project_id=project.id, kind="audio", path=str(track), mime_type="audio/wav",
                      origin="generated", rights_confirmed=True))
    take = VoiceTake(project_id=project.id, engine=engine.id, language=project.language, speed=speed,
                     selected=True, pauses={"scenes": [{"position": s.position, "voice_s": d} for s, _, d in clips]})
    session.add(take)
    if confirmation is not None:
        amount = voice_cost(engine, scenes) or 0.0
        BudgetService(session, runtime.settings).record(amount, project_id=project.id,
                                                        description=f"Voix off {engine.name}")
        confirmation.description = f"{CONFIRM_LABEL} (utilisée)"
    session.flush()
    timings = word_timings(session, runtime, project, clips)
    return {"engine": engine.name, "scenes": sum(1 for _, p, _ in clips if p), "lengthened_scenes": lengthened,
            "word_timing": timings,
            "duration_s": round(sum(s.duration_s for s in scenes), 2)}


def _assemble(settings: Settings, clips: list[tuple[Scene, Path | None, float]], dest: Path) -> None:
    """Colle les voix des scenes, chacune calee au debut de sa scene (silence pour finir la scene)."""
    cmd = [ffmpeg_path(settings), "-hide_banner", "-y"]
    parts: list[str] = []
    labels = []
    index = 0
    for i, (scene, path, _) in enumerate(clips):
        if path is None:
            parts.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={scene.duration_s:g}[s{i}]")
        else:
            cmd += ["-i", str(path)]
            parts.append(f"[{index}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                         f"apad=whole_dur={scene.duration_s:g},atrim=duration={scene.duration_s:g}[s{i}]")
            index += 1
        labels.append(f"[s{i}]")
    parts.append("".join(labels) + f"concat=n={len(clips)}:v=0:a=1[out]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[out]", "-ar", "48000", "-ac", "2", str(dest)]
    run(cmd, timeout_s=600, what="L'assemblage de la voix off")


def word_timings(session: Session, runtime: Runtime, project: Project,
                 clips: list[tuple[Scene, Path | None, float]]) -> str:
    """Minutage des mots par scene (Whisper si possible), garde pour les sous-titres animes."""
    transcriber = runtime.get_transcriber()
    use_whisper = bool(transcriber and transcriber.available())
    start = 0.0
    timings: list[dict[str, Any]] = []
    for scene, path, voice_s in clips:
        words: list[dict[str, Any]] = []
        if path is not None and use_whisper:
            try:
                for seg in transcriber.transcribe(path, language=project.language):
                    words += [{"word": w["word"], "start": round(start + w["start"], 3),
                               "end": round(start + w["end"], 3)} for w in seg.get("words", [])]
            except Exception:  # le minutage calcule prend le relais
                words = []
        if not words and scene.text.strip():
            tokens = scene.text.split()
            span = voice_s if voice_s > 0 else scene.duration_s
            step = span / len(tokens)
            words = [{"word": t, "start": round(start + i * step, 3), "end": round(start + (i + 1) * step, 3)}
                     for i, t in enumerate(tokens)]
        timings.append({"scene_id": scene.id, "position": scene.position, "words": words})
        start += scene.duration_s
    take = session.scalars(select(VoiceTake).where(VoiceTake.project_id == project.id)
                           .order_by(VoiceTake.created_at.desc())).first()
    if take is not None:
        take.pauses = {**(take.pauses or {}), "words": timings}
    session.flush()
    return "whisper" if use_whisper else "calculé"


def current_word_timings(session: Session, project_id: str) -> list[dict[str, Any]]:
    take = session.scalars(select(VoiceTake).where(VoiceTake.project_id == project_id, VoiceTake.selected.is_(True))
                           .order_by(VoiceTake.created_at.desc())).first()
    return list((take.pauses or {}).get("words", [])) if take else []
