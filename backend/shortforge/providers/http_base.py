"""Base des fournisseurs externes appeles en HTTP."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from shortforge.providers.base import ProviderError, VideoProvider


class HttpVideoProvider(VideoProvider):
    """Fournisseur externe : cle API lue dans `.env`, client HTTP injectable pour les tests."""

    kind = "external"
    base_url: str = ""

    def __init__(self, *, api_key: str | None = None, transport: httpx.BaseTransport | None = None,
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.api_key = api_key or ""
        self._http = httpx.Client(base_url=str(self.config.get("base_url", self.base_url)), timeout=120,
                                  transport=transport, follow_redirects=True)

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def headers(self) -> dict[str, str]:
        return {}

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        """Appel JSON ; toute erreur devient une `ProviderError` lisible (sans jamais afficher la cle)."""
        try:
            res = self._http.request(method, url, headers=self.headers(), **kwargs)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name} est injoignable : vérifie ta connexion.") from exc
        if res.status_code in (401, 403):
            raise ProviderError(f"{self.name} refuse la clé API (erreur {res.status_code}) : vérifie le fichier .env.")
        if res.status_code == 429:
            raise ProviderError(f"{self.name} limite les requêtes ou ton crédit est épuisé (erreur 429).")
        if res.status_code >= 400:
            raise ProviderError(f"{self.name} a renvoyé une erreur {res.status_code} : {res.text[:300]}")
        try:
            return res.json()
        except ValueError as exc:
            raise ProviderError(f"Réponse illisible de {self.name}.") from exc

    def download_url(self, url: str, dest_dir: Path, filename: str, *, auth: bool = False) -> Path:
        try:
            res = self._http.get(url, headers=self.headers() if auth else None)
            res.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Téléchargement impossible depuis {self.name}.") from exc
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / filename
        path.write_bytes(res.content)
        return path
