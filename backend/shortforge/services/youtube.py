"""Brouillon YouTube, verification finale et publication (desactivee par defaut).

- Le brouillon est LOCAL : titre, description (avec la mention IA), tags, confidentialite.
  Rien n'est envoye a YouTube a ce stade.
- La verification finale liste tout ce qui doit etre vrai avant une publication. Une seule
  ligne en echec bloque la publication.
- L'envoi n'a lieu qu'a la validation humaine de l'etape `publish`, apres le garde-fou
  (`publish_guard`) et la verification finale. La video part en « privée » par defaut.
- Les jetons OAuth restent dans un fichier local du dossier de donnees, jamais en base ni dans le code.
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.models import Asset, Idea, PipelineStep, Project, PublishJob, SocialPost, YoutubeChannel, utcnow
from shortforge.pipeline.steps import StepName
from shortforge.services.ideas import selected_idea
from shortforge.services.production import ProductionError
from shortforge.services.publish_guard import PublishBlockedError, is_human_actor
from shortforge.services.render import file_sha256, latest_render, probe, spec_problems
from shortforge.services.safety import content_issues
from shortforge.services.scripts import current_script
from shortforge.vault import Vault, VaultError

SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_URL = "https://www.googleapis.com/youtube/v3"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
PRIVACY = ("private", "unlisted", "public")
MAX_TITLE, MAX_DESCRIPTION, MAX_TAGS_CHARS = 100, 5000, 500


class YouTubeError(ProductionError):
    """Erreur YouTube ; le message est destine a l'utilisateur."""


# ── Brouillon ──


def current_draft(session: Session, project_id: str) -> PublishJob | None:
    return session.scalars(select(PublishJob).where(PublishJob.project_id == project_id)
                           .order_by(PublishJob.created_at.desc())).first()


def _hashtags(keywords: list[str]) -> str:
    tags = ["#Shorts"] + ["#" + "".join(k.split()) for k in keywords[:3] if k.strip()]
    return " ".join(dict.fromkeys(tags))


def create_draft(session: Session, settings: Settings, project: Project) -> dict[str, Any]:
    """Etape create_youtube_draft : prepare titre, description et tags a partir du script."""
    render = latest_render(session, project.id)
    if render is None or render.approved_at is None:
        raise YouTubeError("Le rendu final doit être validé avant de préparer le brouillon YouTube.")
    script = current_script(session, project.id)
    idea: Idea | None = selected_idea(session, project.id)
    title = (idea.title if idea else project.title).strip()[:MAX_TITLE]
    keywords = list(idea.keywords) if idea else []
    body = [script.hook, script.call_to_action] if script else []
    description = "\n\n".join([p for p in body if p] + [settings.ai_disclosure_text, _hashtags(keywords)])
    draft = current_draft(session, project.id)
    if draft is None or draft.status != "draft":
        draft = PublishJob(project_id=project.id)
        session.add(draft)
    draft.render_id = render.id
    draft.title, draft.description = title, description[:MAX_DESCRIPTION]
    draft.tags = [k for k in keywords if k.strip()][:15]
    draft.privacy, draft.ai_disclosure, draft.made_for_kids = "private", True, False
    session.flush()
    from shortforge.services import social

    social.ensure_posts(session, settings, project)
    return {"publish_job_id": draft.id, "title": draft.title, "privacy": draft.privacy,
            "message": "Brouillon local prêt : rien n'a été envoyé à YouTube."}


def update_draft(session: Session, settings: Settings, project_id: str, changes: dict[str, Any]) -> PublishJob:
    draft = current_draft(session, project_id)
    if draft is None:
        raise YouTubeError("Aucun brouillon YouTube : lance d'abord l'étape « Brouillon YouTube ».")
    if draft.status != "draft":
        raise YouTubeError("Cette vidéo a déjà été envoyée : le brouillon n'est plus modifiable.")
    if "privacy" in changes and changes["privacy"] not in PRIVACY:
        raise YouTubeError("Confidentialité inconnue : private, unlisted ou public.")
    for key in ("title", "description", "tags", "privacy", "made_for_kids"):
        if key in changes and changes[key] is not None:
            setattr(draft, key, changes[key])
    draft.human_approved_at = None  # toute modification annule la confirmation precedente
    post = session.scalars(select(SocialPost).where(SocialPost.project_id == project_id,
                                                    SocialPost.platform == "youtube")).first()
    if post is not None and post.status in ("draft", "failed"):
        post.caption = draft.description  # YouTube : le texte publie est celui du brouillon
    session.flush()
    return draft


# ── Verification finale ──


@dataclass(slots=True)
class Check:
    id: str
    label: str
    ok: bool
    detail: str = ""


def _step(session: Session, project_id: str, name: StepName) -> PipelineStep | None:
    return session.scalars(select(PipelineStep).where(PipelineStep.project_id == project_id,
                                                      PipelineStep.name == name.value)).first()


def final_checks(session: Session, settings: Settings, project: Project,
                 *, check_file: bool = True) -> list[Check]:
    """Tout ce qui doit etre vrai avant une publication, ligne par ligne."""
    checks: list[Check] = []
    add = checks.append
    from shortforge.services import social

    auto = social.automatic_posts(session, project.id)
    youtube_auto = any(p.platform == "youtube" for p in auto)
    enabled = settings.youtube_publish_enabled or settings.social_publish_enabled
    add(Check("publish_enabled", "Publication automatique activée dans le .env", enabled,
              "" if enabled else "YOUTUBE_PUBLISH_ENABLED=false et SOCIAL_PUBLISH_ENABLED=false (réglage par défaut)"))
    add(Check("targets", "Au moins une plateforme à publier automatiquement", bool(auto),
              ", ".join(social.LABELS[p.platform] for p in auto) if auto
              else "aucune : active une plateforme ou publie toi-même (export manuel)"))

    render = latest_render(session, project.id)
    asset = session.get(Asset, render.asset_id) if render and render.asset_id else None
    path = Path(asset.path) if asset else None
    exists = bool(path and path.is_file())
    add(Check("render_exists", "Rendu final présent", exists, "" if exists else "aucun fichier MP4 exporté"))
    if check_file and exists and path is not None and asset is not None:
        try:
            problems = spec_problems(probe(path, settings))
        except ProductionError as exc:
            problems = [str(exc)]
        add(Check("render_format", "Format Short : 1080x1920, H.264, AAC, 180 s au plus", not problems,
                  ", ".join(problems)))
        same = file_sha256(path) == asset.sha256
        add(Check("render_unchanged", "Fichier identique à celui qui a été validé", same,
                  "" if same else "le fichier a changé depuis la validation : refais le rendu et la validation"))

    final = _step(session, project.id, StepName.APPROVE_FINAL_RENDER)
    human = bool(final and final.status == "done" and is_human_actor(final.validated_by)
                 and render and render.approved_at)
    add(Check("final_validated", "Rendu final regardé et validé par une personne", human,
              f"validé par {final.validated_by}" if human and final else "validation humaine manquante"))

    draft = current_draft(session, project.id)
    add(Check("draft_exists", "Brouillon YouTube préparé", draft is not None,
              "" if draft else "lance l'étape « Brouillon YouTube »"))
    if draft is not None:
        title_ok = 0 < len(draft.title.strip()) <= MAX_TITLE and "<" not in draft.title and ">" not in draft.title
        add(Check("title", "Titre valide (1 à 100 caractères, sans < ni >)", title_ok, draft.title))
        desc_ok = len(draft.description) <= MAX_DESCRIPTION and "<" not in draft.description
        add(Check("description", "Description valide (5 000 caractères au plus)", desc_ok))
        tags_ok = sum(len(t) for t in draft.tags) <= MAX_TAGS_CHARS
        add(Check("tags", "Tags : 500 caractères au plus", tags_ok))
        disclosure = draft.ai_disclosure and settings.ai_disclosure_text.strip() in draft.description
        add(Check("ai_disclosure", "Mention « contenu généré par IA » présente", disclosure,
                  "" if disclosure else f"ajoute « {settings.ai_disclosure_text} » à la description"))
        labels = {"private": "privée", "unlisted": "non répertoriée", "public": "publique"}
        add(Check("privacy", "Confidentialité choisie", draft.privacy in PRIVACY,
                  labels.get(draft.privacy, draft.privacy)))
        script = current_script(session, project.id)
        text = " ".join([draft.title, draft.description] + ([script.hook, script.body, script.conclusion]
                                                             if script else []))
        issues = content_issues(text)
        add(Check("content", "Contenu autorisé (ni violent, sexuel, haineux, illégal ou trompeur)", not issues,
                  ", ".join(issues)))
    idea = selected_idea(session, project.id)
    reuse_ok = idea is None or idea.reuse_risk != "high"
    add(Check("originality", "Idée originale (pas de risque élevé de contenu réutilisé)", reuse_ok,
              "" if reuse_ok else "trop proche d'une vidéo existante"))
    if youtube_auto:
        channel = default_channel(session)
        token_ok = bool(channel and Path(channel.token_path).is_file())
        add(Check("channel", "Chaîne YouTube connectée", token_ok,
                  channel.title if token_ok and channel else "connecte ta chaîne dans Paramètres"))
    quality = _quality(session, project.id)
    if quality is not None:
        add(Check("quality", f"Contrôle qualité : {quality['score']:g}/10 (minimum {settings.quality_min_score:g})",
                  quality["score"] >= settings.quality_min_score, ", ".join(quality.get("issues", []))))
    for check_id, label, ok, detail in social.post_checks(session, settings, project):
        add(Check(check_id, label, ok, detail))
    return checks


def checks_as_dict(checks: list[Check]) -> dict[str, Any]:
    return {"ready": all(c.ok for c in checks), "checks": [asdict(c) for c in checks]}


# ── Connexion OAuth de la chaine ──


def default_channel(session: Session) -> YoutubeChannel | None:
    return session.scalars(select(YoutubeChannel).order_by(YoutubeChannel.is_default.desc(),
                                                           YoutubeChannel.connected_at.desc())).first()


def client_secrets(settings: Settings) -> dict[str, str]:
    """Identifiants OAuth « application de bureau » telecharges depuis Google Cloud (fichier local)."""
    if not settings.youtube_client_secrets_file:
        raise YouTubeError("Renseigne YOUTUBE_CLIENT_SECRETS_FILE dans le .env (fichier OAuth de Google Cloud).")
    path = Path(settings.youtube_client_secrets_file)
    if not path.is_file():
        raise YouTubeError(f"Fichier OAuth introuvable : {path}.")
    data = json.loads(path.read_text(encoding="utf-8"))
    info = data.get("installed") or data.get("web") or {}
    if not info.get("client_id") or not info.get("client_secret"):
        raise YouTubeError("Fichier OAuth invalide : client_id ou client_secret manquant.")
    return {"client_id": info["client_id"], "client_secret": info["client_secret"]}


def token_path(settings: Settings) -> Path:
    return settings.shortforge_data_dir / "youtube" / "token.json"


class YouTubeClient:
    """Appels a l'API YouTube Data v3 (connexion, chaine, envoi d'une video)."""

    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None,
                 vault: Vault | None = None) -> None:
        self.settings = settings
        self.vault = vault
        self._http = httpx.Client(timeout=120, transport=transport)
        self._state = ""

    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.settings.shortforge_port}/api/youtube/oauth/callback"

    def authorization_url(self) -> str:
        secrets_ = client_secrets(self.settings)
        self._state = secrets.token_urlsafe(24)
        query = {"client_id": secrets_["client_id"], "redirect_uri": self.redirect_uri(), "response_type": "code",
                 "scope": SCOPES, "access_type": "offline", "prompt": "consent", "state": self._state}
        return f"{AUTH_URL}?{urlencode(query)}"

    def finish_authorization(self, session: Session, code: str, state: str) -> YoutubeChannel:
        if not self._state or not secrets.compare_digest(state, self._state):
            raise YouTubeError("Connexion refusée : jeton de sécurité invalide. Recommence depuis l'application.")
        self._state = ""
        secrets_ = client_secrets(self.settings)
        token = self._token_request({**secrets_, "code": code, "grant_type": "authorization_code",
                                     "redirect_uri": self.redirect_uri()})
        if "refresh_token" not in token:
            raise YouTubeError("Google n'a pas fourni de jeton durable : retire l'accès à ShortForge dans ton compte "
                               "Google puis reconnecte-toi.")
        path = token_path(self.settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._save_token(path, token)
        info = self._get("/channels", {"part": "snippet", "mine": "true"}, token["access_token"])
        items = info.get("items") or []
        if not items:
            raise YouTubeError("Aucune chaîne YouTube sur ce compte Google.")
        channel_id, title = items[0]["id"], items[0]["snippet"]["title"]
        channel = session.scalars(select(YoutubeChannel).where(YoutubeChannel.channel_id == channel_id)).first()
        if channel is None:
            channel = YoutubeChannel(channel_id=channel_id, title=title)
            session.add(channel)
        channel.title, channel.token_path, channel.is_default = title, str(path), True
        session.flush()
        return channel

    def access_token(self, channel: YoutubeChannel) -> str:
        path = Path(channel.token_path)
        if not path.is_file():
            raise YouTubeError("Chaîne YouTube déconnectée : reconnecte-la dans Paramètres.")
        stored = self._read_token(path)
        if stored.get("access_token") and stored.get("expires_at", 0) > time.time() + 60:
            return str(stored["access_token"])
        token = self._token_request({**client_secrets(self.settings), "grant_type": "refresh_token",
                                     "refresh_token": stored.get("refresh_token", "")})
        self._save_token(path, {**stored, **token})
        return str(token["access_token"])

    def upload(self, channel: YoutubeChannel, video: Path, draft: PublishJob,
               publish_at: datetime | None = None) -> str:
        """Envoi en deux temps (session puis fichier). Renvoie l'identifiant YouTube de la video."""
        token = self.access_token(channel)
        metadata: dict[str, Any] = {
            "snippet": {"title": draft.title, "description": draft.description, "tags": draft.tags,
                        "categoryId": draft.category_id or "22"},
            "status": {"privacyStatus": draft.privacy, "selfDeclaredMadeForKids": draft.made_for_kids,
                       "containsSyntheticMedia": draft.ai_disclosure},
        }
        if publish_at is not None:  # programmee : privee jusqu'a l'heure choisie (exige par YouTube)
            metadata["status"].update({"privacyStatus": "private", "publishAt": publish_at.isoformat() + "Z"})
        size = video.stat().st_size
        start = self._http.post(UPLOAD_URL, params={"uploadType": "resumable", "part": "snippet,status"},
                                headers={"Authorization": f"Bearer {token}", "X-Upload-Content-Type": "video/mp4",
                                         "X-Upload-Content-Length": str(size)}, json=metadata)
        self._raise(start)
        location = start.headers.get("location")
        if not location:
            raise YouTubeError("YouTube n'a pas ouvert la session d'envoi.")
        with video.open("rb") as handle:
            sent = self._http.put(location, content=handle.read(),
                                  headers={"Authorization": f"Bearer {token}", "Content-Type": "video/mp4"})
        self._raise(sent)
        video_id = sent.json().get("id")
        if not video_id:
            raise YouTubeError("YouTube n'a pas renvoyé d'identifiant de vidéo.")
        return str(video_id)

    # ── Aides ──

    def _token_request(self, data: dict[str, str]) -> dict[str, Any]:
        res = self._http.post(TOKEN_URL, data=data)
        self._raise(res)
        token: dict[str, Any] = res.json()
        token["expires_at"] = time.time() + float(token.get("expires_in", 3600))
        return token

    def _get(self, path: str, params: dict[str, str], token: str) -> dict[str, Any]:
        res = self._http.get(f"{API_URL}{path}", params=params, headers={"Authorization": f"Bearer {token}"})
        self._raise(res)
        data: dict[str, Any] = res.json()
        return data

    def _encrypts(self) -> bool:
        return self.vault is not None and self.vault.available

    def _save_token(self, path: Path, token: dict[str, Any]) -> None:
        """Jeton chiffre par le coffre quand il est disponible ; sinon comme avant (fichier local)."""
        keep = {k: token[k] for k in ("access_token", "refresh_token", "expires_at", "scope") if k in token}
        text = json.dumps(keep)
        if self._encrypts() and self.vault is not None:
            sealed = self.vault.encrypt(text)
            if self.vault.decrypt(sealed) != text:
                raise YouTubeError("Le coffre n'a pas pu protéger le jeton YouTube : rien n'a été modifié.")
            text = sealed
        temporary = path.with_suffix(".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)  # remplacement atomique : jamais de jeton a moitie ecrit

    def _read_token(self, path: Path) -> dict[str, Any]:
        raw = path.read_text(encoding="utf-8").strip()
        if raw.startswith("{"):  # jeton d'une version 0.5.x, en clair : chiffre sur place, sans le perdre
            stored: dict[str, Any] = json.loads(raw)
            if self._encrypts():
                self._save_token(path, stored)
            return stored
        if not self._encrypts() or self.vault is None:
            raise YouTubeError("Jeton YouTube protégé par le coffre, mais le coffre est indisponible sur cette "
                               "session. Reconnecte la chaîne dans Paramètres.")
        try:
            data: dict[str, Any] = json.loads(self.vault.decrypt(raw))
        except VaultError as exc:
            raise YouTubeError("Jeton YouTube illisible (la clé du coffre a changé) : reconnecte la chaîne dans "
                               "Paramètres.") from exc
        return data

    def token_encrypted(self, path: Path) -> bool | None:
        """Vrai si le jeton est chiffre, faux s'il est en clair, None s'il n'existe pas."""
        if not path.is_file():
            return None
        return not path.read_text(encoding="utf-8").lstrip().startswith("{")

    @staticmethod
    def _raise(res: httpx.Response) -> None:
        if res.status_code < 400:
            return
        try:
            message = res.json().get("error", {})
            message = message.get("message") if isinstance(message, dict) else res.json().get("error_description")
        except ValueError:
            message = res.text[:200]
        if res.status_code in (401, 403):
            raise YouTubeError(f"YouTube refuse l'accès ({res.status_code}) : {message or 'reconnecte ta chaîne'}.")
        raise YouTubeError(f"Erreur YouTube {res.status_code} : {message or 'réponse inattendue'}.")


def _quality(session: Session, project_id: str) -> dict[str, Any] | None:
    step = _step(session, project_id, StepName.RENDER_VIDEO)
    quality = (step.output or {}).get("quality") if step else None
    return quality if isinstance(quality, dict) and "score" in quality else None


def publish(session: Session, settings: Settings, project: Project, client: YouTubeClient, actor: str,
            *, postiz: Any = None) -> dict[str, str]:
    """Envoi reel. Appele seulement apres le garde-fou ; refait la verification finale juste avant."""
    from shortforge.integrations.postiz import PostizClient
    from shortforge.services import social

    social.ensure_posts(session, settings, project)
    failing = [c for c in final_checks(session, settings, project) if not c.ok]
    if failing:
        raise PublishBlockedError([f"{c.label} : {c.detail}" if c.detail else c.label for c in failing])
    draft = current_draft(session, project.id)
    assert draft is not None  # verifie plus haut
    draft.human_approved_by, draft.human_approved_at = actor, utcnow()

    def youtube_upload(post: Any) -> str:
        channel = default_channel(session)
        render = latest_render(session, project.id)
        asset = session.get(Asset, render.asset_id) if render and render.asset_id else None
        if channel is None or asset is None:
            raise YouTubeError("Chaîne ou rendu introuvable.")
        draft.status, draft.channel_id = "uploading", channel.id
        try:
            draft.youtube_video_id = client.upload(channel, Path(asset.path), draft, publish_at=post.scheduled_at)
        except YouTubeError as exc:
            draft.status, draft.error = "failed", str(exc)
            raise
        draft.status, draft.error = "published", None
        return str(draft.youtube_video_id)

    if postiz is None:
        key = settings.postiz_api_key.get_secret_value() if settings.postiz_api_key else None
        postiz = PostizClient(settings.postiz_url, key)
    results = social.publish_posts(session, settings, project, postiz=postiz, youtube_upload=youtube_upload,
                                   actor=actor)
    session.flush()
    return results
