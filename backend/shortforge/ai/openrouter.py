"""Adaptateur OpenRouter (API compatible OpenAI, catalogue et tarifs publics)."""

from __future__ import annotations

from typing import Any

from shortforge.ai.base import (
    AiError,
    AiProvider,
    AiTimeoutError,
    GenerationRequest,
    GenerationResult,
    InvalidKeyError,
    Model,
    ModelUnavailableError,
    QuotaError,
    TestResult,
)


def _price(value: Any) -> float | None:
    """Tarif par jeton (texte) → dollars par million de jetons ; None si absent ou illisible."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number < 0 else round(number * 1_000_000, 6)


class OpenRouterProvider(AiProvider):
    id = "openrouter"
    label = "OpenRouter"
    mode = "cloud"
    billing = "usage"
    needs_key = True
    default_base_url = "https://openrouter.ai/api/v1"
    key_help = "Clé créée sur openrouter.ai, page Keys. Les modèles « gratuits » restent soumis à des limites."

    def _headers(self) -> dict[str, str]:
        return {**super()._headers(), "X-Title": "ShortForge"}

    def list_models(self) -> list[Model]:
        res = self._call("GET", "/models", timeout_s=30)
        self._raise(res, "")
        out = []
        for m in res.json().get("data", []):
            if not isinstance(m, dict) or not m.get("id"):
                continue
            pricing = m.get("pricing") or {}
            p_in, p_out = _price(pricing.get("prompt")), _price(pricing.get("completion"))
            paid = None if p_in is None or p_out is None else (p_in > 0 or p_out > 0)
            out.append(Model(id=str(m["id"]), label=str(m.get("name") or m["id"]), provider_id=self.id, mode="cloud",
                             paid=paid, context_length=m.get("context_length"), price_in_per_mtok=p_in,
                             price_out_per_mtok=p_out, description=str(m.get("description") or "")[:300]))
        return out

    def is_paid(self, model_id: str) -> bool:
        try:
            model = next((m for m in self.list_models() if m.id == model_id), None)
        except AiError:
            return True
        return model is None or model.paid is not False

    def test(self) -> TestResult:
        if not self.api_key:
            count = len(self.list_models())
            return TestResult(False, f"OpenRouter répond ({count} modèles), mais aucune clé n'est enregistrée.", count)
        res = self._call("GET", "/key", timeout_s=20)
        self._raise(res, "")
        data = res.json().get("data") or {}
        remaining = data.get("limit_remaining")
        credit = "" if remaining is None else f" Crédit restant sur cette clé : {float(remaining):.2f} $."
        return TestResult(True, f"Clé OpenRouter valide.{credit}", key_checked=True)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        self._require_key()
        body: dict[str, Any] = {
            "model": request.model, "usage": {"include": True},
            "messages": [{"role": "system", "content": request.system}, {"role": "user", "content": request.prompt}],
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.max_tokens is not None:
            body["max_tokens"] = request.max_tokens
        if request.json_mode:
            body["response_format"] = {"type": "json_object"}
        res = self._call("POST", "/chat/completions", json=body, timeout_s=request.timeout_s)
        if res.status_code == 400 and request.json_mode:  # ce modele n'accepte pas le mode JSON : sans lui
            body.pop("response_format")
            res = self._call("POST", "/chat/completions", json=body, timeout_s=request.timeout_s)
        self._raise(res, request.model)
        data = res.json()
        if isinstance(data.get("error"), dict):  # OpenRouter peut renvoyer une erreur avec un statut 200
            self._raise_code(int(data["error"].get("code") or 500), str(data["error"].get("message", "")),
                             request.model)
        choices = data.get("choices") or [{}]
        usage = data.get("usage") or {}
        cost = usage.get("cost")
        return GenerationResult(text=str((choices[0].get("message") or {}).get("content") or ""),
                                model=str(data.get("model") or request.model),
                                input_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens"),
                                cost_usd=float(cost) if isinstance(cost, int | float) else None)

    def _raise(self, res: Any, model: str) -> None:
        if res.status_code < 400:
            return
        try:
            message = str((res.json().get("error") or {}).get("message") or "")
        except ValueError:
            message = res.text[:200]
        self._raise_code(res.status_code, message, model)

    def _raise_code(self, code: int, message: str, model: str) -> None:
        if code in (401, 403):
            raise InvalidKeyError("OpenRouter a refusé la clé API. Vérifie-la dans Réglages > Intelligence "
                                  "artificielle.")
        if code == 402:
            raise QuotaError("Crédit OpenRouter épuisé : recharge ton compte ou choisis un autre modèle.")
        if code == 429:
            raise QuotaError("Limite de requêtes OpenRouter atteinte. Réessaie dans quelques minutes.")
        if code == 404:
            raise ModelUnavailableError(f"Le modèle « {model} » n'est pas disponible chez OpenRouter.")
        if code in (408, 504, 524):
            raise AiTimeoutError("OpenRouter n'a pas répondu à temps. Réessaie.")
        raise AiError(f"OpenRouter a renvoyé une erreur {code} : {message[:200]}")
