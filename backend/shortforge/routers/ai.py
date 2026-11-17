"""Reglages > Intelligence artificielle : fournisseurs, cles, modeles et choix par tache.

Une cle API n'est jamais renvoyee : l'interface ne recoit que « cle enregistree » et ses derniers
caracteres. Les modeles listes sont ceux que le fournisseur declare au moment de la demande.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from shortforge.ai.base import TEXT_TASKS, AiError, PaidConfirmationError
from shortforge.ai.router import PROVIDERS, Choice, TaskRouter, secret_name
from shortforge.deps import get_runtime, get_session
from shortforge.integrations.ollama import LLMError
from shortforge.models import AiCall, AiProviderConfig, TaskModel, utcnow
from shortforge.runtime import Runtime
from shortforge.services.youtube import token_path

router = APIRouter(prefix="/api", tags=["intelligence artificielle"])


def get_router(runtime: Runtime = Depends(get_runtime)) -> TaskRouter:
    if not isinstance(runtime.llm, TaskRouter):
        raise HTTPException(http.HTTP_503_SERVICE_UNAVAILABLE, "Routage des modèles indisponible.")
    return runtime.llm


def _known(provider_id: str) -> None:
    if provider_id not in PROVIDERS:
        raise HTTPException(http.HTTP_404_NOT_FOUND, f"Fournisseur d'IA inconnu : {provider_id}.")


def _config(session: Session, provider_id: str) -> AiProviderConfig:
    row = session.get(AiProviderConfig, provider_id)
    if row is None:
        row = AiProviderConfig(id=provider_id)
        session.add(row)
        session.flush()
    return row


def _provider_out(session: Session, ai: TaskRouter, provider_id: str) -> dict[str, Any]:
    cls = PROVIDERS[provider_id]
    row = session.get(AiProviderConfig, provider_id)
    hint = ai.vault.hint(session, secret_name(provider_id)) if cls.needs_key else None
    return {
        "id": cls.id, "label": cls.label, "type": cls.type, "mode": cls.mode, "billing": cls.billing,
        "needs_key": cls.needs_key, "key_set": hint is not None, "key_hint": hint or "", "key_help": cls.key_help,
        "base_url": ai.base_url(session, provider_id), "default_base_url": cls.default_base_url,
        "base_url_editable": cls.base_url_editable,
        "reachable": ai.reachable(session, provider_id),
        "last_test": None if row is None or row.last_test_ok is None else {
            "ok": row.last_test_ok, "message": row.last_test_message, "key_checked": row.last_test_key_checked,
            "at": row.last_test_at.isoformat() if row.last_test_at else None},
    }


@router.get("/ai/providers")
def list_providers(session: Session = Depends(get_session),
                   ai: TaskRouter = Depends(get_router)) -> list[dict[str, Any]]:
    return [_provider_out(session, ai, provider_id) for provider_id in PROVIDERS]


class ProviderIn(BaseModel):
    base_url: str | None = Field(default=None, max_length=300)
    api_key: str | None = Field(default=None, min_length=8, max_length=500)


@router.put("/ai/providers/{provider_id}")
def update_provider(provider_id: str, payload: ProviderIn, session: Session = Depends(get_session),
                    ai: TaskRouter = Depends(get_router)) -> dict[str, Any]:
    _known(provider_id)
    cls = PROVIDERS[provider_id]
    row = _config(session, provider_id)
    if payload.base_url is not None:
        url = payload.base_url.strip().rstrip("/")
        if not cls.base_url_editable:
            raise HTTPException(http.HTTP_400_BAD_REQUEST, f"L'adresse de {cls.label} ne se modifie pas.")
        if url and not url.startswith(("http://", "https://")):
            raise HTTPException(http.HTTP_400_BAD_REQUEST, "L'adresse doit commencer par http:// ou https://.")
        row.base_url = url
    if payload.api_key is not None:
        if not cls.needs_key:
            raise HTTPException(http.HTTP_400_BAD_REQUEST, f"{cls.label} n'utilise pas de clé API.")
        ai.vault.set(session, secret_name(provider_id), payload.api_key)  # 503 clair si le coffre est indisponible
    row.last_test_ok, row.last_test_message, row.last_test_at = None, "", None  # l'ancien test ne vaut plus
    session.flush()
    return _provider_out(session, ai, provider_id)


@router.delete("/ai/providers/{provider_id}/key")
def delete_key(provider_id: str, session: Session = Depends(get_session),
               ai: TaskRouter = Depends(get_router)) -> dict[str, Any]:
    _known(provider_id)
    ai.vault.delete(session, secret_name(provider_id))
    row = _config(session, provider_id)
    row.last_test_ok, row.last_test_message, row.last_test_at = None, "", None
    return _provider_out(session, ai, provider_id)


@router.post("/ai/providers/{provider_id}/test")
def test_provider(provider_id: str, session: Session = Depends(get_session),
                  ai: TaskRouter = Depends(get_router)) -> dict[str, Any]:
    """Vraie requete au fournisseur. Le resultat dit si la cle a reellement ete verifiee."""
    _known(provider_id)
    row = _config(session, provider_id)
    try:
        provider = ai.provider(session, provider_id)
        try:
            result = provider.test()
        finally:
            provider.close()
        ok, message, kind = result.ok, result.message, ""
        key_checked, count = result.key_checked, result.models_count
    except LLMError as exc:
        ok, message, kind, key_checked, count = False, str(exc), getattr(exc, "kind", "error"), False, None
    row.last_test_ok, row.last_test_message, row.last_test_at = ok, message[:300], utcnow()
    row.last_test_key_checked = key_checked
    session.flush()
    return {"ok": ok, "message": message, "kind": kind, "key_checked": key_checked, "models_count": count}


@router.get("/ai/providers/{provider_id}/models")
def list_models(provider_id: str, refresh: bool = Query(default=False), session: Session = Depends(get_session),
                ai: TaskRouter = Depends(get_router)) -> list[dict[str, Any]]:
    _known(provider_id)
    return [m.as_dict() for m in ai.models(session, provider_id, refresh=refresh)]


def _task_out(session: Session, ai: TaskRouter, task: str) -> dict[str, Any]:
    plan = ai.assignment(session, task)
    info = ai.describe(session, task)
    primary_cls = PROVIDERS.get(plan.primary.provider_id)
    return {
        "task": task, "label": TEXT_TASKS[task], "is_default": plan.is_default,
        "mode": info["mode"], "configured": info["configured"],
        "provider_id": plan.primary.provider_id, "provider_label": primary_cls.label if primary_cls else "",
        "model": plan.primary.model,
        "fallback_provider_id": plan.fallback.provider_id if plan.fallback else "",
        "fallback_model": plan.fallback.model if plan.fallback else "",
        "allow_paid_fallback": plan.allow_paid_fallback, "temperature": plan.temperature,
        "max_tokens": plan.max_tokens, "strict_json": plan.strict_json, "timeout_s": plan.timeout_s,
    }


@router.get("/ai/tasks")
def list_tasks(session: Session = Depends(get_session), ai: TaskRouter = Depends(get_router)) -> list[dict[str, Any]]:
    return [_task_out(session, ai, task) for task in TEXT_TASKS]


class TaskIn(BaseModel):
    provider_id: str
    model: str = Field(min_length=1, max_length=200)
    fallback_provider_id: str = ""
    fallback_model: str = Field(default="", max_length=200)
    allow_paid_fallback: bool = False
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=64, le=200_000)
    strict_json: bool = True
    timeout_s: float | None = Field(default=None, ge=10, le=3600)
    confirm_paid: bool = False  # accord explicite pour un modele payant
    apply_to_all: bool = False  # « utiliser le meme modele partout »


@router.put("/ai/tasks/{task}")
def set_task(task: str, payload: TaskIn, session: Session = Depends(get_session),
             ai: TaskRouter = Depends(get_router)) -> list[dict[str, Any]]:
    if task not in TEXT_TASKS:
        raise HTTPException(http.HTTP_404_NOT_FOUND, f"Tâche inconnue : {task}.")
    _known(payload.provider_id)
    if payload.fallback_model:
        _known(payload.fallback_provider_id)
    primary = Choice(payload.provider_id, payload.model.strip())
    _must_exist(session, ai, primary)
    _known_price(session, ai, primary)
    targets = list(TEXT_TASKS) if payload.apply_to_all else [task]
    changed = any(ai.assignment(session, name).primary != primary for name in targets)
    if changed and ai.is_paid(session, primary) and not payload.confirm_paid:
        raise PaidConfirmationError(
            f"« {primary.model} » chez {PROVIDERS[primary.provider_id].label} peut être payant (à l'usage ou via un "
            "abonnement). Confirme pour l'utiliser.")
    if payload.fallback_model:
        fallback = Choice(payload.fallback_provider_id, payload.fallback_model.strip())
        _must_exist(session, ai, fallback)
        _known_price(session, ai, fallback)
    for name in targets:
        row = session.get(TaskModel, name)
        if row is None:
            row = TaskModel(task=name, provider_id=primary.provider_id, model=primary.model)
            session.add(row)
        row.provider_id, row.model = primary.provider_id, primary.model
        row.fallback_provider_id = payload.fallback_provider_id if payload.fallback_model else ""
        row.fallback_model = payload.fallback_model.strip()
        row.allow_paid_fallback = payload.allow_paid_fallback and bool(payload.fallback_model)
        row.temperature, row.max_tokens = payload.temperature, payload.max_tokens
        row.strict_json, row.timeout_s = payload.strict_json, payload.timeout_s
    session.flush()
    return list_tasks(session, ai)


def _known_price(session: Session, ai: TaskRouter, choice: Choice) -> None:
    """Un modele paye a l'usage sans tarif publie ne peut pas etre plafonne : il est refuse."""
    if ai.billing(choice) != "usage":
        return
    model = ai.price(session, choice)
    if model is None or model.price_in_per_mtok is None or model.price_out_per_mtok is None:
        raise HTTPException(http.HTTP_400_BAD_REQUEST, f"Le tarif de « {choice.model} » n'est pas publié : ShortForge "
                            "ne peut pas le plafonner. Choisis un modèle au tarif affiché.")


def _must_exist(session: Session, ai: TaskRouter, choice: Choice) -> None:
    """Refuse un modele que le fournisseur ne declare pas (pas de reference inventee)."""
    try:
        known = {m.id for m in ai.models(session, choice.provider_id, refresh=True)}
    except AiError as exc:
        raise HTTPException(http.HTTP_502_BAD_GATEWAY, f"Impossible de vérifier le modèle : {exc}") from exc
    if choice.model not in known:
        label = PROVIDERS[choice.provider_id].label
        raise HTTPException(http.HTTP_400_BAD_REQUEST, f"« {choice.model} » ne figure pas dans les modèles de {label}.")


@router.delete("/ai/tasks/{task}")
def reset_task(task: str, session: Session = Depends(get_session),
               ai: TaskRouter = Depends(get_router)) -> list[dict[str, Any]]:
    """Revient au reglage d'origine (Ollama et le modele du fichier de reglages)."""
    row = session.get(TaskModel, task)
    if row is not None:
        session.delete(row)
        session.flush()
    return list_tasks(session, ai)


@router.get("/ai/calls")
def list_calls(limit: int = Query(default=50, ge=1, le=500), session: Session = Depends(get_session),
               ai: TaskRouter = Depends(get_router)) -> list[dict[str, Any]]:
    ai.flush_log()
    rows = session.scalars(select(AiCall).order_by(AiCall.created_at.desc()).limit(limit)).all()
    return [{"id": r.id, "at": r.created_at.isoformat(), "task": r.task, "provider_id": r.provider_id,
             "model": r.model, "mode": r.mode, "ok": r.ok, "used_fallback": r.used_fallback,
             "error_kind": r.error_kind, "error": r.error, "duration_ms": r.duration_ms,
             "input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "cost_usd": r.cost_usd,
             "billing": "free" if r.mode == "local" else ai.billing(Choice(r.provider_id, r.model))} for r in rows]


@router.get("/security")
def security_status(runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    """Ce qui protege les secrets sur cette machine (aucune valeur secrete n'est renvoyee)."""
    available = runtime.vault.available
    message = ""
    if not available:
        try:
            runtime.vault.encrypt("test")
        except Exception as exc:
            message = str(exc)
    return {
        "vault_available": available, "vault_protection": runtime.vault.protection if available else "",
        "vault_message": message,
        "api_token_required": bool(runtime.settings.shortforge_api_token),
        "youtube_token_encrypted": runtime.youtube.token_encrypted(token_path(runtime.settings)),
    }
