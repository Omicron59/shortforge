"""Assemblage des dependances (modele de texte, ComfyUI, tendances, fournisseurs video).

Tout passe par cet objet, ce qui permet aux tests de remplacer chaque service par un faux.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy.orm import Session

from shortforge.ai.router import TaskRouter
from shortforge.config import Settings
from shortforge.integrations.comfyui import DEFAULT_COMFYUI_URLS, ComfyUIClient, WorkflowLibrary
from shortforge.integrations.ollama import LLMClient
from shortforge.integrations.trends import GoogleTrendsSource, ManualTrendSource, TrendSource, YouTubeTrendSource
from shortforge.providers.registry import ProviderRegistry, build_registry
from shortforge.services.app_settings import get_value
from shortforge.vault import Vault, default_keystore

if TYPE_CHECKING:
    from shortforge.services.youtube import YouTubeClient


@dataclass(slots=True)
class Runtime:
    settings: Settings
    llm: LLMClient
    comfy: ComfyUIClient
    library: WorkflowLibrary
    trend_sources: Callable[[Session], list[TrendSource]]
    providers: Callable[[Session], ProviderRegistry]
    sleep: Callable[[float], None] = field(default=time.sleep)
    youtube_transport: httpx.BaseTransport | None = None  # remplace par un faux dans les tests
    http_transport: httpx.BaseTransport | None = None  # ElevenLabs, Postiz, API YouTube publique (tests)
    transcriber: Any = None  # faster-whisper par defaut ; un faux dans les tests
    tts_override: Any = None  # moteur de voix impose (tests)
    vault: Vault = field(default_factory=lambda: Vault(None))  # coffre a secrets (indisponible par defaut)
    _youtube: Any = None

    def llm_for(self, task: str) -> LLMClient:
        """Modele de texte regle pour une tache (idees, script, analyse)."""
        for_task = getattr(self.llm, "for_task", None)
        client: LLMClient = for_task(task) if for_task else self.llm
        return client

    def postiz(self) -> Any:
        from shortforge.integrations.postiz import PostizClient

        key = self.settings.postiz_api_key.get_secret_value() if self.settings.postiz_api_key else None
        return PostizClient(self.settings.postiz_url, key, transport=self.http_transport)

    def youtube_data(self) -> Any:
        from shortforge.integrations.youtube_data import YouTubeData

        key = self.settings.youtube_api_key.get_secret_value() if self.settings.youtube_api_key else None
        return YouTubeData(key, transport=self.http_transport)

    def get_transcriber(self) -> Any:
        if self.transcriber is None:
            from shortforge.integrations.whisper import FasterWhisper

            self.transcriber = FasterWhisper(self.settings.whisper_model)
        return self.transcriber

    @property
    def youtube(self) -> YouTubeClient:
        """Client YouTube unique (il garde le jeton de securite de la connexion en cours)."""
        if self._youtube is None:
            from shortforge.services.youtube import YouTubeClient

            self._youtube = YouTubeClient(self.settings, transport=self.youtube_transport, vault=self.vault)
        client: YouTubeClient = self._youtube
        return client

    @property
    def data_dir(self) -> Path:
        return self.settings.shortforge_data_dir

    def project_dir(self, project_id: str) -> Path:
        return self.data_dir / "projects" / project_id


def default_trend_sources(settings: Settings) -> Callable[[Session], list[TrendSource]]:
    def build(session: Session) -> list[TrendSource]:
        sources: list[TrendSource] = [ManualTrendSource(list(get_value(session, "manual_trends", []) or []))]
        sources.append(GoogleTrendsSource(settings.trends_region))
        if settings.youtube_api_key is not None:
            sources.append(YouTubeTrendSource(settings.youtube_api_key.get_secret_value(), settings.trends_region))
        return sources

    return build


def build_runtime(settings: Settings) -> Runtime:
    comfy = ComfyUIClient(settings.comfyui_url, timeout_s=settings.comfyui_timeout_s,
                          candidates=list(DEFAULT_COMFYUI_URLS))
    library = WorkflowLibrary(settings.workflow_dirs[:1] + settings.workflow_dirs[2:],
                              settings.shortforge_data_dir / "workflows")
    vault = Vault(default_keystore())
    llm = TaskRouter(settings, vault)
    return Runtime(settings=settings, llm=llm, comfy=comfy, library=library, vault=vault,
                   trend_sources=default_trend_sources(settings),
                   providers=lambda session: build_registry(session, settings, comfy, library))
