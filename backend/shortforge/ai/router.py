"""Routage par tache : quel fournisseur et quel modele pour les idees, le script, l'analyse.

Sans reglage enregistre, le comportement est celui des versions 0.5.x : Ollama a l'adresse et avec le
modele du fichier de reglages. Un modele de secours payant n'est jamais utilise sans accord explicite.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from shortforge.ai.base import (
    TEXT_TASKS,
    AiError,
    AiProvider,
    GenerationRequest,
    Model,
    NotConfiguredError,
    PaidConfirmationError,
)
from shortforge.ai.ollama import OllamaCloudProvider, OllamaLocalProvider
from shortforge.ai.openrouter import OpenRouterProvider
from shortforge.config import Settings
from shortforge.db import Database
from shortforge.integrations.ollama import LLMError, _parse_json
from shortforge.models import AiCall, AiProviderConfig, TaskModel
from shortforge.vault import Vault, VaultError

logger = logging.getLogger("shortforge.ai")
PROVIDERS: dict[str, type[AiProvider]] = {p.id: p for p in (OllamaLocalProvider, OllamaCloudProvider,
                                                            OpenRouterProvider)}
MODELS_CACHE_S = 300


def secret_name(provider_id: str) -> str:
    return f"ai:{provider_id}"


@dataclass(frozen=True, slots=True)
class Choice:
    provider_id: str
    model: str


@dataclass(frozen=True, slots=True)
class Assignment:
    task: str
    primary: Choice
    fallback: Choice | None
    allow_paid_fallback: bool
    temperature: float | None
    max_tokens: int | None
    strict_json: bool
    timeout_s: float | None
    is_default: bool


class TaskClient:
    """Ce que les services recoivent : un modele de texte deja regle pour une tache."""

    def __init__(self, router: TaskRouter, task: str) -> None:
        self._router, self.task = router, task

    def generate_json(self, system: str, prompt: str, *, temperature: float | None = None) -> dict[str, Any]:
        return self._router.generate_json(system, prompt, temperature=temperature, task=self.task)


class TaskRouter:
    def __init__(self, settings: Settings, vault: Vault, *, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self.vault = vault
        self._transport = transport
        self._db: Database | None = None
        self._pending: list[AiCall] = []
        self._lock = threading.Lock()
        self._models: dict[tuple[str, str], tuple[float, list[Model]]] = {}
        self._last = threading.local()

    def bind(self, db: Database) -> None:
        self._db = db

    def for_task(self, task: str) -> TaskClient:
        if task not in TEXT_TASKS:
            raise ValueError(f"Tâche inconnue : {task}.")
        return TaskClient(self, task)

    def last_used(self) -> dict[str, Any] | None:
        """Moteur reellement utilise par le dernier appel reussi de ce fil d'execution (pour l'afficher)."""
        value: dict[str, Any] | None = getattr(self._last, "value", None)
        return value

    def describe(self, session: Session, task: str) -> dict[str, Any]:
        """Moteur prevu pour une tache, sans rien appeler : fournisseur, modele, local ou cloud, pret ou non."""
        plan = self.assignment(session, task)
        cls = PROVIDERS.get(plan.primary.provider_id)
        key_ok = cls is not None and (not cls.needs_key
                                      or self.vault.hint(session, secret_name(plan.primary.provider_id)) is not None)
        return {"task": task, "provider_id": plan.primary.provider_id, "provider_label": cls.label if cls else "",
                "model": plan.primary.model, "mode": self._mode(plan.primary),
                "configured": bool(plan.primary.model) and key_ok}

    def _mode(self, choice: Choice) -> str:
        """Un modele « :cloud » d'Ollama passe par le PC mais s'execute dans le cloud."""
        cls = PROVIDERS.get(choice.provider_id)
        if cls is None or cls.mode == "cloud":
            return "cloud"
        probe = cls(transport=self._transport)
        try:
            return "cloud" if probe.is_paid(choice.model) else "local"
        finally:
            probe.close()

    # --- fournisseurs ---
    def base_url(self, session: Session, provider_id: str) -> str:
        cls = PROVIDERS[provider_id]
        row = session.get(AiProviderConfig, provider_id)
        if cls.base_url_editable and row is not None and row.base_url:
            return row.base_url
        return self.settings.ollama_url if provider_id == OllamaLocalProvider.id else cls.default_base_url

    def provider(self, session: Session, provider_id: str) -> AiProvider:
        cls = PROVIDERS.get(provider_id)
        if cls is None:
            raise NotConfiguredError(f"Fournisseur d'IA inconnu : {provider_id}.")
        key: str | None = None
        if cls.needs_key and self.vault.hint(session, secret_name(provider_id)) is not None:
            try:
                key = self.vault.get(session, secret_name(provider_id))
            except VaultError as exc:
                raise NotConfiguredError(f"{cls.label} : {exc}") from exc
        return cls(self.base_url(session, provider_id), key, transport=self._transport)

    def models(self, session: Session, provider_id: str, *, refresh: bool = False) -> list[Model]:
        """Modeles declares par le fournisseur (cache court pour ne pas le rappeler a chaque ecran)."""
        cache_key = (provider_id, self.base_url(session, provider_id))
        cached = self._models.get(cache_key)
        if cached and not refresh and time.monotonic() - cached[0] < MODELS_CACHE_S:
            return cached[1]
        provider = self.provider(session, provider_id)
        try:
            models = provider.list_models()
        finally:
            provider.close()
        self._models[cache_key] = (time.monotonic(), models)
        return models

    def is_paid(self, session: Session, choice: Choice) -> bool:
        """Vrai si l'usage de ce modele peut couter quelque chose (ou si on ne sait pas le prouver gratuit)."""
        cls = PROVIDERS.get(choice.provider_id)
        if cls is None:
            return True
        if cls is OpenRouterProvider:
            try:
                model = next((m for m in self.models(session, choice.provider_id) if m.id == choice.model), None)
            except LLMError:
                return True
            return model is None or model.paid is not False
        provider = cls(self.base_url(session, choice.provider_id), transport=self._transport)
        try:
            return provider.is_paid(choice.model)
        finally:
            provider.close()

    # --- reglage par tache ---
    def assignment(self, session: Session, task: str) -> Assignment:
        row = session.get(TaskModel, task)
        if row is None:
            return Assignment(task, Choice(OllamaLocalProvider.id, self.settings.ollama_model), None, False,
                              None, None, True, None, True)
        fallback = Choice(row.fallback_provider_id, row.fallback_model) if row.fallback_model else None
        return Assignment(task, Choice(row.provider_id, row.model), fallback, row.allow_paid_fallback,
                          row.temperature, row.max_tokens, row.strict_json, row.timeout_s, False)

    # --- generation ---
    def generate_json(self, system: str, prompt: str, *, temperature: float | None = None,
                      task: str = "script") -> dict[str, Any]:
        if self._db is None:
            raise LLMError("Moteur de texte non initialisé.")
        with self._db.session() as session:
            plan = self.assignment(session, task)
            if temperature is None:
                temperature = plan.temperature if plan.temperature is not None else self.settings.ollama_temperature
            request = GenerationRequest(task=task, model=plan.primary.model, system=system, prompt=prompt,
                                        temperature=temperature, max_tokens=plan.max_tokens,
                                        json_mode=plan.strict_json,
                                        timeout_s=plan.timeout_s or self.settings.ollama_timeout_s)
            try:
                return self._run(session, plan.primary, request, used_fallback=False)
            except AiError as exc:
                if plan.fallback is None or not exc.retry_with_fallback:
                    raise
                if self.is_paid(session, plan.fallback) and not plan.allow_paid_fallback:
                    raise PaidConfirmationError(
                        f"{exc} Le modèle de secours « {plan.fallback.model} » est payant : il n'a pas été utilisé. "
                        "Autorise-le dans Réglages > Intelligence artificielle si tu veux ce repli.") from exc
                logger.warning("Tâche %s : repli sur %s/%s (%s).", task, plan.fallback.provider_id,
                               plan.fallback.model, exc.kind)
                fallback_request = GenerationRequest(**{**_fields(request), "model": plan.fallback.model})
                return self._run(session, plan.fallback, fallback_request, used_fallback=True)

    def _run(self, session: Session, choice: Choice, request: GenerationRequest, *,
             used_fallback: bool) -> dict[str, Any]:
        cls = PROVIDERS.get(choice.provider_id)
        started = time.monotonic()
        log = AiCall(task=request.task, provider_id=choice.provider_id, model=choice.model,
                     mode=self._mode(choice), ok=False, used_fallback=used_fallback)
        self._last.value = None
        try:
            if not choice.model:
                raise NotConfiguredError("Aucun modèle de texte choisi : choisis-en un dans Réglages > Intelligence "
                                         "artificielle (ou renseigne OLLAMA_MODEL dans le fichier de réglages).")
            provider = self.provider(session, choice.provider_id)
            try:
                last = ""
                for _ in range(2):  # une seconde chance si le modele renvoie un JSON invalide
                    result = provider.generate(request)
                    log.input_tokens = (log.input_tokens or 0) + (result.input_tokens or 0) or None
                    log.output_tokens = (log.output_tokens or 0) + (result.output_tokens or 0) or None
                    if result.cost_usd is not None:
                        log.cost_usd = (log.cost_usd or 0.0) + result.cost_usd
                    try:
                        data = _parse_json(result.text)
                    except ValueError as exc:
                        last = str(exc)
                        continue
                    log.ok = True
                    self._last.value = {"task": request.task, "provider_id": choice.provider_id,
                                        "provider_label": cls.label if cls else "", "model": result.model,
                                        "mode": log.mode, "used_fallback": used_fallback}
                    return data
                raise AiError(f"Le modèle n'a pas renvoyé de JSON valide ({last}).")
            finally:
                provider.close()
        except AiError as exc:
            log.error_kind, log.error = exc.kind, str(exc)[:300]
            raise
        finally:
            log.duration_ms = int((time.monotonic() - started) * 1000)
            self._record(log)

    # --- journal ---
    def _record(self, call: AiCall) -> None:
        with self._lock:
            self._pending.append(call)
        self.flush_log()

    def flush_log(self) -> None:
        """Ecrit le journal en attente ; si la base est occupee, il sera ecrit au prochain appel."""
        if self._db is None:
            return
        with self._lock:
            batch, self._pending = self._pending, []
        if not batch:
            return
        try:
            with self._db.session() as session:
                session.add_all(batch)
        except SQLAlchemyError:
            logger.warning("Journal des appels IA en attente (base occupée).")
            with self._lock:
                self._pending = batch + self._pending

    # --- compatibilite avec l'ecran d'etat ---
    def is_running(self) -> bool:
        if self._db is None:
            return False
        with self._db.session() as session:
            try:
                provider = self.provider(session, self.assignment(session, "ideas").primary.provider_id)
            except LLMError:
                return False
        try:
            return provider.is_available()
        finally:
            provider.close()


def _fields(request: GenerationRequest) -> dict[str, Any]:
    return {name: getattr(request, name) for name in request.__dataclass_fields__}
