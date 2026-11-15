"""Croissance : concurrents et formats gagnants, style d'ecriture personnel, analyse des resultats.

Regle du projet : on s'inspire du FORMAT d'un Short qui marche (type d'accroche, structure,
rythme, chute), jamais de son contenu. Aucune video n'est telechargee : seuls le titre, la
description, la duree et les vues publiques sont lus. Chaque idee tiree d'un format est comparee
au Short d'origine et ecartee si elle lui ressemble trop.
"""

from __future__ import annotations

import json
import statistics
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from shortforge.integrations.ollama import LLMClient, LLMError
from shortforge.integrations.youtube_data import YouTubeData
from shortforge.models import Analytics, Competitor, CompetitorVideo, Idea, Project, PublishJob, SocialPost, utcnow
from shortforge.services.app_settings import get_value, set_value
from shortforge.services.ideas import IdeaDraft
from shortforge.services.production import ProductionError
from shortforge.services.safety import best_match, content_issues, reuse_risk
from shortforge.services.scripts import current_script

MAX_COMPETITORS = 5
OUTLIER_RATIO = 2.0
MAX_SHORT_S = 180


class GrowthError(ProductionError):
    """Erreur de suivi ou d'analyse ; le message est destine a l'utilisateur."""


# ── Concurrents ──


def add_competitor(session: Session, data: YouTubeData | None, platform: str, handle: str) -> Competitor:
    if session.query(Competitor).count() >= MAX_COMPETITORS:
        raise GrowthError(f"Tu suis déjà {MAX_COMPETITORS} comptes : retires-en un avant d'en ajouter.")
    platform = platform.lower()
    if platform not in ("youtube", "tiktok"):
        raise GrowthError("Plateforme inconnue : youtube ou tiktok.")
    competitor = Competitor(platform=platform, handle=handle.strip(), title=handle.strip())
    if platform == "youtube" and data is not None:
        info = data.channel(handle)
        competitor.channel_id, competitor.title = info["id"], info["title"]
    session.add(competitor)
    session.flush()
    return competitor


def refresh_competitor(session: Session, data: YouTubeData, competitor: Competitor) -> dict[str, Any]:
    """Recupere les derniers Shorts d'une chaine YouTube et repere ceux qui font 2x sa mediane."""
    if competitor.platform != "youtube":
        raise GrowthError("TikTok n'offre pas d'accès public aux vidéos d'un compte : ajoute ses Shorts à la main.")
    info = data.channel(competitor.channel_id or competitor.handle)
    videos = [v for v in data.recent_videos(info["uploads"]) if 0 < v["duration_s"] <= MAX_SHORT_S]
    for video in videos:
        row = session.scalars(select(CompetitorVideo).where(CompetitorVideo.competitor_id == competitor.id,
                                                            CompetitorVideo.external_id == video["id"])).first()
        if row is None:
            row = CompetitorVideo(competitor_id=competitor.id, external_id=video["id"])
            session.add(row)
        row.title, row.description = video["title"][:300], video["description"][:2000]
        row.url, row.duration_s, row.views = video["url"], video["duration_s"], video["views"]
        row.published_at = video["published_at"]
    competitor.last_checked_at = utcnow()
    session.flush()
    return update_outliers(session, competitor)


def add_manual_video(session: Session, competitor: Competitor, *, title: str, views: int, url: str = "",
                     duration_s: float = 0, description: str = "") -> CompetitorVideo:
    """Saisie a la main (TikTok, ou YouTube sans cle API) : titre, vues et duree visibles publiquement."""
    row = CompetitorVideo(competitor_id=competitor.id, external_id=f"manuel-{utcnow().timestamp():.0f}-{views}",
                          title=title.strip()[:300], description=description[:2000], url=url.strip(),
                          duration_s=duration_s, views=max(0, views), source="manuel")
    session.add(row)
    session.flush()
    update_outliers(session, competitor)
    return row


def update_outliers(session: Session, competitor: Competitor) -> dict[str, Any]:
    videos = list(session.scalars(select(CompetitorVideo).where(CompetitorVideo.competitor_id == competitor.id)))
    median = statistics.median([v.views for v in videos]) if videos else 0
    competitor.median_views = float(median)
    for video in videos:
        video.ratio = round(video.views / median, 2) if median else 0
        video.outlier = median > 0 and video.ratio >= OUTLIER_RATIO
    session.flush()
    return {"videos": len(videos), "median_views": median, "outliers": sum(v.outlier for v in videos)}


RECIPE_SYSTEM = """Tu analyses le FORMAT d'un Short qui a bien marché, pas son contenu.
Tu décris de façon abstraite : type d'accroche, structure en étapes, rythme, type de chute,
pourquoi le format retient l'attention. Ne recopie aucune phrase, aucun nom, aucune histoire.
Réponds uniquement en JSON."""

RECIPE_PROMPT = """Short de la chaîne « {channel} » :
Titre : {title}
Description (extrait) : {description}
Durée : {duration} s ; vues : {views} ({ratio}x la médiane de la chaîne).
Format JSON exact :
{{"hook_type": "...", "structure": ["étape 1", "étape 2", "..."], "pacing": "...", "ending": "...",
"why_it_works": "...", "duration_s": 30}}"""


def extract_recipe(session: Session, llm: LLMClient, video: CompetitorVideo) -> dict[str, Any]:
    competitor = session.get(Competitor, video.competitor_id)
    raw = llm.generate_json(RECIPE_SYSTEM, RECIPE_PROMPT.format(
        channel=competitor.title if competitor else "", title=video.title, description=video.description[:500],
        duration=round(video.duration_s or 30), views=video.views, ratio=video.ratio))
    structure = raw.get("structure")
    if not isinstance(structure, list) or not structure:
        raise LLMError("Le modèle n'a pas su décrire ce format.")
    recipe = {"hook_type": str(raw.get("hook_type", ""))[:300], "structure": [str(s)[:200] for s in structure[:8]],
              "pacing": str(raw.get("pacing", ""))[:300], "ending": str(raw.get("ending", ""))[:300],
              "why_it_works": str(raw.get("why_it_works", ""))[:500],
              "duration_s": float(raw.get("duration_s") or video.duration_s or 30)}
    video.recipe = recipe
    session.flush()
    return recipe


IDEA_FROM_FORMAT_SYSTEM = """Tu crées une idée de Short ORIGINALE pour la niche donnée, en réutilisant
seulement un format (accroche, structure, rythme, chute). L'histoire, le sujet, les phrases et les
personnages doivent être entièrement nouveaux. Interdits : violence, sexe, haine, contenu illégal
ou trompeur, personnes réelles, conseils médicaux, juridiques ou financiers personnalisés.
Réponds uniquement en JSON."""

IDEA_FROM_FORMAT_PROMPT = """Niche : {niche}
Langue : {language}
Format à suivre : accroche « {hook_type} » ; étapes : {structure} ; rythme : {pacing} ; chute : {ending}.
{insights}
Format JSON exact :
{{"title": "...", "hook": "...", "original_angle": "...", "estimated_duration_s": {duration},
"potential_score": 0-100, "keywords": ["..."], "visual_style": "..."}}"""


def idea_from_format(session: Session, llm: LLMClient, project: Project, video: CompetitorVideo) -> Idea:
    recipe = video.recipe or extract_recipe(session, llm, video)
    raw = llm.generate_json(IDEA_FROM_FORMAT_SYSTEM, IDEA_FROM_FORMAT_PROMPT.format(
        niche=project.niche or "générale", language=project.language, hook_type=recipe["hook_type"],
        structure=" → ".join(recipe["structure"]), pacing=recipe["pacing"], ending=recipe["ending"],
        duration=round(recipe.get("duration_s") or 30), insights=insights_hint(session)))
    try:
        draft = IdeaDraft.model_validate(raw)
    except Exception as exc:
        raise LLMError("Le modèle a renvoyé une idée incomplète.") from exc
    if issues := content_issues(" ".join([draft.title, draft.hook, draft.original_angle])):
        raise LLMError("Idée refusée : " + ", ".join(issues) + ".")
    similarity, _ = best_match(f"{draft.title} {draft.hook}", [video.title, f"{video.title} {video.description[:300]}"])
    risk = reuse_risk(similarity)
    if risk == "high":
        raise GrowthError("L'idée proposée ressemble trop au Short d'origine : relance pour une autre histoire.")
    idea = Idea(project_id=project.id, title=draft.title, hook=draft.hook, original_angle=draft.original_angle,
                estimated_duration_s=draft.estimated_duration_s, potential_score=draft.potential_score,
                keywords=draft.keywords, visual_style=draft.visual_style, reuse_risk=risk,
                sources=[json.dumps({"title": f"format : {video.title[:120]}", "source": "concurrent",
                                     "url": video.url}, ensure_ascii=False)])
    session.add(idea)
    session.flush()
    return idea


# ── Style d'ecriture personnel ──

STYLE_SYSTEM = """Tu analyses la façon d'écrire et de parler d'un créateur à partir de ses textes.
Décris son style pour qu'un autre auteur puisse l'imiter : ton, longueur des phrases, vocabulaire,
tournures et expressions récurrentes, type d'accroches, structure, ce qu'il évite.
N'invente rien. Réponds uniquement en JSON."""

STYLE_PROMPT = """Textes du créateur ({count}) :
{samples}
Format JSON exact :
{{"tone": "...", "sentence_length": "...", "vocabulary": "...", "expressions": ["..."],
"hooks": "...", "structure": "...", "avoid": "...", "summary": "consigne de style en 3 phrases"}}"""


def learn_style(session: Session, llm: LLMClient, samples: list[str], source: str) -> dict[str, Any]:
    texts = [s.strip()[:3000] for s in samples if s and len(s.strip()) > 20][:30]
    if len(texts) < 2:
        raise GrowthError("Donne au moins 2 textes (scripts, transcriptions ou descriptions de tes vidéos).")
    raw = llm.generate_json(STYLE_SYSTEM, STYLE_PROMPT.format(
        count=len(texts), samples="\n---\n".join(texts)), temperature=0.2)
    if not raw.get("summary"):
        raise LLMError("Le modèle n'a pas su décrire ton style.")
    profile = {k: raw.get(k) for k in ("tone", "sentence_length", "vocabulary", "expressions", "hooks", "structure",
                                        "avoid", "summary")}
    profile.update({"samples": len(texts), "source": source, "updated_at": utcnow().isoformat(), "enabled": True})
    set_value(session, "style_profile", profile)
    return profile


def style_hint(session: Session) -> str:
    profile = get_value(session, "style_profile")
    if not profile or not profile.get("enabled", True) or not profile.get("summary"):
        return ""
    expressions = ", ".join(profile.get("expressions") or [])[:300]
    return str(f"Écris dans le style du créateur : {profile['summary']} Ton : {profile.get('tone', '')}. "
            f"Expressions qu'il utilise (avec parcimonie) : {expressions}. À éviter : {profile.get('avoid', '')}.")


# ── Resultats et lecons ──


def add_manual_stats(session: Session, project_id: str, platform: str, *, views: int, likes: int = 0,
                     comments: int = 0, average_view_duration_s: float = 0) -> Analytics:
    if session.get(Project, project_id) is None:
        raise GrowthError("Projet introuvable.")
    row = Analytics(project_id=project_id, platform=platform, youtube_video_id="", views=views, likes=likes,
                    comments=comments, average_view_duration_s=average_view_duration_s, source="manuel")
    session.add(row)
    session.flush()
    return row


def refresh_youtube_stats(session: Session, data: YouTubeData) -> int:
    """Vues, j'aime et commentaires publics des Shorts publies sur YouTube."""
    jobs = list(session.scalars(select(PublishJob).where(PublishJob.youtube_video_id.is_not(None))))
    posts = list(session.scalars(select(SocialPost).where(SocialPost.platform == "youtube",
                                                          SocialPost.external_id.is_not(None))))
    ids = {j.youtube_video_id: j.project_id for j in jobs if j.youtube_video_id}
    ids.update({p.external_id: p.project_id for p in posts if p.external_id})
    count = 0
    for video in data.videos(list(ids)):
        session.add(Analytics(project_id=ids.get(video["id"]), platform="youtube", youtube_video_id=video["id"],
                              views=video["views"], likes=video["likes"], comments=video["comments"]))
        count += 1
    session.flush()
    return count


def performance_table(session: Session) -> list[dict[str, Any]]:
    """Derniers chiffres de chaque Short (par projet et plateforme)."""
    latest: dict[tuple[str | None, str], Analytics] = {}
    for row in session.scalars(select(Analytics).order_by(Analytics.collected_at)):
        latest[(row.project_id, row.platform)] = row
    table = []
    for (project_id, platform), row in latest.items():
        project = session.get(Project, project_id) if project_id else None
        script = current_script(session, project_id) if project_id else None
        table.append({"project_id": project_id, "title": project.title if project else row.youtube_video_id,
                      "platform": platform, "views": row.views, "likes": row.likes, "comments": row.comments,
                      "average_view_duration_s": row.average_view_duration_s,
                      "hook": script.hook if script else "", "duration_s": script.estimated_duration_s if script else 0,
                      "collected_at": row.collected_at.isoformat()})
    return sorted(table, key=lambda r: r["views"], reverse=True)


INSIGHTS_SYSTEM = """Tu analyses les résultats de Shorts d'un même créateur pour comprendre ce qui marche.
Compare les meilleurs et les moins bons : accroche, sujet, durée, rythme. Sois concret et prudent
(peu de données = conclusions provisoires). Réponds uniquement en JSON."""

INSIGHTS_PROMPT = """Meilleurs Shorts :
{top}
Moins bons Shorts :
{bottom}
Format JSON exact :
{{"summary": "...", "what_works": ["..."], "avoid": ["..."], "next_week": ["piste d'idée", "..."]}}"""


def compute_insights(session: Session, llm: LLMClient) -> dict[str, Any]:
    table = performance_table(session)
    if len(table) < 3:
        raise GrowthError("Il faut les résultats d'au moins 3 Shorts pour en tirer des leçons.")
    half = max(1, min(5, len(table) // 2))

    def lines(rows: list[dict[str, Any]]) -> str:
        return "\n".join(f"- « {r['title']} » ({r['platform']}) : {r['views']} vues, {r['likes']} j'aime, "
                         f"durée {r['duration_s']:g} s, accroche « {r['hook'][:150]} »" for r in rows)

    raw = llm.generate_json(INSIGHTS_SYSTEM, INSIGHTS_PROMPT.format(top=lines(table[:half]),
                                                                    bottom=lines(table[-half:])), temperature=0.3)
    insights = {"summary": str(raw.get("summary", ""))[:1000],
                "what_works": [str(x)[:300] for x in raw.get("what_works") or []][:6],
                "avoid": [str(x)[:300] for x in raw.get("avoid") or []][:6],
                "next_week": [str(x)[:300] for x in raw.get("next_week") or []][:8],
                "based_on": len(table), "updated_at": utcnow().isoformat()}
    set_value(session, "insights", insights)
    return insights


def insights_hint(session: Session) -> str:
    insights = get_value(session, "insights")
    if not insights or not insights.get("summary"):
        return ""
    return str("Leçons tirées des résultats précédents : " + insights["summary"] + " Ce qui marche : "
            + "; ".join(insights.get("what_works", [])) + ". À éviter : " + "; ".join(insights.get("avoid", [])) + ".")
