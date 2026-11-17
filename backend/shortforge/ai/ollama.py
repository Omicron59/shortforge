"""Adaptateurs Ollama : sur ton PC (local) et Ollama Cloud (ollama.com, avec une cle)."""

from __future__ import annotations

from typing import Any

from shortforge.ai.base import (
    AiError,
    AiProvider,
    GenerationRequest,
    GenerationResult,
    InvalidKeyError,
    Model,
    ModelUnavailableError,
    QuotaError,
    TestResult,
)


def is_cloud_tag(entry: dict[str, Any]) -> bool:
    """Modele « :cloud » d'Ollama : installe en local mais execute sur les serveurs d'Ollama."""
    name = str(entry.get("name", ""))
    tag = name.split(":", 1)[1] if ":" in name else ""
    return bool(entry.get("remote_host") or entry.get("remote_model")) or tag == "cloud" or tag.endswith("-cloud")


class _OllamaBase(AiProvider):
    def _models(self) -> list[dict[str, Any]]:
        res = self._call("GET", "/api/tags", timeout_s=15)
        self._raise(res, "")
        models = res.json().get("models", [])
        return [m for m in models if isinstance(m, dict) and m.get("name")]

    def _raise(self, res: Any, model: str) -> None:
        if res.status_code < 400:
            return
        detail = res.text[:200]
        if res.status_code in (401, 403):
            raise InvalidKeyError(f"{self.label} a refusé la clé API. Vérifie-la dans Réglages > Intelligence "
                                  "artificielle.")
        if res.status_code in (402, 429):
            raise QuotaError(f"{self.label} : quota ou limite d'utilisation atteint. Réessaie plus tard.")
        if res.status_code == 404:
            raise ModelUnavailableError(self._missing(model))
        raise AiError(f"{self.label} a renvoyé une erreur {res.status_code} : {detail}")

    def _missing(self, model: str) -> str:
        return f"Le modèle « {model} » n'est pas disponible chez {self.label}."

    def ping(self) -> bool:
        """Reponse rapide (2 s) pour la pastille d'etat, sans attendre un test complet."""
        try:
            return self._call("GET", "/api/tags", timeout_s=2).status_code < 400
        except AiError:
            return False

    def generate(self, request: GenerationRequest) -> GenerationResult:
        self._require_key()
        options: dict[str, Any] = {}
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens
        body: dict[str, Any] = {
            "model": request.model, "stream": False, "options": options,
            "messages": [{"role": "system", "content": request.system}, {"role": "user", "content": request.prompt}],
        }
        if request.json_mode:
            body["format"] = "json"
        res = self._call("POST", "/api/chat", json=body, timeout_s=request.timeout_s)
        if res.status_code == 404:
            resolved = self._resolve(request.model)
            if resolved:  # nom ecrit sans son etiquette « :xxx »
                body["model"] = resolved
                res = self._call("POST", "/api/chat", json=body, timeout_s=request.timeout_s)
        self._raise(res, request.model)
        data = res.json()
        return GenerationResult(text=str(data.get("message", {}).get("content", "")), model=str(body["model"]),
                                input_tokens=data.get("prompt_eval_count"), output_tokens=data.get("eval_count"))

    def _resolve(self, model: str) -> str | None:
        if ":" in model:
            return None
        try:
            names = [str(m["name"]) for m in self._models()]
        except AiError:
            return None
        return next((n for n in names if n.split(":", 1)[0] == model), None)


class OllamaLocalProvider(_OllamaBase):
    id = "ollama"
    label = "Ollama (via mon PC)"
    mode = "local"
    billing = "free"
    needs_key = False
    default_base_url = "http://127.0.0.1:11434"
    base_url_editable = True

    def list_models(self) -> list[Model]:
        out = []
        for m in self._models():
            cloud = is_cloud_tag(m)
            out.append(Model(
                id=str(m["name"]), label=str(m["name"]), provider_id=self.id, mode="cloud" if cloud else "local",
                paid=cloud, size_bytes=None if cloud else m.get("size"),
                description="Exécuté sur les serveurs d'Ollama (abonnement Ollama)." if cloud
                else str((m.get("details") or {}).get("parameter_size") or "")))
        return out

    def is_paid(self, model_id: str) -> bool:
        tag = model_id.split(":", 1)[1] if ":" in model_id else ""
        return tag == "cloud" or tag.endswith("-cloud")

    def test(self) -> TestResult:
        models = self._models()
        return TestResult(True, f"Ollama détecté : {len(models)} modèle(s) installé(s).", len(models))

    def _unreachable(self) -> str:
        return f"Ollama ne répond pas à {self.base_url}. Lance Ollama puis réessaie."

    def _missing(self, model: str) -> str:
        return f"Le modèle « {model} » n'est pas installé : lance `ollama pull {model}`."


class OllamaCloudProvider(_OllamaBase):
    id = "ollama_cloud"
    label = "Ollama Cloud"
    mode = "cloud"
    billing = "subscription"
    needs_key = True
    default_base_url = "https://ollama.com"
    key_help = "Clé créée sur ollama.com, dans les réglages de ton compte (Keys)."

    def list_models(self) -> list[Model]:
        return [Model(id=str(m["name"]), label=str(m["name"]), provider_id=self.id, mode="cloud", paid=True,
                      description="Inclus dans l'abonnement Ollama, selon ses limites.") for m in self._models()]

    def test(self) -> TestResult:
        models = self._models()
        if not self.api_key:
            return TestResult(False, f"Ollama Cloud répond ({len(models)} modèles), mais aucune clé n'est "
                              "enregistrée : la génération ne fonctionnera pas.", len(models))
        # La liste des modeles est publique : elle ne prouve pas que la cle est valide.
        return TestResult(True, f"Ollama Cloud répond ({len(models)} modèles). La clé n'est pas vérifiée par ce "
                          "test : elle le sera à la première génération.", len(models), key_checked=False)
