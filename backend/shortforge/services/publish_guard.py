"""Garde-fou de publication YouTube.

Rien n'est publie sans que TOUTES ces conditions soient reunies :
1. `YOUTUBE_PUBLISH_ENABLED=true` ou `SOCIAL_PUBLISH_ENABLED=true` dans le `.env` local
   (les deux sont desactives par defaut) ;
2. le rendu final a ete valide par une personne (etape `approve_final_render`) ;
3. la publication elle-meme est confirmee explicitement par une personne.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shortforge.config import Settings

# Identifiants qui designent un automatisme et jamais une personne.
NON_HUMAN_ACTORS = frozenset({"", "system", "systeme", "auto", "automatique", "agent", "ia", "ai", "bot"})


def is_human_actor(actor: str | None) -> bool:
    return (actor or "").strip().lower() not in NON_HUMAN_ACTORS


class PublishBlockedError(PermissionError):
    """La publication est refusee ; `reasons` explique pourquoi, en francais."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("Publication bloquée : " + " ; ".join(reasons))


@dataclass(slots=True)
class PublishCheck:
    allowed: bool
    reasons: list[str] = field(default_factory=list)


def check_publish(
    settings: Settings,
    *,
    final_render_validated_by: str | None,
    confirmed: bool,
    actor: str | None,
) -> PublishCheck:
    """Verifie les conditions de publication sans rien declencher."""
    reasons: list[str] = []
    if not (settings.youtube_publish_enabled or settings.social_publish_enabled):
        reasons.append("la publication automatique est désactivée "
                       "(YOUTUBE_PUBLISH_ENABLED=false et SOCIAL_PUBLISH_ENABLED=false)")
    if not is_human_actor(final_render_validated_by):
        reasons.append("le rendu final n'a pas été validé par une personne")
    if not confirmed:
        reasons.append("la publication n'a pas été confirmée explicitement")
    if not is_human_actor(actor):
        reasons.append("seule une personne peut confirmer une publication")
    return PublishCheck(allowed=not reasons, reasons=reasons)


def ensure_can_publish(
    settings: Settings,
    *,
    final_render_validated_by: str | None,
    confirmed: bool,
    actor: str | None,
) -> None:
    """Leve `PublishBlockedError` si une seule condition manque."""
    result = check_publish(
        settings, final_render_validated_by=final_render_validated_by, confirmed=confirmed, actor=actor
    )
    if not result.allowed:
        raise PublishBlockedError(result.reasons)
