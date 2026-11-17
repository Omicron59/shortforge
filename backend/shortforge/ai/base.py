"""Interface commune des fournisseurs d'IA (equivalent Python de l'interface `AiProvider`)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any, ClassVar, Literal

import httpx

from shortforge.integrations.ollama import LLMError

Mode = Literal["local", "cloud"]
Billing = Literal["free", "subscription", "usage"]

# Taches de texte reellement branchees dans l'application.
TEXT_TASKS: dict[str, str] = {
    "ideas": "Génération d'idées",
    "script": "Écriture et correction du script",
    "storyboard": "Storyboard (intentions et prompts visuels)",
    "variants": "Variantes (idées, hooks)",
    "analysis": "Analyse (formats, style, résultats, extraits)",
}


class AiError(LLMError):
    """Erreur d'un fournisseur ; `kind` permet a l'interface et au repli de la reconnaitre."""

    kind: ClassVar[str] = "error"
    retry_with_fallback: ClassVar[bool] = False


class NotConfiguredError(AiError):
    kind = "not_configured"
    retry_with_fallback = True


class InvalidKeyError(AiError):
    kind = "invalid_key"
    retry_with_fallback = True


class QuotaError(AiError):
    kind = "quota"
    retry_with_fallback = True


class ModelUnavailableError(AiError):
    kind = "model_unavailable"
    retry_with_fallback = True


class AiTimeoutError(AiError):
    kind = "timeout"
    retry_with_fallback = True


class UnreachableError(AiError):
    kind = "unreachable"
    retry_with_fallback = True


class BudgetExceededError(AiError):
    """Un appel payant depasserait le plafond du jour ou du mois : il n'est pas envoye."""

    kind = "budget"
    retry_with_fallback = True


class UnknownPriceError(AiError):
    """Modele paye a l'usage dont le tarif n'est pas publie : il n'est pas utilise."""

    kind = "unknown_price"
    retry_with_fallback = True


class PaidConfirmationError(AiError):
    """Un modele payant serait utilise sans accord explicite."""

    kind = "needs_paid_confirmation"


@dataclass(frozen=True, slots=True)
class Model:
    """Un modele tel que le fournisseur le declare. Aucun champ n'est invente : inconnu = None."""

    id: str
    label: str
    provider_id: str
    mode: Mode
    paid: bool | None  # None = tarif inconnu (traite comme payant)
    context_length: int | None = None
    size_bytes: int | None = None
    price_in_per_mtok: float | None = None  # dollars par million de jetons en entree
    price_out_per_mtok: float | None = None
    description: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    task: str
    model: str
    system: str
    prompt: str
    temperature: float | None = None
    max_tokens: int | None = None
    json_mode: bool = True
    timeout_s: float | None = None


@dataclass(frozen=True, slots=True)
class GenerationResult:
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


@dataclass(frozen=True, slots=True)
class TestResult:
    ok: bool
    message: str
    models_count: int | None = None
    key_checked: bool = False  # la cle a-t-elle vraiment ete verifiee par le fournisseur ?

    __test__ = False  # ce n'est pas une classe de test pytest


class AiProvider(ABC):
    """Un adaptateur par fournisseur. Les instances sont creees a la demande, avec l'adresse et la cle."""

    id: ClassVar[str]
    label: ClassVar[str]
    type: ClassVar[str] = "text"
    mode: ClassVar[Mode]
    billing: ClassVar[Billing]
    needs_key: ClassVar[bool]
    default_base_url: ClassVar[str]
    base_url_editable: ClassVar[bool] = False
    key_help: ClassVar[str] = ""

    def __init__(self, base_url: str = "", api_key: str | None = None, *, timeout_s: float = 300,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.base_url = (base_url or self.default_base_url).rstrip("/")
        self.api_key = api_key
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout_s, transport=transport,
                                  headers=self._headers())

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def close(self) -> None:
        self._http.close()

    def is_available(self) -> bool:
        try:
            self.list_models()
        except LLMError:
            return False
        return True

    @abstractmethod
    def list_models(self) -> list[Model]: ...

    @abstractmethod
    def generate(self, request: GenerationRequest) -> GenerationResult: ...

    @abstractmethod
    def test(self) -> TestResult: ...

    def is_paid(self, model_id: str) -> bool:
        """Par prudence, tout ce qui n'est pas prouve gratuit est considere payant."""
        return self.billing != "free"

    # --- outils communs ---
    def _call(self, method: str, path: str, *, timeout_s: float | None = None, **kwargs: Any) -> httpx.Response:
        try:
            if timeout_s is not None:
                kwargs["timeout"] = timeout_s
            return self._http.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise AiTimeoutError(f"{self.label} n'a pas répondu à temps. Réessaie ou augmente le délai "
                                 "maximum.") from exc
        except httpx.HTTPError as exc:
            raise UnreachableError(self._unreachable()) from exc

    def _unreachable(self) -> str:
        return f"{self.label} ne répond pas à {self.base_url}."

    def _require_key(self) -> None:
        if self.needs_key and not self.api_key:
            raise NotConfiguredError(f"Aucune clé API enregistrée pour {self.label} : ajoute-la dans "
                                     "Réglages > Intelligence artificielle.")
