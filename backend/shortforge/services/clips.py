"""Video longue → plusieurs Shorts : transcription locale, choix des meilleurs passages, recadrage 9:16.

La video doit etre la tienne (ou tu dois en avoir les droits) : l'import exige une confirmation.
Le recadrage est centre (pas de suivi du visage). Le son d'origine est garde ; les sous-titres
animes viennent de la transcription mot a mot.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.integrations.ollama import LLMClient, LLMError
from shortforge.media import MediaToolError, duration_of
from shortforge.models import Project, SourceVideo
from shortforge.pipeline.engine import PipelineService
from shortforge.pipeline.steps import StepName
from shortforge.services import render as render_service
from shortforge.services.production import ProductionError
from shortforge.services.safety import content_issues

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".m4v", ".webm", ".avi"}
MIN_CLIP_S, MAX_CLIP_S = 12.0, 90.0
SKIPPED_FOR_CLIPS = [StepName.GENERATE_IDEAS, StepName.SELECT_IDEA, StepName.WRITE_SCRIPT, StepName.APPROVE_SCRIPT,
                     StepName.CREATE_STORYBOARD, StepName.GENERATE_IMAGES, StepName.GENERATE_VIDEOS,
                     StepName.GENERATE_VOICE, StepName.SELECT_MUSIC]


class ClipError(ProductionError):
    """Erreur sur une video importee ; le message est destine a l'utilisateur."""


def safe_name(filename: str, default: str = "video") -> str:
    return re.sub(r"[^\w.-]+", "_", Path(filename).stem)[:60] or default


def register_source(session: Session, settings: Settings, path: Path, *, title: str, rights_confirmed: bool,
                    language: str = "fr") -> SourceVideo:
    if not rights_confirmed:
        path.unlink(missing_ok=True)
        raise ClipError("Confirme que cette vidéo est la tienne ou que tu as le droit de la réutiliser.")
    try:
        duration = duration_of(settings, path)
    except MediaToolError as exc:
        path.unlink(missing_ok=True)
        raise ClipError("Vidéo illisible.") from exc
    source = SourceVideo(title=title.strip() or path.stem, path=str(path), duration_s=duration,
                         rights_confirmed=True, language=language)
    session.add(source)
    session.flush()
    return source


def transcribe_source(session: Session, transcriber: Any, source: SourceVideo) -> dict[str, Any]:
    try:
        source.transcript = transcriber.transcribe(Path(source.path), language=source.language)
    except Exception as exc:
        source.status, source.error = "failed", str(exc)
        session.flush()
        raise ClipError(str(exc)) from exc
    source.status, source.error = "transcribed", None
    session.flush()
    return {"segments": len(source.transcript)}


PICK_SYSTEM = """Tu repères dans la transcription d'une vidéo longue les passages qui feraient de
bons Shorts autonomes : une idée complète, une accroche forte dans les premières secondes, une fin
nette. Chaque passage dure entre 15 et 60 secondes. Utilise uniquement les horodatages fournis.
Réponds uniquement en JSON."""

PICK_PROMPT = """Transcription horodatée (secondes) :
{lines}
Propose jusqu'à {count} passages. Format JSON exact :
{{"clips": [{{"start": 12.0, "end": 48.5, "title": "...", "hook": "première phrase forte", "why": "..."}}]}}"""


def propose_clips(session: Session, llm: LLMClient, source: SourceVideo, count: int = 5) -> list[dict[str, Any]]:
    if not source.transcript:
        raise ClipError("Transcris d'abord la vidéo.")
    lines = "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in source.transcript)[:24000]
    raw = llm.generate_json(PICK_SYSTEM, PICK_PROMPT.format(lines=lines, count=count), temperature=0.3)
    items = raw.get("clips")
    if not isinstance(items, list):
        raise LLMError("Le modèle n'a proposé aucun passage.")
    proposals: list[dict[str, Any]] = []
    for item in items[:count]:
        try:
            start, end = float(item["start"]), float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        start, end = _snap(source.transcript, max(0.0, start), min(source.duration_s, end))
        if not MIN_CLIP_S <= end - start <= MAX_CLIP_S:
            continue
        title = str(item.get("title", "")).strip()[:120] or f"Extrait {len(proposals) + 1}"
        if content_issues(" ".join([title, transcript_text(source, start, end)])):
            continue
        proposals.append({"start": round(start, 2), "end": round(end, 2), "title": title,
                          "hook": str(item.get("hook", ""))[:300], "why": str(item.get("why", ""))[:300]})
    if not proposals:
        raise ClipError("Aucun passage exploitable trouvé (entre 12 et 90 secondes).")
    source.proposals, source.status = proposals, "analysed"
    session.flush()
    return proposals


def _snap(transcript: list[dict[str, Any]], start: float, end: float) -> tuple[float, float]:
    """Cale le debut et la fin sur les phrases de la transcription (pas de mot coupe)."""
    starts = [s["start"] for s in transcript]
    ends = [s["end"] for s in transcript]
    start = min(starts, key=lambda t: abs(t - start), default=start)
    end = min(ends, key=lambda t: abs(t - end), default=end)
    return start, end


def transcript_text(source: SourceVideo, start: float, end: float) -> str:
    return " ".join(s["text"] for s in source.transcript if s["end"] > start and s["start"] < end)


def create_clip_projects(session: Session, service: PipelineService, source: SourceVideo, indexes: list[int],
                         *, actor: str) -> list[Project]:
    projects = []
    for index in indexes:
        if not 0 <= index < len(source.proposals):
            raise ClipError("Extrait inconnu.")
        proposal = source.proposals[index]
        project = service.create_project(proposal["title"], niche="vidéo importée", language=source.language)
        project.source = "clip"
        project.clip = {"source_id": source.id, "start": proposal["start"], "end": proposal["end"]}
        service.skip_steps(project, SKIPPED_FOR_CLIPS, reason="Extrait d'une vidéo importée : étape sans objet.",
                           actor=actor)
        projects.append(project)
    session.flush()
    return projects


def clip_words(session: Session, project: Project) -> list[dict[str, Any]]:
    source = session.get(SourceVideo, project.clip.get("source_id"))
    if source is None:
        raise ClipError("Vidéo d'origine introuvable.")
    start, end = float(project.clip["start"]), float(project.clip["end"])
    words = []
    for segment in source.transcript:
        for word in segment.get("words") or []:
            if word["start"] >= start and word["end"] <= end:
                words.append({"word": word["word"], "start": round(word["start"] - start, 3),
                              "end": round(word["end"] - start, 3)})
    return words


def create_clip_subtitles(session: Session, data_dir: Path, project: Project) -> dict[str, Any]:
    words = clip_words(session, project)
    if not words:
        return {"skipped": True, "message": "Pas de mots minutés dans la transcription : pas de sous-titres."}
    return render_service.save_subtitles(session, data_dir, project, words, "transcription de la vidéo")


def render_clip(session: Session, settings: Settings, project: Project) -> dict[str, Any]:
    source = session.get(SourceVideo, project.clip.get("source_id"))
    if source is None or not Path(source.path).is_file():
        raise ClipError("Vidéo d'origine introuvable : réimporte-la.")
    start, end = float(project.clip["start"]), float(project.clip["end"])
    out_dir = settings.shortforge_data_dir / "projects" / project.id / "render"
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = render_service.RenderPlan(
        clips=[render_service.ClipInput(Path(source.path), round(end - start, 3), False, start_s=start)],
        output=out_dir / "short_1080x1920.mp4", source_audio=True,
        warnings=["Recadrage centré : vérifie que le sujet reste dans le cadre."])
    render_service.add_finishing(session, plan, project)
    return render_service.execute_plan(session, settings, project, plan)
