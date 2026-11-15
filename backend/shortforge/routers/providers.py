"""Moteurs video : liste, etat de configuration et reglages."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from shortforge.deps import get_runtime, get_session
from shortforge.models import Provider
from shortforge.pipeline import PipelineError
from shortforge.providers.registry import CONFIG_KEYS, ProviderRegistry
from shortforge.runtime import Runtime
from shortforge.schemas import ProviderOut, ProviderPatch
from shortforge.services.provider_catalog import CATALOG

router = APIRouter(prefix="/api/providers", tags=["moteurs"])

_ORDER = {spec.id: i for i, spec in enumerate(CATALOG)}


def _out(row: Provider, registry: ProviderRegistry) -> ProviderOut:
    out = ProviderOut.model_validate(row)
    provider = registry.get(row.id)
    out.configured = provider.is_configured()
    out.configuration_hint = "" if out.configured else provider.not_configured_message()
    out.operations = sorted(op.value for op in provider.operations)
    return out


@router.get("", response_model=list[ProviderOut])
def list_providers(session: Session = Depends(get_session),
                   runtime: Runtime = Depends(get_runtime)) -> list[ProviderOut]:
    registry = runtime.providers(session)
    rows = sorted(session.scalars(select(Provider)), key=lambda p: _ORDER.get(p.id, len(_ORDER)))
    return [_out(p, registry) for p in rows]


@router.patch("/{provider_id}", response_model=ProviderOut)
def update_provider(provider_id: str, payload: ProviderPatch, session: Session = Depends(get_session),
                    runtime: Runtime = Depends(get_runtime)) -> ProviderOut:
    row = session.get(Provider, provider_id)
    if row is None:
        raise PipelineError(f"Moteur vidéo inconnu : {provider_id}.")
    if payload.enabled is not None:
        if provider_id == "comfyui_local" and not payload.enabled:
            raise PipelineError("ComfyUI local est le moteur de secours : il ne peut pas être désactivé.")
        row.enabled = payload.enabled
    if payload.cost_per_second_usd is not None:
        if row.kind == "local":
            raise PipelineError("Un moteur local est gratuit : pas de tarif à régler.")
        row.cost_per_second_usd = payload.cost_per_second_usd
    if payload.config is not None:
        unknown = set(payload.config) - CONFIG_KEYS
        if unknown:
            raise PipelineError(f"Réglage non autorisé : {', '.join(sorted(unknown))}. Les clés API vont dans le .env.")
        merged = {**(row.config or {}), **payload.config}
        row.config = {k: v for k, v in merged.items() if v.strip()}  # valeur vide = reglage par defaut
    session.flush()
    return _out(row, runtime.providers(session))
