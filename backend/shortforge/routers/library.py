"""Fichiers generes, file de production, historique et statistiques (lecture seule, pour l'interface)."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.deps import get_session, get_settings_dep
from shortforge.models import Asset, Cost, Idea, PipelineStep, Project, ProviderJob, Scene
from shortforge.pipeline.steps import DEFINITIONS, StepName

router = APIRouter(prefix="/api", tags=["bibliotheque"])


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    scene_id: str | None
    kind: str
    mime_type: str
    origin: str
    created_at: datetime


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider_id: str
    project_id: str
    scene_id: str | None
    operation: str
    status: str
    estimated_cost_usd: float
    error: str | None
    created_at: datetime
    updated_at: datetime


@router.get("/projects/{project_id}/assets", response_model=list[AssetOut])
def list_assets(project_id: str, kind: str | None = None,
                session: Session = Depends(get_session)) -> list[AssetOut]:
    query = select(Asset).where(Asset.project_id == project_id)
    if kind:
        query = query.where(Asset.kind == kind)
    return [AssetOut.model_validate(a) for a in session.scalars(query.order_by(Asset.created_at))]


@router.get("/assets/{asset_id}/file")
def asset_file(asset_id: str, session: Session = Depends(get_session),
               settings: Settings = Depends(get_settings_dep)) -> FileResponse:
    """Sert un fichier genere. Seuls les fichiers du dossier de donnees sont accessibles."""
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Fichier introuvable.")
    path = Path(asset.path).resolve()
    root = settings.shortforge_data_dir.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable.")
    return FileResponse(path, media_type=asset.mime_type or None)


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(project_id: str | None = None, limit: int = Query(default=100, ge=1, le=500),
              session: Session = Depends(get_session)) -> list[JobOut]:
    query = select(ProviderJob)
    if project_id:
        query = query.where(ProviderJob.project_id == project_id)
    jobs = session.scalars(query.order_by(ProviderJob.created_at.desc()).limit(limit))
    return [JobOut.model_validate(j) for j in jobs]


@router.get("/history")
def history(limit: int = Query(default=200, ge=1, le=1000), project_id: str | None = None,
            session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    """Journal : etapes terminees, validations, echecs et depenses, du plus recent au plus ancien."""
    titles: dict[str, str] = {pid: title for pid, title in session.execute(select(Project.id, Project.title))}
    events: list[dict[str, Any]] = []
    steps = select(PipelineStep).where(PipelineStep.started_at.is_not(None) | PipelineStep.validated_at.is_not(None))
    if project_id:
        steps = steps.where(PipelineStep.project_id == project_id)
    for step in session.scalars(steps):
        label = DEFINITIONS[StepName(step.name)].label
        when = step.validated_at or step.finished_at or step.started_at
        events.append({"at": when, "type": f"step_{step.status}", "project_id": step.project_id,
                       "project_title": titles.get(step.project_id, ""), "label": label,
                       "detail": step.error or (f"validé par {step.validated_by}" if step.validated_by else ""),
                       "amount_usd": None})
    costs = select(Cost)
    if project_id:
        costs = costs.where(Cost.project_id == project_id)
    for cost in session.scalars(costs):
        events.append({"at": cost.created_at, "type": f"cost_{cost.kind}", "project_id": cost.project_id,
                       "project_title": titles.get(cost.project_id or "", ""),
                       "label": "Dépense" if cost.kind == "actual" else "Confirmation de dépense",
                       "detail": cost.description, "amount_usd": cost.amount_usd})
    events.sort(key=lambda e: e["at"] or datetime.min, reverse=True)
    return events[:limit]


@router.get("/stats")
def stats(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Chiffres de production. Les statistiques YouTube arriveront avec la publication."""
    projects = Counter(session.scalars(select(Project.status)))
    jobs = Counter(session.scalars(select(ProviderJob.status)))
    spent_by_provider: dict[str, float] = defaultdict(float)
    spent_by_month: dict[str, float] = defaultdict(float)
    for cost in session.scalars(select(Cost).where(Cost.kind == "actual")):
        spent_by_provider[cost.provider_id or "inconnu"] += cost.amount_usd
        spent_by_month[cost.created_at.strftime("%Y-%m")] += cost.amount_usd
    scenes_by_provider = Counter(session.scalars(select(Scene.provider_id).where(Scene.provider_id.is_not(None))))

    def count(model: type[Any]) -> int:
        return session.scalar(select(func.count()).select_from(model)) or 0

    return {
        "projects_total": sum(projects.values()),
        "projects_by_status": dict(projects),
        "ideas_total": count(Idea),
        "scenes_total": count(Scene),
        "images_total": session.scalar(select(func.count()).where(Asset.kind == "image")) or 0,
        "videos_total": session.scalar(select(func.count()).where(Asset.kind == "video")) or 0,
        "jobs_by_status": dict(jobs),
        "scenes_by_provider": dict(scenes_by_provider),
        "spent_total_usd": round(sum(spent_by_provider.values()), 4),
        "spent_by_provider": {k: round(v, 4) for k, v in spent_by_provider.items()},
        "spent_by_month": {k: round(v, 4) for k, v in sorted(spent_by_month.items())},
        "youtube": {"available": False, "message": "Les statistiques YouTube arriveront avec la publication."},
    }
