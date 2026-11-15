"""Reglages de l'application : regles de choix des moteurs, tendances manuelles, workflow image."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.deps import get_session, get_settings_dep
from shortforge.models import Provider
from shortforge.pipeline import PipelineError
from shortforge.services.app_settings import get_value, set_value
from shortforge.services.engine_selection import IMPORTANCE_LABELS, PRESET_RULES

router = APIRouter(prefix="/api/settings", tags=["parametres"])


class SettingsIn(BaseModel):
    engine_rules: dict[str, str] | None = None
    manual_trends: list[str] | None = Field(default=None, max_length=100)
    comfyui_image_workflow: str | None = None


@router.get("")
def read_settings(session: Session = Depends(get_session),
                  settings: Settings = Depends(get_settings_dep)) -> dict[str, Any]:
    return {
        "engine_rules": get_value(session, "engine_rules", PRESET_RULES["standard"]),
        "preset_rules": PRESET_RULES,
        "manual_trends": get_value(session, "manual_trends", []),
        "comfyui_image_workflow": get_value(session, "comfyui_image_workflow", settings.comfyui_image_workflow),
        "youtube_publish_enabled": settings.youtube_publish_enabled,
    }


@router.put("")
def update_settings(payload: SettingsIn, session: Session = Depends(get_session),
                    settings: Settings = Depends(get_settings_dep)) -> dict[str, Any]:
    if payload.engine_rules is not None:
        for importance, provider_id in payload.engine_rules.items():
            if importance not in IMPORTANCE_LABELS:
                raise PipelineError(f"Type de scène inconnu : {importance}.")
            if session.get(Provider, provider_id) is None:
                raise PipelineError(f"Moteur vidéo inconnu : {provider_id}.")
        set_value(session, "engine_rules", payload.engine_rules)
    if payload.manual_trends is not None:
        set_value(session, "manual_trends", [t.strip()[:200] for t in payload.manual_trends if t.strip()])
    if payload.comfyui_image_workflow is not None:
        set_value(session, "comfyui_image_workflow", payload.comfyui_image_workflow)
    return read_settings(session, settings)
