"""Construit les fournisseurs video a partir du catalogue en base et des cles du `.env`."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.integrations.comfyui import ComfyUIClient, WorkflowLibrary
from shortforge.models import Provider
from shortforge.providers.base import ProviderError, VideoProvider
from shortforge.providers.comfyui_local import ComfyUIWorkflowProvider
from shortforge.providers.google import GeminiOmniFlashProvider, Veo3FastProvider, Veo3Provider
from shortforge.providers.others import KlingProvider, MiniMaxProvider, PikaProvider, RunwayProvider

LOCAL_IDS = ("comfyui_local", "wan22_local", "ltx_video_local", "cogvideox_local")
# Champs de configuration modifiables depuis l'interface (jamais de secret).
CONFIG_KEYS = frozenset({"model", "base_url", "workflow", "api_version"})


def _secret(value: Any) -> str | None:
    return value.get_secret_value() if value is not None else None


class ProviderRegistry:
    def __init__(self, providers: dict[str, VideoProvider], enabled: set[str]) -> None:
        self._providers = providers
        self.enabled = enabled

    def get(self, provider_id: str) -> VideoProvider:
        provider = self._providers.get(provider_id)
        if provider is None:
            raise ProviderError(f"Moteur vidéo inconnu : {provider_id}.")
        return provider

    def all(self) -> list[VideoProvider]:
        return list(self._providers.values())


def build_registry(session: Session, settings: Settings, comfy: ComfyUIClient, library: WorkflowLibrary,
                   transport: httpx.BaseTransport | None = None) -> ProviderRegistry:
    rows = {p.id: p for p in session.scalars(select(Provider))}

    def common(provider_id: str) -> dict[str, Any]:
        row = rows.get(provider_id)
        return {"cost_per_second_usd": row.cost_per_second_usd if row else None,
                "config": dict(row.config or {}) if row else {}}

    external: dict[str, Callable[[], VideoProvider]] = {
        "pika_h3_flex": lambda: PikaProvider(**common("pika_h3_flex")),
        "hailuo_fast": lambda: MiniMaxProvider(api_key=_secret(settings.minimax_api_key), transport=transport,
                                               **common("hailuo_fast")),
        "kling": lambda: KlingProvider(api_key=_secret(settings.kling_access_key),
                                       secret_key=_secret(settings.kling_secret_key), transport=transport,
                                       **common("kling")),
        "runway": lambda: RunwayProvider(api_key=_secret(settings.runway_api_key), transport=transport,
                                         **common("runway")),
        "gemini_omni_12_flash": lambda: GeminiOmniFlashProvider(api_key=_secret(settings.gemini_api_key),
                                                                transport=transport,
                                                                **common("gemini_omni_12_flash")),
        "veo3_fast": lambda: Veo3FastProvider(api_key=_secret(settings.gemini_api_key), transport=transport,
                                              **common("veo3_fast")),
        "veo3": lambda: Veo3Provider(api_key=_secret(settings.gemini_api_key), transport=transport,
                                     **common("veo3")),
    }
    providers: dict[str, VideoProvider] = {}
    for provider_id in LOCAL_IDS:
        name = rows[provider_id].name if provider_id in rows else provider_id
        providers[provider_id] = ComfyUIWorkflowProvider(provider_id, name, comfy, library, **common(provider_id))
    for provider_id, factory in external.items():
        providers[provider_id] = factory()
    enabled = {pid for pid, row in rows.items() if row.enabled}
    return ProviderRegistry(providers, enabled)
