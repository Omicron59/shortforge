"""Lecture publique de l'API YouTube Data v3 avec une cle API (aucun envoi, aucun telechargement de video).

Sert au suivi des concurrents (titres, durees, vues) et aux statistiques des videos publiees.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import httpx

API = "https://www.googleapis.com/youtube/v3"


class YouTubeDataError(RuntimeError):
    """Erreur de lecture YouTube ; le message est destine a l'utilisateur."""


def iso_duration(value: str) -> float:
    """Duree ISO 8601 (PT1M5S) en secondes."""
    match = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not match:
        return 0.0
    days, hours, minutes, secs = (int(x or 0) for x in match.groups())
    return float(days * 86400 + hours * 3600 + minutes * 60 + secs)


class YouTubeData:
    def __init__(self, api_key: str | None, *, transport: httpx.BaseTransport | None = None) -> None:
        self.api_key = api_key
        self._http = httpx.Client(base_url=API, timeout=30, transport=transport)

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise YouTubeDataError("Ajoute YOUTUBE_API_KEY dans le fichier .env pour lire les chaînes YouTube.")
        try:
            res = self._http.get(path, params={**params, "key": self.api_key})
        except httpx.HTTPError as exc:
            raise YouTubeDataError("YouTube injoignable : vérifie la connexion internet.") from exc
        if res.status_code == 403:
            raise YouTubeDataError("YouTube refuse la clé API ou le quota du jour est épuisé.")
        if res.status_code >= 400:
            raise YouTubeDataError(f"Erreur YouTube {res.status_code}.")
        data: dict[str, Any] = res.json()
        return data

    def channel(self, handle_or_id: str) -> dict[str, Any]:
        """Chaine a partir d'un @nom, d'une adresse ou d'un identifiant UC..."""
        value = handle_or_id.strip().rstrip("/")
        value = value.split("youtube.com/")[-1].removeprefix("channel/")
        params = {"part": "snippet,contentDetails"}
        params.update({"id": value} if value.startswith("UC") else {"forHandle": value if value.startswith("@")
                                                                     else f"@{value}"})
        items = self._get("/channels", params).get("items") or []
        if not items:
            raise YouTubeDataError(f"Chaîne YouTube introuvable : {handle_or_id}.")
        item = items[0]
        return {"id": item["id"], "title": item["snippet"]["title"],
                "uploads": item["contentDetails"]["relatedPlaylists"]["uploads"]}

    def recent_videos(self, uploads_playlist: str, limit: int = 50) -> list[dict[str, Any]]:
        items = self._get("/playlistItems", {"part": "contentDetails", "playlistId": uploads_playlist,
                                             "maxResults": min(50, limit)}).get("items") or []
        ids = [i["contentDetails"]["videoId"] for i in items]
        return self.videos(ids)

    def videos(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        items = self._get("/videos", {"part": "snippet,statistics,contentDetails", "id": ",".join(ids[:50])})
        out = []
        for item in items.get("items") or []:
            stats, snippet = item.get("statistics", {}), item.get("snippet", {})
            published = snippet.get("publishedAt")
            out.append({
                "id": item["id"], "title": snippet.get("title", ""), "description": snippet.get("description", ""),
                "duration_s": iso_duration(item.get("contentDetails", {}).get("duration", "")),
                "views": int(stats.get("viewCount", 0) or 0), "likes": int(stats.get("likeCount", 0) or 0),
                "comments": int(stats.get("commentCount", 0) or 0),
                "published_at": datetime.fromisoformat(published.replace("Z", "+00:00")).replace(tzinfo=None)
                if published else None,
                "url": f"https://www.youtube.com/shorts/{item['id']}",
            })
        return out
