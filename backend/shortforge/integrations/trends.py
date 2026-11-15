"""Sources de tendances pour inspirer les idees.

Les tendances servent uniquement d'inspiration : on n'en garde que le titre, jamais le contenu,
et le risque de reprise de chaque idee est calcule par rapport a elles.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Protocol

import httpx

logger = logging.getLogger("shortforge.trends")


@dataclass(frozen=True, slots=True)
class Trend:
    title: str
    source: str  # youtube | google | manuel
    url: str = ""


class TrendSource(Protocol):
    name: str

    def fetch(self, niche: str, language: str) -> list[Trend]: ...


class ManualTrendSource:
    """Tendances saisies a la main dans l'application."""

    name = "manuel"

    def __init__(self, titles: list[str]) -> None:
        self.titles = [t.strip() for t in titles if t and t.strip()]

    def fetch(self, niche: str, language: str) -> list[Trend]:
        return [Trend(t, "manuel") for t in self.titles]


class GoogleTrendsSource:
    """Recherches en hausse sur Google, via le flux RSS public de Google Trends."""

    name = "google"
    URL = "https://trends.google.com/trending/rss"

    def __init__(self, region: str = "FR", *, transport: httpx.BaseTransport | None = None) -> None:
        self.region = region
        self._http = httpx.Client(timeout=20, transport=transport, follow_redirects=True)

    def fetch(self, niche: str, language: str) -> list[Trend]:
        res = self._http.get(self.URL, params={"geo": self.region})
        res.raise_for_status()
        root = ET.fromstring(res.text)
        trends = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            if title:
                trends.append(Trend(title, "google", (item.findtext("link") or "").strip()))
        return trends[:25]


class YouTubeTrendSource:
    """Videos populaires de YouTube (API Data v3, lecture seule, cle API simple)."""

    name = "youtube"
    URL = "https://www.googleapis.com/youtube/v3/videos"

    def __init__(self, api_key: str, region: str = "FR", *, transport: httpx.BaseTransport | None = None) -> None:
        self.api_key = api_key
        self.region = region
        self._http = httpx.Client(timeout=20, transport=transport)

    def fetch(self, niche: str, language: str) -> list[Trend]:
        res = self._http.get(self.URL, params={"part": "snippet", "chart": "mostPopular", "regionCode": self.region,
                                               "maxResults": 25, "key": self.api_key})
        res.raise_for_status()
        return [Trend(item["snippet"]["title"], "youtube", f"https://www.youtube.com/watch?v={item['id']}")
                for item in res.json().get("items", []) if item.get("snippet", {}).get("title")]


def collect_trends(sources: list[TrendSource], niche: str, language: str) -> tuple[list[Trend], list[str]]:
    """Interroge chaque source ; une source en panne n'empeche pas les autres. Renvoie (tendances, avertissements)."""
    trends: list[Trend] = []
    warnings: list[str] = []
    for source in sources:
        try:
            trends.extend(source.fetch(niche, language))
        except Exception as exc:  # une source externe ne doit jamais bloquer la generation
            logger.warning("Tendances %s indisponibles : %s", source.name, exc)
            warnings.append(f"Tendances {source.name} indisponibles.")
    return trends, warnings
