"""Client Postiz (outil open source de programmation de publications : TikTok, Instagram, YouTube...).

Postiz detient les connexions a tes comptes ; ShortForge lui envoie la video, le texte et l'heure.
A verifier avec une vraie instance : le format exact de l'API publique peut evoluer.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


class PostizError(RuntimeError):
    """Erreur Postiz ; le message est destine a l'utilisateur."""


class PostizClient:
    def __init__(self, base_url: str, api_key: str | None, *, transport: httpx.BaseTransport | None = None) -> None:
        self.api_key = api_key
        self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=300, transport=transport)

    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise PostizError("Postiz n'est pas configuré : ajoute POSTIZ_API_KEY (et POSTIZ_URL) "
                              "dans le fichier .env.")
        return {"Authorization": self.api_key}

    @staticmethod
    def _check(res: httpx.Response) -> Any:
        if res.status_code in (401, 403):
            raise PostizError("Postiz refuse la clé API : vérifie POSTIZ_API_KEY.")
        if res.status_code >= 400:
            raise PostizError(f"Erreur Postiz {res.status_code} : {res.text[:200]}")
        return res.json()

    def integrations(self) -> list[dict[str, Any]]:
        """Comptes connectes dans Postiz : [{id, name, providerIdentifier, disabled}]."""
        try:
            data = self._check(self._http.get("/integrations", headers=self._headers()))
        except httpx.HTTPError as exc:
            raise PostizError("Postiz injoignable : vérifie POSTIZ_URL.") from exc
        return [i for i in (data if isinstance(data, list) else data.get("integrations", [])) if not i.get("disabled")]

    def find(self, platform: str) -> dict[str, Any] | None:
        names = {"tiktok": ("tiktok",), "instagram": ("instagram", "instagram-standalone"), "youtube": ("youtube",)}
        return next((i for i in self.integrations()
                     if str(i.get("providerIdentifier", i.get("identifier", ""))).lower() in names[platform]), None)

    def upload(self, video: Path) -> dict[str, Any]:
        with video.open("rb") as handle:
            res = self._http.post("/upload", headers=self._headers(), files={"file": (video.name, handle, "video/mp4")})
        data = self._check(res)
        if not data.get("id") or not data.get("path"):
            raise PostizError("Postiz n'a pas accepté la vidéo.")
        return {"id": data["id"], "path": data["path"]}

    def schedule(self, *, integration_id: str, platform: str, caption: str, media: dict[str, Any],
                 when: datetime | None, title: str = "") -> str:
        settings: dict[str, Any] = {"__type": platform}
        if platform == "tiktok":
            settings.update({"privacy_level": "SELF_ONLY", "duet": False, "stitch": False, "comment": True,
                             "autoAddMusic": "no", "brand_content_toggle": False, "brand_organic_toggle": False,
                             "content_posting_method": "DIRECT_POST", "isAIGenerated": True})
        elif platform == "instagram":
            settings.update({"post_type": "reel"})
        elif platform == "youtube":
            settings.update({"title": title[:100], "type": "private"})
        body = {"type": "schedule" if when else "now", "date": (when or datetime.utcnow()).isoformat() + "Z",
                "shortLink": False, "tags": [],
                "posts": [{"integration": {"id": integration_id}, "value": [{"content": caption, "image": [media]}],
                           "settings": settings}]}
        data = self._check(self._http.post("/posts", headers=self._headers(), json=body))
        first = data[0] if isinstance(data, list) and data else data
        return str((first or {}).get("postId") or (first or {}).get("id") or "programmé")
