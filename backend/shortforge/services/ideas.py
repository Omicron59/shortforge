"""Generation d'idees de Shorts avec le modele de texte local."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from shortforge.integrations.ollama import LLMClient, LLMError
from shortforge.integrations.trends import Trend, TrendSource, collect_trends
from shortforge.models import Idea, Project
from shortforge.services.safety import best_match, content_issues, reuse_risk

DUPLICATE_THRESHOLD = 0.8

SYSTEM_PROMPT = """Tu es un auteur de YouTube Shorts (8 à 60 secondes, format vertical).
Tu proposes des idées ORIGINALES. Les tendances fournies servent seulement d'inspiration :
ne recopie jamais un titre ou une vidéo existante, trouve un angle personnel.
Interdits : violence, sexe, haine, contenu illégal ou trompeur, personnes réelles,
conseils médicaux, juridiques ou financiers personnalisés.
Réponds uniquement en JSON."""

PROMPT_TEMPLATE = """Niche : {niche}
Langue des Shorts : {language}
Tendances du moment (inspiration uniquement) :
{trends}
Sujets déjà traités (à ne pas refaire) :
{history}

Propose {count} idées. Format JSON exact :
{{"ideas": [{{"title": "...", "hook": "phrase d'accroche des 2 premières secondes",
"original_angle": "ce qui rend l'idée originale", "estimated_duration_s": 30,
"potential_score": 0-100, "keywords": ["..."], "visual_style": "style visuel conseillé",
"inspired_by": "tendance d'inspiration ou vide"}}]}}"""


class IdeaDraft(BaseModel):
    """Une idee telle que renvoyee par le modele, validee."""

    title: str = Field(min_length=3, max_length=200)
    hook: str = Field(default="", max_length=500)
    original_angle: str = Field(default="", max_length=1000)
    estimated_duration_s: float = Field(default=30, ge=5, le=180)
    potential_score: float = Field(default=50)
    keywords: list[str] = Field(default_factory=list)
    visual_style: str = Field(default="", max_length=500)
    inspired_by: str = ""

    @field_validator("potential_score", mode="before")
    @classmethod
    def _clamp_score(cls, value: Any) -> float:
        try:
            return max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            return 50.0

    @field_validator("estimated_duration_s", mode="before")
    @classmethod
    def _clamp_duration(cls, value: Any) -> float:
        try:
            return max(5.0, min(180.0, float(value)))
        except (TypeError, ValueError):
            return 30.0

    @field_validator("keywords", mode="before")
    @classmethod
    def _keywords(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            value = value.split(",")
        return [str(k).strip() for k in (value or []) if str(k).strip()][:10]


@dataclass(slots=True)
class IdeaResult:
    ideas: list[Idea]
    rejected: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def previous_subjects(session: Session, exclude_project: str | None = None) -> list[str]:
    """Titres des idees retenues et des projets deja crees : l'historique a ne pas repeter."""
    titles = list(session.scalars(select(Project.title).where(Project.id != (exclude_project or ""))))
    titles += list(session.scalars(select(Idea.title).where(Idea.selected.is_(True))))
    return sorted({t for t in titles if t})


def generate_ideas(session: Session, llm: LLMClient, project: Project, *, trend_sources: list[TrendSource],
                   count: int = 8) -> IdeaResult:
    """Demande des idees au modele, filtre les doublons et les contenus interdits, et les enregistre."""
    trends, warnings = collect_trends(trend_sources, project.niche, project.language)
    history = previous_subjects(session, exclude_project=project.id)
    prompt = PROMPT_TEMPLATE.format(
        niche=project.niche or "générale", language=project.language, count=count,
        trends=_bullets([t.title for t in trends[:30]]), history=_bullets(history[-50:]),
    )
    raw = llm.generate_json(SYSTEM_PROMPT, prompt)
    items = raw.get("ideas")
    if not isinstance(items, list) or not items:
        raise LLMError("Le modèle n'a proposé aucune idée exploitable.")

    result = IdeaResult(ideas=[], warnings=warnings)
    known = list(history) + [i.title for i in session.scalars(select(Idea).where(Idea.project_id == project.id))]
    trend_titles = [t.title for t in trends]
    for item in items:
        try:
            draft = IdeaDraft.model_validate(item)
        except ValidationError:
            result.rejected.append("idée mal formée")
            continue
        text = " ".join([draft.title, draft.hook, draft.original_angle])
        if issues := content_issues(text):
            result.rejected.append(f"« {draft.title} » : {', '.join(issues)}")
            continue
        dup_score, dup_of = best_match(draft.title, known)
        if dup_score >= DUPLICATE_THRESHOLD:
            result.rejected.append(f"« {draft.title} » : doublon de « {dup_of} »")
            continue
        trend_score, _ = best_match(f"{draft.title} {draft.hook}", trend_titles)
        title_score, _ = best_match(draft.title, trend_titles)
        idea = Idea(
            project_id=project.id, title=draft.title, hook=draft.hook, original_angle=draft.original_angle,
            estimated_duration_s=draft.estimated_duration_s, potential_score=draft.potential_score,
            keywords=draft.keywords, visual_style=draft.visual_style,
            reuse_risk=reuse_risk(max(trend_score, title_score)),
            sources=_sources_for(draft.inspired_by, trends),
        )
        session.add(idea)
        known.append(draft.title)
        result.ideas.append(idea)
    session.flush()
    if not result.ideas:
        raise LLMError("Toutes les idées proposées ont été écartées : " + " ; ".join(result.rejected))
    return result


def select_idea(session: Session, project_id: str, idea_id: str) -> Idea:
    """Marque une idee comme choisie (une seule par projet)."""
    ideas = list(session.scalars(select(Idea).where(Idea.project_id == project_id)))
    chosen = next((i for i in ideas if i.id == idea_id), None)
    if chosen is None:
        raise ValueError("Idée introuvable pour ce projet.")
    for idea in ideas:
        idea.selected = idea.id == idea_id
    session.flush()
    return chosen


def selected_idea(session: Session, project_id: str) -> Idea | None:
    return session.scalars(select(Idea).where(Idea.project_id == project_id, Idea.selected.is_(True))).first()


def _bullets(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines) if lines else "- (aucun)"


def _sources_for(inspired_by: str, trends: list[Trend]) -> list[str]:
    if not inspired_by:
        return []
    score, title = best_match(inspired_by, [t.title for t in trends])
    if score < 0.5:
        return [json.dumps({"title": inspired_by[:200], "source": "modèle"}, ensure_ascii=False)]
    trend = next(t for t in trends if t.title == title)
    return [json.dumps({"title": trend.title, "source": trend.source, "url": trend.url}, ensure_ascii=False)]
