"""Planning de la semaine : un lot d'idees, tu choisis, ShortForge prepare chaque Short jusqu'a ta validation.

Les Shorts avancent tout seuls (« pilote automatique ») mais s'arretent a chaque validation
humaine (script, depense, apercu, rendu final, publication). Rien n'est publie sans toi.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from shortforge.models import Idea, PipelineStep, Project
from shortforge.pipeline.engine import PipelineService
from shortforge.pipeline.steps import DEFINITIONS, StepName
from shortforge.services.app_settings import get_value
from shortforge.services.ideas import select_idea
from shortforge.services.production import ProductionError

PLATFORMS = ("youtube", "tiktok", "instagram")
DEFAULT_SLOTS: dict[str, Any] = {"youtube": "12:00", "tiktok": "12:00", "instagram": "08:30",
                                 "days": [0, 1, 2, 3, 4, 5, 6], "per_day": 1}


class PlanningError(ProductionError):
    """Erreur de planning ; le message est destine a l'utilisateur."""


def schedule_slots(session: Session) -> dict[str, Any]:
    return {**DEFAULT_SLOTS, **(get_value(session, "schedule_slots", {}) or {})}


def to_utc(local: datetime) -> datetime:
    """Heure locale de l'ordinateur → UTC sans fuseau (format de toutes les dates en base)."""
    aware = local if local.tzinfo else local.astimezone()
    return aware.astimezone(UTC).replace(tzinfo=None)


def to_local(utc: datetime) -> datetime:
    return utc.replace(tzinfo=UTC).astimezone().replace(tzinfo=None)


def next_dates(session: Session, count: int, start: datetime | None = None) -> list[datetime]:
    """Prochains jours de publication, un ou plusieurs Shorts par jour.

    Les creneaux sont en heure locale de l'ordinateur ; les dates renvoyees sont en UTC.
    `start` est une heure locale (maintenant par defaut).
    """
    slots = schedule_slots(session)
    days = set(slots.get("days") or range(7))
    per_day = max(1, int(slots.get("per_day", 1)))
    hour, minute = (int(x) for x in str(slots.get("youtube", "12:00")).split(":"))
    day = (start or datetime.now()).replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=1)
    dates: list[datetime] = []
    while len(dates) < count:
        if day.weekday() in days:
            dates += [to_utc(day)] * min(per_day, count - len(dates))
        day += timedelta(days=1)
    return dates


def create_pool(service: PipelineService, *, niche: str, language: str, video_mode: str) -> Project:
    """Projet « reserve d'idees » de la semaine (n'apparait pas dans la liste des Shorts)."""
    project = service.create_project(f"Idées de la semaine — {niche or 'générale'}", niche=niche,
                                     language=language, video_mode=video_mode)
    project.source = "plan"
    service.session.flush()
    return project


def create_week(session: Session, service: PipelineService, pool: Project, idea_ids: list[str], *,
                actor: str, dates: list[datetime] | None = None) -> list[Project]:
    """Un Short par idee choisie : l'idee est deja choisie (ton clic), la suite avance toute seule."""
    if pool.source != "plan":
        raise PlanningError("Ce projet n'est pas une réserve d'idées.")
    ideas = [session.get(Idea, i) for i in idea_ids]
    if not idea_ids or any(i is None or i.project_id != pool.id for i in ideas):
        raise PlanningError("Choisis des idées de cette réserve.")
    dates = dates or next_dates(session, len(ideas))
    projects = []
    for idea, when in zip(ideas, dates, strict=False):
        assert idea is not None
        project = service.create_project(idea.title, niche=pool.niche, language=pool.language,
                                         video_mode=pool.video_mode)
        project.planned_for = when
        copy = Idea(project_id=project.id, title=idea.title, hook=idea.hook, original_angle=idea.original_angle,
                    estimated_duration_s=idea.estimated_duration_s, potential_score=idea.potential_score,
                    keywords=list(idea.keywords), reuse_risk=idea.reuse_risk, visual_style=idea.visual_style,
                    sources=list(idea.sources))
        session.add(copy)
        session.flush()
        service.skip_steps(project, [StepName.GENERATE_IDEAS], reason="Idée choisie dans le planning de la semaine.",
                           actor=actor)
        service.advance(project.id)  # choix de l'idee -> en attente de validation
        select_idea(session, project.id, copy.id)
        service.approve(project.id, StepName.SELECT_IDEA, actor=actor)
        idea.selected = True
        projects.append(project)
    session.flush()
    return projects


def pending_validations(session: Session) -> list[dict[str, Any]]:
    """Boite de validation : toutes les decisions qui t'attendent, tous projets confondus."""
    rows = session.execute(select(PipelineStep, Project).join(Project, Project.id == PipelineStep.project_id)
                           .where(PipelineStep.status == "needs_validation", Project.source != "plan",
                                  Project.archived_at.is_(None))
                           .order_by(Project.planned_for, PipelineStep.updated_at)).all()
    items = []
    for step, project in rows:
        output = step.output or {}
        kind = "depense" if output.get("confirmation_required") else {
            "select_idea": "idee", "approve_script": "script", "review_preview": "apercu",
            "approve_final_render": "rendu_final", "publish": "publication"}.get(step.name, "autre")
        items.append({"project_id": project.id, "project_title": project.title, "step": step.name,
                      "label": DEFINITIONS[StepName(step.name)].label, "kind": kind,
                      "message": output.get("message", ""), "planned_for": project.planned_for,
                      "since": step.updated_at})
    return items
