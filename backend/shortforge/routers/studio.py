"""Routes des fonctions de creation et de croissance.

Voix off, musiques, marque (logo), concurrents et formats gagnants, style personnel, resultats et
lecons, planning de la semaine, boite de validation, video longue → Shorts, publications par
plateforme et assistant de premier lancement.

Les fichiers (musique, logo, video longue) sont envoyes tels quels dans le corps de la requete
(`PUT ...?filename=...`) et ecrits par morceaux : pas de limite de taille en memoire.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.deps import build_service, get_runtime, get_session, get_settings_dep
from shortforge.integrations.tts import TTSError, pick_engine
from shortforge.models import Competitor, CompetitorVideo, Idea, MusicTrack, Project, SocialPost, SourceVideo
from shortforge.pipeline import PipelineError, StepName
from shortforge.runtime import Runtime
from shortforge.services import clips, growth, music, planning, social, voice
from shortforge.services.app_settings import get_value, set_value
from shortforge.services.production import ProductionError
from shortforge.services.render import brand_settings
from shortforge.services.subtitles import PRESETS

router = APIRouter(prefix="/api", tags=["studio"])

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


async def save_upload(request: Request, dest: Path, max_bytes: int) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with dest.open("wb") as handle:
        async for chunk in request.stream():
            size += len(chunk)
            if size > max_bytes:
                handle.close()
                dest.unlink(missing_ok=True)
                raise ProductionError(f"Fichier trop gros (maximum {max_bytes // 2**20} Mo).")
            handle.write(chunk)
    if size == 0:
        dest.unlink(missing_ok=True)
        raise ProductionError("Fichier vide.")
    return size


# ── Voix off ──


class VoicePrefs(BaseModel):
    engine: Literal["auto", "piper", "system", "elevenlabs"] | None = None
    speed: float | None = Field(default=None, ge=0.5, le=2.0)
    enabled: bool | None = None


@router.get("/voice")
def voice_state(session: Session = Depends(get_session),
                settings: Settings = Depends(get_settings_dep)) -> dict[str, Any]:
    return {"settings": voice.voice_settings(session), "engines": voice.engines_status(settings),
            "elevenlabs_cost_per_1000_chars": settings.elevenlabs_cost_per_1000_chars}


@router.put("/voice")
def set_voice(payload: VoicePrefs, session: Session = Depends(get_session),
              settings: Settings = Depends(get_settings_dep)) -> dict[str, Any]:
    prefs = voice.voice_settings(session)
    prefs.update(payload.model_dump(exclude_none=True))
    set_value(session, "voice", prefs)
    return voice_state(session, settings)


class VoiceSample(BaseModel):
    text: str = Field(default="Bonjour ! Voici un essai de ma voix off pour mes Shorts.", min_length=2, max_length=300)


@router.post("/voice/sample")
def voice_sample(payload: VoiceSample, session: Session = Depends(get_session),
                 runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    """Essai de voix (moteurs locaux uniquement : jamais de depense pour un essai)."""
    engine = pick_engine(runtime.settings, voice.voice_settings(session)["engine"], transport=runtime.http_transport)
    if not engine.local:
        raise ProductionError("Essai réservé aux voix locales : ElevenLabs coûte de l'argent à chaque essai.")
    dest = runtime.data_dir / "samples" / "essai_voix.wav"
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        engine.synthesize(payload.text, dest, speed=float(voice.voice_settings(session).get("speed", 1.0)))
    except TTSError as exc:
        raise ProductionError(str(exc)) from exc
    return {"engine": engine.name, "url": "/api/voice/sample/file", "size": dest.stat().st_size}


@router.get("/voice/sample/file")
def voice_sample_file(runtime: Runtime = Depends(get_runtime)) -> Any:
    from fastapi.responses import FileResponse

    path = runtime.data_dir / "samples" / "essai_voix.wav"
    if not path.is_file():
        raise ProductionError("Aucun essai de voix.")
    return FileResponse(path, media_type="audio/wav")


# ── Musiques ──


class TrackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    mood: str
    license: str
    volume: float
    is_default: bool


@router.get("/music", response_model=list[TrackOut])
def list_music(session: Session = Depends(get_session)) -> list[TrackOut]:
    return [TrackOut.model_validate(t) for t in session.scalars(select(MusicTrack).order_by(MusicTrack.created_at))]


@router.put("/music/upload", response_model=TrackOut)
async def upload_music(request: Request, filename: str, title: str = "", license: str = Query(min_length=2),
                       rights_confirmed: bool = False, mood: str = "", volume: float = Query(default=0.15, ge=0, le=1),
                       session: Session = Depends(get_session),
                       settings: Settings = Depends(get_settings_dep)) -> TrackOut:
    tmp = settings.shortforge_data_dir / "tmp" / clips.safe_name(filename, "musique")
    await save_upload(request, tmp, 200 * 2**20)
    try:
        track = music.add_track(session, settings, filename=filename, content=tmp.read_bytes(), title=title,
                                license=license, rights_confirmed=rights_confirmed, mood=mood, volume=volume)
    finally:
        tmp.unlink(missing_ok=True)
    return TrackOut.model_validate(track)


class TrackPatch(BaseModel):
    is_default: bool | None = None
    volume: float | None = Field(default=None, ge=0, le=1)


@router.patch("/music/{track_id}", response_model=TrackOut)
def patch_music(track_id: str, payload: TrackPatch, session: Session = Depends(get_session)) -> TrackOut:
    track = session.get(MusicTrack, track_id)
    if track is None:
        raise ProductionError("Musique introuvable.")
    if payload.is_default is not None:
        music.set_default(session, track.id if payload.is_default else None)
    if payload.volume is not None:
        track.volume = payload.volume
    session.flush()
    return TrackOut.model_validate(track)


@router.delete("/music/{track_id}")
def delete_music(track_id: str, session: Session = Depends(get_session)) -> dict[str, bool]:
    music.delete_track(session, track_id)
    return {"deleted": True}


# ── Marque (logo, style de sous-titres par defaut) ──


class BrandIn(BaseModel):
    logo_position: Literal["haut_droite", "haut_gauche", "bas_droite", "bas_gauche"] | None = None
    logo_scale: float | None = Field(default=None, ge=0.05, le=0.5)
    logo_opacity: float | None = Field(default=None, ge=0.1, le=1)
    subtitle_preset: str | None = None
    remove_logo: bool = False


@router.get("/brand")
def get_brand(session: Session = Depends(get_session)) -> dict[str, Any]:
    brand = brand_settings(session)
    return {**brand, "has_logo": bool(brand["logo_path"]) and Path(brand["logo_path"]).is_file(),
            "logo_path": ""}


@router.put("/brand")
def set_brand(payload: BrandIn, session: Session = Depends(get_session)) -> dict[str, Any]:
    brand = brand_settings(session)
    if payload.subtitle_preset is not None and payload.subtitle_preset not in PRESETS:
        raise ProductionError("Style de sous-titres inconnu.")
    brand.update(payload.model_dump(exclude_none=True, exclude={"remove_logo"}))
    if payload.remove_logo:
        brand["logo_path"] = ""
    set_value(session, "brand", brand)
    return get_brand(session)


@router.put("/brand/logo")
async def upload_logo(request: Request, filename: str, session: Session = Depends(get_session),
                      settings: Settings = Depends(get_settings_dep)) -> dict[str, Any]:
    ext = Path(filename).suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        raise ProductionError("Logo : image PNG (de préférence avec transparence), JPG ou WebP.")
    dest = settings.shortforge_data_dir / "brand" / f"logo{ext}"
    await save_upload(request, dest, 10 * 2**20)
    brand = brand_settings(session)
    brand["logo_path"] = str(dest)
    set_value(session, "brand", brand)
    return get_brand(session)


@router.get("/brand/logo")
def logo_file(session: Session = Depends(get_session)) -> Any:
    from fastapi.responses import FileResponse

    path = Path(brand_settings(session)["logo_path"] or "-")
    if not path.is_file():
        raise ProductionError("Aucun logo.")
    return FileResponse(path)


# ── Concurrents et formats gagnants ──


class CompetitorIn(BaseModel):
    platform: Literal["youtube", "tiktok"] = "youtube"
    handle: str = Field(min_length=2, max_length=200)


class ManualVideoIn(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    views: int = Field(ge=0)
    url: str = ""
    duration_s: float = Field(default=0, ge=0, le=600)
    description: str = Field(default="", max_length=2000)


def _competitor_out(session: Session, competitor: Competitor) -> dict[str, Any]:
    videos = session.scalars(select(CompetitorVideo).where(CompetitorVideo.competitor_id == competitor.id)
                             .order_by(CompetitorVideo.ratio.desc())).all()
    return {"id": competitor.id, "platform": competitor.platform, "handle": competitor.handle,
            "title": competitor.title, "median_views": competitor.median_views,
            "last_checked_at": competitor.last_checked_at,
            "videos": [{"id": v.id, "title": v.title, "url": v.url, "views": v.views, "ratio": v.ratio,
                        "outlier": v.outlier, "duration_s": v.duration_s, "recipe": v.recipe or None,
                        "source": v.source} for v in videos]}


@router.get("/competitors")
def list_competitors(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [_competitor_out(session, c) for c in session.scalars(select(Competitor).order_by(Competitor.created_at))]


@router.post("/competitors")
def add_competitor(payload: CompetitorIn, session: Session = Depends(get_session),
                   runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    data = runtime.youtube_data() if payload.platform == "youtube" and runtime.settings.youtube_api_key else None
    competitor = growth.add_competitor(session, data, payload.platform, payload.handle)
    if data is not None:
        growth.refresh_competitor(session, data, competitor)
    return _competitor_out(session, competitor)


def _competitor(session: Session, competitor_id: str) -> Competitor:
    competitor = session.get(Competitor, competitor_id)
    if competitor is None:
        raise ProductionError("Compte suivi introuvable.")
    return competitor


@router.post("/competitors/{competitor_id}/refresh")
def refresh_competitor(competitor_id: str, session: Session = Depends(get_session),
                       runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    competitor = _competitor(session, competitor_id)
    growth.refresh_competitor(session, runtime.youtube_data(), competitor)
    return _competitor_out(session, competitor)


@router.post("/competitors/{competitor_id}/videos")
def add_competitor_video(competitor_id: str, payload: ManualVideoIn,
                         session: Session = Depends(get_session)) -> dict[str, Any]:
    competitor = _competitor(session, competitor_id)
    growth.add_manual_video(session, competitor, **payload.model_dump())
    return _competitor_out(session, competitor)


@router.delete("/competitors/{competitor_id}")
def delete_competitor(competitor_id: str, session: Session = Depends(get_session)) -> dict[str, bool]:
    session.delete(_competitor(session, competitor_id))
    return {"deleted": True}


def _video(session: Session, video_id: str) -> CompetitorVideo:
    video = session.get(CompetitorVideo, video_id)
    if video is None:
        raise ProductionError("Short introuvable.")
    return video


@router.post("/competitor-videos/{video_id}/recipe")
def video_recipe(video_id: str, session: Session = Depends(get_session),
                 runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return growth.extract_recipe(session, runtime.llm_for("analysis"), _video(session, video_id))


class FromFormatIn(BaseModel):
    niche: str = Field(default="", max_length=200)
    language: str = "fr"
    video_mode: Literal["economique", "standard", "premium", "personnalise"] = "economique"


@router.post("/competitor-videos/{video_id}/make-short")
def make_short_from_format(video_id: str, payload: FromFormatIn, request: Request,
                           session: Session = Depends(get_session),
                           runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    """« Un clic, il fabrique ton Short » : nouvelle histoire sur ce format, puis pilote automatique.

    Le clic de l'utilisateur vaut choix de l'idee ; la suite s'arrete a chaque validation humaine.
    """
    video = _video(session, video_id)
    service = build_service(request, session)
    project = service.create_project("Nouveau Short", niche=payload.niche, language=payload.language,
                                     video_mode=payload.video_mode)
    idea = growth.idea_from_format(session, runtime.llm_for("ideas"), project, video)
    project.title = idea.title[:200]
    service.skip_steps(project, [StepName.GENERATE_IDEAS], reason="Idée créée à partir d'un format gagnant.",
                       actor="utilisateur")
    service.advance(project.id)
    idea.selected = True
    service.approve(project.id, StepName.SELECT_IDEA, actor="utilisateur")
    session.commit()
    request.app.state.runner.submit(project.id, autopilot=True)
    return {"project_id": project.id, "title": idea.title, "reuse_risk": idea.reuse_risk}


# ── Style personnel ──


class StyleIn(BaseModel):
    samples: list[str] = Field(min_length=1, max_length=30)


@router.get("/style")
def get_style(session: Session = Depends(get_session)) -> dict[str, Any] | None:
    profile: dict[str, Any] | None = get_value(session, "style_profile")
    return profile


@router.post("/style/learn")
def learn_style(payload: StyleIn, session: Session = Depends(get_session),
                runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return growth.learn_style(session, runtime.llm_for("analysis"), payload.samples, "textes collés")


@router.post("/style/learn-from-videos")
def learn_style_from_videos(session: Session = Depends(get_session),
                            runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    """A partir des transcriptions de tes videos longues importees."""
    texts = [" ".join(s["text"] for s in v.transcript)[:3000]
             for v in session.scalars(select(SourceVideo).where(SourceVideo.status != "imported")) if v.transcript]
    return growth.learn_style(session, runtime.llm_for("analysis"), texts, "transcriptions de tes vidéos")


@router.put("/style/enabled")
def toggle_style(enabled: bool, session: Session = Depends(get_session)) -> dict[str, Any]:
    profile = get_value(session, "style_profile")
    if not profile:
        raise ProductionError("Aucun style appris.")
    profile = {**profile, "enabled": enabled}
    set_value(session, "style_profile", profile)
    return dict(profile)


# ── Resultats et lecons ──


class StatsIn(BaseModel):
    project_id: str
    platform: Literal["youtube", "tiktok", "instagram"]
    views: int = Field(ge=0)
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    average_view_duration_s: float = Field(default=0, ge=0)


@router.get("/performance")
def performance(session: Session = Depends(get_session)) -> dict[str, Any]:
    return {"rows": growth.performance_table(session), "insights": get_value(session, "insights")}


@router.post("/performance/manual")
def add_stats(payload: StatsIn, session: Session = Depends(get_session)) -> dict[str, Any]:
    data = payload.model_dump()
    growth.add_manual_stats(session, data.pop("project_id"), data.pop("platform"), **data)
    return performance(session)


@router.post("/performance/refresh")
def refresh_stats(session: Session = Depends(get_session), runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    count = growth.refresh_youtube_stats(session, runtime.youtube_data())
    return {"updated": count, **performance(session)}


@router.post("/performance/insights")
def insights(session: Session = Depends(get_session), runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return growth.compute_insights(session, runtime.llm_for("analysis"))


# ── Planning de la semaine et boite de validation ──


class PoolIn(BaseModel):
    niche: str = Field(default="", max_length=200)
    language: str = "fr"
    video_mode: Literal["economique", "standard", "premium", "personnalise"] = "economique"
    count: int = Field(default=7, ge=1, le=21)


class WeekIn(BaseModel):
    pool_id: str
    idea_ids: list[str] = Field(min_length=1, max_length=21)
    autopilot: bool = True


class SlotsIn(BaseModel):
    youtube: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    tiktok: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    instagram: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    days: list[int] | None = None
    per_day: int | None = Field(default=None, ge=1, le=5)


@router.get("/planning/slots")
def get_slots(session: Session = Depends(get_session)) -> dict[str, Any]:
    return planning.schedule_slots(session)


@router.put("/planning/slots")
def set_slots(payload: SlotsIn, session: Session = Depends(get_session)) -> dict[str, Any]:
    slots = planning.schedule_slots(session)
    slots.update(payload.model_dump(exclude_none=True))
    set_value(session, "schedule_slots", slots)
    return slots


@router.post("/planning/pool")
def planning_pool(payload: PoolIn, request: Request, session: Session = Depends(get_session),
                  runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    from shortforge.services.ideas import generate_ideas

    service = build_service(request, session)
    pool = planning.create_pool(service, niche=payload.niche, language=payload.language,
                                video_mode=payload.video_mode)
    result = generate_ideas(session, runtime.llm_for("ideas"), pool, trend_sources=runtime.trend_sources(session),
                            count=min(21, payload.count * 2))
    return {"pool_id": pool.id, "dates": planning.next_dates(session, payload.count),
            "ideas": [{"id": i.id, "title": i.title, "hook": i.hook, "potential_score": i.potential_score,
                       "reuse_risk": i.reuse_risk, "original_angle": i.original_angle} for i in result.ideas],
            "warnings": result.warnings}


@router.post("/planning/week")
def planning_week(payload: WeekIn, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    service = build_service(request, session)
    pool = service.get_project(payload.pool_id)
    projects = planning.create_week(session, service, pool, payload.idea_ids, actor="utilisateur")
    session.commit()
    if payload.autopilot:
        for project in projects:
            request.app.state.runner.submit(project.id, autopilot=True)
    return {"projects": [{"id": p.id, "title": p.title, "planned_for": p.planned_for} for p in projects]}


@router.post("/projects/{project_id}/autopilot")
def autopilot(project_id: str, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Enchaine les etapes automatiques jusqu'a la prochaine validation humaine."""
    build_service(request, session).get_project(project_id)
    if not request.app.state.runner.submit(project_id, autopilot=True):
        raise PipelineError("Une étape de ce projet est déjà en cours.")
    return {"detail": "Pilote automatique lancé."}


@router.get("/validations")
def validations(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return planning.pending_validations(session)


# ── Video longue → Shorts ──


def _source_out(source: SourceVideo, runner: Any) -> dict[str, Any]:
    return {"id": source.id, "title": source.title, "duration_s": source.duration_s, "status": source.status,
            "error": source.error, "segments": len(source.transcript or []), "proposals": source.proposals,
            "busy": runner.is_running(f"source:{source.id}")}


@router.get("/sources")
def list_sources(request: Request, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [_source_out(s, request.app.state.runner)
            for s in session.scalars(select(SourceVideo).order_by(SourceVideo.created_at.desc()))]


@router.put("/sources/upload")
async def upload_source(request: Request, filename: str, title: str = "", rights_confirmed: bool = False,
                        language: str = "fr", session: Session = Depends(get_session),
                        settings: Settings = Depends(get_settings_dep)) -> dict[str, Any]:
    if Path(filename).suffix.lower() not in clips.VIDEO_EXTENSIONS:
        raise ProductionError("Format vidéo non pris en charge (mp4, mov, mkv, m4v, webm ou avi).")
    if not rights_confirmed:
        raise ProductionError("Confirme que cette vidéo est la tienne ou que tu as le droit de la réutiliser.")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = settings.shortforge_data_dir / "sources" / f"{stamp}_{clips.safe_name(filename)}{Path(filename).suffix}"
    await save_upload(request, dest, 20 * 2**30)
    source = clips.register_source(session, settings, dest, title=title or Path(filename).stem,
                                   rights_confirmed=True, language=language)
    return _source_out(source, request.app.state.runner)


def _source(session: Session, source_id: str) -> SourceVideo:
    source = session.get(SourceVideo, source_id)
    if source is None:
        raise ProductionError("Vidéo introuvable.")
    return source


@router.post("/sources/{source_id}/analyse")
def analyse_source(source_id: str, request: Request, count: int = Query(default=5, ge=1, le=10),
                   session: Session = Depends(get_session), runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    """Transcription (si besoin) puis choix des meilleurs passages, en arriere-plan."""
    source = _source(session, source_id)
    db = request.app.state.db

    def task() -> None:
        with db.session() as task_session:
            item = task_session.get(SourceVideo, source_id)
            if item is None:
                return
            try:
                if not item.transcript:
                    clips.transcribe_source(task_session, runtime.get_transcriber(), item)
                clips.propose_clips(task_session, runtime.llm_for("analysis"), item, count)
            except Exception as exc:  # garde l'erreur pour l'afficher
                item.status, item.error = "failed", str(exc)

    if not request.app.state.runner.submit_task(f"source:{source.id}", task):
        raise ProductionError("Analyse déjà en cours.")
    return {"detail": "Analyse lancée."}


class ClipsIn(BaseModel):
    indexes: list[int] = Field(min_length=1, max_length=10)
    autopilot: bool = True


@router.post("/sources/{source_id}/clips")
def create_clips(source_id: str, payload: ClipsIn, request: Request,
                 session: Session = Depends(get_session)) -> dict[str, Any]:
    source = _source(session, source_id)
    projects = clips.create_clip_projects(session, build_service(request, session), source, payload.indexes,
                                          actor="utilisateur")
    session.commit()
    if payload.autopilot:
        for project in projects:
            request.app.state.runner.submit(project.id, autopilot=True)
    return {"projects": [{"id": p.id, "title": p.title} for p in projects]}


@router.delete("/sources/{source_id}")
def delete_source(source_id: str, session: Session = Depends(get_session)) -> dict[str, bool]:
    source = _source(session, source_id)
    Path(source.path).unlink(missing_ok=True)
    session.delete(source)
    return {"deleted": True}


# ── Publications par plateforme ──


class PostPatch(BaseModel):
    caption: str | None = Field(default=None, max_length=5000)
    enabled: bool | None = None
    scheduled_at: datetime | None = None
    clear_schedule: bool = False


def _post_out(post: SocialPost) -> dict[str, Any]:
    return {"id": post.id, "platform": post.platform, "label": social.LABELS[post.platform], "enabled": post.enabled,
            "caption": post.caption, "scheduled_at": post.scheduled_at, "method": post.method, "status": post.status,
            "external_id": post.external_id, "error": post.error}


@router.get("/projects/{project_id}/posts")
def list_posts(project_id: str, request: Request, session: Session = Depends(get_session),
               settings: Settings = Depends(get_settings_dep)) -> list[dict[str, Any]]:
    project = build_service(request, session).get_project(project_id)
    return [_post_out(p) for p in social.ensure_posts(session, settings, project)]


@router.patch("/posts/{post_id}")
def patch_post(post_id: str, payload: PostPatch, session: Session = Depends(get_session)) -> dict[str, Any]:
    post = session.get(SocialPost, post_id)
    if post is None:
        raise ProductionError("Publication introuvable.")
    changes = payload.model_dump(exclude_unset=True, exclude={"clear_schedule"})
    if payload.clear_schedule:
        changes["scheduled_at"] = None
    return _post_out(social.update_post(session, post, changes))


class ManualDone(BaseModel):
    url: str = Field(default="", max_length=300)


@router.post("/posts/{post_id}/exported")
def post_exported(post_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    post = session.get(SocialPost, post_id)
    if post is None:
        raise ProductionError("Publication introuvable.")
    return _post_out(social.mark_exported(session, post))


@router.post("/posts/{post_id}/published")
def post_published(post_id: str, payload: ManualDone, session: Session = Depends(get_session)) -> dict[str, Any]:
    post = session.get(SocialPost, post_id)
    if post is None:
        raise ProductionError("Publication introuvable.")
    return _post_out(social.mark_published(session, post, payload.url))


@router.post("/projects/{project_id}/finish-manual")
def finish_manual(project_id: str, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Terminer sans publication automatique : tu publies toi-meme (rien n'est envoye par l'application)."""
    from shortforge.services.render import latest_render

    service = build_service(request, session)
    project = service.get_project(project_id)
    final = latest_render(session, project.id)
    if final is None or final.approved_at is None:
        raise PipelineError("Valide d'abord le rendu final.")
    service.finish_without_publishing(project, actor="utilisateur")
    return {"status": project.status}


@router.get("/postiz/integrations")
def postiz_integrations(runtime: Runtime = Depends(get_runtime)) -> list[dict[str, Any]]:
    from shortforge.integrations.postiz import PostizError

    try:
        return [{"id": i.get("id"), "name": i.get("name"), "platform": i.get("providerIdentifier")}
                for i in runtime.postiz().integrations()]
    except PostizError as exc:
        raise ProductionError(str(exc)) from exc


# ── Assistant de premier lancement ──


@router.get("/onboarding")
def onboarding(session: Session = Depends(get_session), runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    import sys

    from shortforge.media import MediaToolError, ffmpeg_path

    settings = runtime.settings
    try:
        ffmpeg_ok = bool(ffmpeg_path(settings))
    except MediaToolError:
        ffmpeg_ok = False
    llm_ok = bool(getattr(runtime.llm, "is_running", lambda: False)())
    engines = voice.engines_status(settings)
    env_file = getattr(settings, "model_config", {}).get("env_file")
    steps = [
        {"id": "ffmpeg", "label": "FFmpeg (montage)", "ok": ffmpeg_ok,
         "help": "brew install ffmpeg" if sys.platform == "darwin" else "winget install Gyan.FFmpeg"},
        {"id": "ollama", "label": "Ollama (idées et scripts)", "ok": llm_ok and bool(settings.ollama_model),
         "help": "Installe Ollama (ollama.com), télécharge un modèle puis renseigne OLLAMA_MODEL."},
        {"id": "comfyui", "label": "ComfyUI (images et vidéos locales)", "ok": runtime.comfy.is_running(),
         "help": "Lance ComfyUI Desktop (comfy.org). Facultatif si tu utilises seulement des moteurs en ligne."},
        {"id": "voice", "label": "Voix off", "ok": any(e["available"] and e["local"] for e in engines),
         "help": "La voix du système marche sans rien installer ; Piper donne une voix plus naturelle."},
        {"id": "whisper", "label": "Transcription (vidéos longues, sous-titres précis)",
         "ok": runtime.get_transcriber().available(), "help": "Facultatif : pip install faster-whisper."},
    ]
    return {"steps": steps, "done": bool(get_value(session, "onboarding_done", False)),
            "data_dir": str(settings.shortforge_data_dir.resolve()), "env_file": str(env_file or ".env"),
            "platform": sys.platform, "free_space_gb": round(shutil.disk_usage(settings.shortforge_data_dir).free
                                                             / 2**30, 1)}


@router.post("/onboarding/done")
def onboarding_done(session: Session = Depends(get_session)) -> dict[str, bool]:
    set_value(session, "onboarding_done", True)
    return {"done": True}


@router.get("/ideas/{idea_id}")
def get_idea(idea_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    idea = session.get(Idea, idea_id)
    if idea is None:
        raise ProductionError("Idée introuvable.")
    project = session.get(Project, idea.project_id) if idea.project_id else None
    return {"id": idea.id, "title": idea.title, "project_title": project.title if project else ""}
