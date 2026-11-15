"""Client Ollama (modeles de texte locaux) pour les idees et les scripts."""

from __future__ import annotations

import json
from typing import Any, Protocol

import httpx


class LLMError(RuntimeError):
    """Erreur du modele de texte ; le message est destine a l'utilisateur."""


class LLMClient(Protocol):
    """Ce dont ShortForge a besoin d'un modele de texte : une reponse JSON."""

    def generate_json(self, system: str, prompt: str, *, temperature: float | None = None) -> dict[str, Any]: ...


def _parse_json(text: str) -> dict[str, Any]:
    """Accepte un JSON brut ou entoure de ```json ... ``` ; renvoie toujours un objet."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("aucun objet JSON")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("le JSON n'est pas un objet")
    return data


class OllamaClient:
    """Appelle `POST /api/chat` d'Ollama en mode JSON, sans streaming."""

    def __init__(self, base_url: str, model: str, *, timeout_s: float = 300, temperature: float = 0.8,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout_s, transport=transport)

    def list_models(self) -> list[str]:
        try:
            res = self._http.get("/api/tags")
            res.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(self._unreachable()) from exc
        return [m.get("name", "") for m in res.json().get("models", [])]

    def is_running(self) -> bool:
        try:
            self.list_models()
        except LLMError:
            return False
        return True

    def generate_json(self, system: str, prompt: str, *, temperature: float | None = None) -> dict[str, Any]:
        if not self.model:
            raise LLMError("Aucun modèle Ollama choisi : renseigne OLLAMA_MODEL dans le fichier .env.")
        body = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "options": {"temperature": self.temperature if temperature is None else temperature},
        }
        last_error = ""
        for _ in range(2):  # une seconde chance si le modele renvoie un JSON invalide
            try:
                res = self._http.post("/api/chat", json=body)
            except httpx.HTTPError as exc:
                raise LLMError(self._unreachable()) from exc
            if res.status_code == 404:
                raise LLMError(f"Le modèle « {self.model} » n'est pas installé : lance `ollama pull {self.model}`.")
            if res.status_code >= 400:
                raise LLMError(f"Ollama a renvoyé une erreur {res.status_code} : {res.text[:200]}")
            content = res.json().get("message", {}).get("content", "")
            try:
                return _parse_json(content)
            except ValueError as exc:
                last_error = str(exc)
        raise LLMError(f"Le modèle n'a pas renvoyé de JSON valide ({last_error}).")

    def _unreachable(self) -> str:
        return f"Ollama ne répond pas à {self.base_url}. Lance Ollama puis réessaie."
