"""Rendu final, sous-titres, brouillon YouTube, verification finale et connexion de la chaine."""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.deps import build_service, get_runtime, get_session, get_settings_dep
from shortforge.models import Subtitle
from shortforge.runtime import Runtime
from shortforge.services import render as render_service
from shortforge.services import subtitles as subs
from shortforge.services import youtube
from shortforge.services.safety import content_issues

router = APIRouter(prefix="/api", tags=["publication"])


class RenderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    asset_id: str | None
    width: int
    height: int
    codec: str
    status: str
    approved_at: datetime | None
    approved_by: str | None
    created_at: datetime


class SubtitleStyle(BaseModel):
    preset: str | None = None
    position: Literal["bottom", "middle", "top"] | None = None
    style: dict[str, Any] | None = None


class DraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str
    tags: list[str]
    privacy: str
    made_for_kids: bool
    ai_disclosure: bool
    status: str
    youtube_video_id: str | None
    error: str | None
    human_approved_by: str | None


class DraftEdit(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=5000)
    tags: list[str] | None = Field(default=None, max_length=30)
    privacy: Literal["private", "unlisted", "public"] | None = None
    made_for_kids: bool | None = None


@router.get("/projects/{project_id}/render", response_model=RenderOut | None)
def get_render(project_id: str, session: Session = Depends(get_session)) -> RenderOut | None:
    render = render_service.latest_render(session, project_id)
    return RenderOut.model_validate(render) if render else None


@router.get("/subtitle-presets")
def subtitle_presets() -> dict[str, Any]:
    return {"presets": subs.presets_list(), "effects": subs.EFFECTS}


@router.get("/projects/{project_id}/subtitles")
def get_subtitles(project_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    subtitle = render_service.current_subtitle(session, project_id)
    style = render_service.subtitle_style(session, subtitle)
    return {"segments": subtitle.segments if subtitle else [], "position": style["position"],
            "preset": style["preset"], "style": style}


@router.put("/projects/{project_id}/subtitles")
def set_subtitle_style(project_id: str, payload: SubtitleStyle, request: Request,
                       session: Session = Depends(get_session)) -> dict[str, Any]:
    """Style des sous-titres (applique au prochain montage)."""
    build_service(request, session).get_project(project_id)
    subtitle = render_service.current_subtitle(session, project_id)
    if subtitle is None:
        subtitle = Subtitle(project_id=project_id, style={})
        session.add(subtitle)
    style = dict(subtitle.style or {})
    if payload.preset is not None:
        if payload.preset not in subs.PRESETS:
            raise youtube.YouTubeError("Style de sous-titres inconnu.")
        style = {"preset": payload.preset}  # un nouveau style repart de ses propres reglages
    if payload.position:
        style["position"] = payload.position
        subtitle.position = payload.position
    if payload.style is not None:
        style.update({k: v for k, v in payload.style.items() if k in subs.EDITABLE})
    subtitle.style = style
    session.flush()
    return get_subtitles(project_id, session)


@router.get("/projects/{project_id}/youtube-draft", response_model=DraftOut | None)
def get_draft(project_id: str, session: Session = Depends(get_session)) -> DraftOut | None:
    draft = youtube.current_draft(session, project_id)
    return DraftOut.model_validate(draft) if draft else None


@router.put("/projects/{project_id}/youtube-draft", response_model=DraftOut)
def edit_draft(project_id: str, payload: DraftEdit, session: Session = Depends(get_session),
               settings: Settings = Depends(get_settings_dep)) -> DraftOut:
    changes = payload.model_dump(exclude_none=True)
    if "tags" in changes:
        changes["tags"] = [t.strip()[:100] for t in changes["tags"] if t.strip()]
    text = " ".join([changes.get("title", ""), changes.get("description", "")])
    issues = content_issues(text)
    if issues:
        raise youtube.YouTubeError("Texte refusé : " + ", ".join(issues) + ".")
    return DraftOut.model_validate(youtube.update_draft(session, settings, project_id, changes))


@router.get("/projects/{project_id}/final-check")
def final_check(project_id: str, request: Request, session: Session = Depends(get_session),
                settings: Settings = Depends(get_settings_dep)) -> dict[str, Any]:
    """Verification finale avant publication (lecture seule : ne declenche rien)."""
    project = build_service(request, session).get_project(project_id)
    return youtube.checks_as_dict(youtube.final_checks(session, settings, project))


@router.get("/youtube/status")
def youtube_status(session: Session = Depends(get_session),
                   settings: Settings = Depends(get_settings_dep)) -> dict[str, Any]:
    channel = youtube.default_channel(session)
    return {"publish_enabled": settings.youtube_publish_enabled,
            "client_secrets_configured": bool(settings.youtube_client_secrets_file),
            "channel": {"id": channel.channel_id, "title": channel.title} if channel else None,
            "ai_disclosure_text": settings.ai_disclosure_text}


@router.post("/youtube/connect")
def youtube_connect(runtime: Runtime = Depends(get_runtime)) -> dict[str, str]:
    """Adresse de connexion Google a ouvrir dans le navigateur (lecture de la chaine et envoi de videos)."""
    return {"url": runtime.youtube.authorization_url()}


@router.get("/youtube/oauth/callback", response_class=HTMLResponse)
def youtube_callback(code: str = Query(default=""), state: str = Query(default=""), error: str = Query(default=""),
                     session: Session = Depends(get_session), runtime: Runtime = Depends(get_runtime)) -> HTMLResponse:
    if error or not code:
        return _page("Connexion annulée", f"Google a répondu : {escape(error or 'aucun code reçu')}.")
    try:
        channel = runtime.youtube.finish_authorization(session, code, state)
    except youtube.YouTubeError as exc:
        return _page("Connexion impossible", escape(str(exc)))
    return _page("Chaîne connectée", f"ShortForge peut envoyer des vidéos sur « {escape(channel.title)} ». "
                 "La publication reste soumise à ta validation. Tu peux fermer cette page.")


def _page(title: str, message: str) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><html lang='fr'><meta charset='utf-8'><title>{title}</title>"
                        f"<body style='font-family:sans-serif;background:#09090b;color:#f4f4f5;padding:3rem'>"
                        f"<h1>{title}</h1><p>{message}</p></body></html>")
