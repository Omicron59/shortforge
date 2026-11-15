"""Publication multi-plateforme : YouTube Shorts, TikTok et Instagram Reels, a l'heure choisie.

- YouTube : envoi direct par l'API officielle (programmation possible : la video reste privee
  jusqu'a l'heure choisie).
- TikTok et Instagram : par Postiz si tu l'utilises (SOCIAL_PUBLISH_ENABLED=true), sinon
  « export manuel » : ShortForge prepare le fichier et le texte, tu publies toi-meme.
- Chaque publication automatique passe par le garde-fou, la verification finale et ta confirmation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.integrations.postiz import PostizClient, PostizError
from shortforge.models import Asset, Idea, Project, PublishJob, SocialPost, utcnow
from shortforge.services.ideas import selected_idea
from shortforge.services.planning import PLATFORMS, schedule_slots
from shortforge.services.production import ProductionError
from shortforge.services.render import latest_render
from shortforge.services.safety import content_issues

LABELS = {"youtube": "YouTube Shorts", "tiktok": "TikTok", "instagram": "Instagram Reels"}
MAX_CAPTION = {"youtube": 5000, "tiktok": 2200, "instagram": 2200}
MAX_HASHTAGS = {"instagram": 30, "tiktok": 30, "youtube": 15}


class SocialError(ProductionError):
    """Erreur de publication ; le message est destine a l'utilisateur."""


def method_for(settings: Settings, platform: str) -> str:
    if platform == "youtube":
        return "youtube_api" if settings.youtube_publish_enabled else "manual"
    if settings.social_publish_enabled and settings.postiz_api_key is not None:
        return "postiz"
    return "manual"


def _hashtags(idea: Idea | None, platform: str) -> str:
    base = {"youtube": ["#Shorts"], "tiktok": ["#fyp"], "instagram": ["#reels"]}[platform]
    words = ["#" + "".join(k.split()) for k in (idea.keywords if idea else []) if k.strip()]
    return " ".join(dict.fromkeys(base + words[: MAX_HASHTAGS[platform] - 1]))


def build_caption(settings: Settings, draft: PublishJob | None, idea: Idea | None, platform: str) -> str:
    if platform == "youtube" and draft is not None:
        return draft.description
    hook = idea.hook if idea else (draft.title if draft else "")
    return "\n\n".join(p for p in (hook, settings.ai_disclosure_text, _hashtags(idea, platform)) if p)


def _local_slot_to_utc(day_utc: datetime, hhmm: str) -> datetime:
    """Le jour prevu (UTC) a l'heure du creneau de la plateforme (heure locale), renvoye en UTC."""
    from shortforge.services.planning import to_local, to_utc

    hour, minute = (int(x) for x in hhmm.split(":"))
    return to_utc(to_local(day_utc).replace(hour=hour, minute=minute, second=0, microsecond=0))


def ensure_posts(session: Session, settings: Settings, project: Project) -> list[SocialPost]:
    """Une publication par plateforme, avec son texte et son heure (planning de la semaine)."""
    from shortforge.services.youtube import current_draft

    draft = current_draft(session, project.id)
    idea = selected_idea(session, project.id)
    slots = schedule_slots(session)
    posts = {p.platform: p for p in session.scalars(select(SocialPost).where(SocialPost.project_id == project.id))}
    for platform in PLATFORMS:
        post = posts.get(platform)
        if post is None:
            post = SocialPost(project_id=project.id, platform=platform,
                              caption=build_caption(settings, draft, idea, platform))
            if project.planned_for:
                post.scheduled_at = _local_slot_to_utc(project.planned_for, str(slots.get(platform, "12:00")))
            session.add(post)
            posts[platform] = post
        if post.status in ("draft", "failed"):
            post.method = method_for(settings, platform)
            if platform == "youtube" and draft is not None:  # YouTube : le texte est celui du brouillon
                post.caption = draft.description
    session.flush()
    return [posts[p] for p in PLATFORMS]


def update_post(session: Session, post: SocialPost, changes: dict[str, Any]) -> SocialPost:
    if post.status in ("published", "scheduled"):
        raise SocialError("Cette publication est déjà partie : elle n'est plus modifiable.")
    if "caption" in changes and changes["caption"] is not None:
        caption = str(changes["caption"])
        if issues := content_issues(caption):
            raise SocialError("Texte refusé : " + ", ".join(issues) + ".")
        post.caption = caption[: MAX_CAPTION[post.platform]]
    if "enabled" in changes and changes["enabled"] is not None:
        post.enabled = bool(changes["enabled"])
    if "scheduled_at" in changes:
        value = changes["scheduled_at"]
        post.scheduled_at = None if not value else value.astimezone(UTC).replace(tzinfo=None) \
            if isinstance(value, datetime) and value.tzinfo else value
    session.flush()
    return post


def mark_exported(session: Session, post: SocialPost) -> SocialPost:
    post.status = "exported"
    session.flush()
    return post


def mark_published(session: Session, post: SocialPost, url: str = "") -> SocialPost:
    """Publication faite a la main par l'utilisateur."""
    post.status, post.method = "published", "manual"
    post.external_id = url.strip()[:200] or post.external_id
    session.flush()
    return post


def automatic_posts(session: Session, project_id: str) -> list[SocialPost]:
    return list(session.scalars(select(SocialPost).where(SocialPost.project_id == project_id,
                                                         SocialPost.enabled.is_(True),
                                                         SocialPost.method.in_(("youtube_api", "postiz")),
                                                         SocialPost.status.in_(("draft", "failed")))))


def post_checks(session: Session, settings: Settings, project: Project) -> list[tuple[str, str, bool, str]]:
    """Lignes de verification finale propres a chaque plateforme."""
    checks = []
    for post in session.scalars(select(SocialPost).where(SocialPost.project_id == project.id,
                                                         SocialPost.enabled.is_(True))):
        label = LABELS[post.platform]
        mention = settings.ai_disclosure_text.strip() in post.caption
        checks.append((f"caption_{post.platform}", f"{label} : texte avec la mention IA", mention,
                       "" if mention else f"ajoute « {settings.ai_disclosure_text} »"))
        size_ok = len(post.caption) <= MAX_CAPTION[post.platform] and \
            post.caption.count("#") <= MAX_HASHTAGS[post.platform]
        checks.append((f"length_{post.platform}", f"{label} : longueur du texte et nombre de hashtags", size_ok, ""))
        if post.scheduled_at and post.scheduled_at < utcnow():
            checks.append((f"date_{post.platform}", f"{label} : heure de publication à venir", False,
                           "l'heure choisie est déjà passée"))
        if post.method == "postiz":
            ok = settings.postiz_api_key is not None
            checks.append((f"postiz_{post.platform}", f"{label} : Postiz configuré", ok,
                           "" if ok else "POSTIZ_API_KEY manquante"))
    return checks


def publish_posts(session: Session, settings: Settings, project: Project, *, postiz: PostizClient,
                  youtube_upload: Any, actor: str) -> dict[str, str]:
    """Envoi des publications automatiques (apres garde-fou et verification finale, faits par l'appelant)."""
    render = latest_render(session, project.id)
    asset = session.get(Asset, render.asset_id) if render and render.asset_id else None
    if asset is None or not Path(asset.path).is_file():
        raise SocialError("Rendu final introuvable.")
    results: dict[str, str] = {}
    media: dict[str, Any] | None = None
    for post in automatic_posts(session, project.id):
        try:
            if post.method == "youtube_api":
                post.external_id = youtube_upload(post)
            else:
                integration = postiz.find(post.platform)
                if integration is None:
                    raise SocialError(f"Aucun compte {LABELS[post.platform]} connecté dans Postiz.")
                media = media or postiz.upload(Path(asset.path))
                post.external_id = postiz.schedule(integration_id=str(integration["id"]), platform=post.platform,
                                                   caption=post.caption, media=media, when=post.scheduled_at,
                                                   title=project.title)
            post.status = "scheduled" if post.scheduled_at and post.scheduled_at > utcnow() else "published"
            post.error = None
            results[post.platform] = post.status
        except (SocialError, PostizError, ProductionError) as exc:
            post.status, post.error = "failed", str(exc)
            results[post.platform] = f"échec : {exc}"
    session.flush()
    if results and all(v.startswith("échec") for v in results.values()):
        details = " ; ".join(f"{LABELS[k]} {v}" for k, v in results.items())
        raise SocialError("Aucune publication n'a abouti : " + details)
    return results
