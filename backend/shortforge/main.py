"""Application FastAPI de ShortForge."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi import status as http
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shortforge import __version__
from shortforge.config import Settings, get_settings
from shortforge.db import Database
from shortforge.integrations.comfyui import ComfyUIError
from shortforge.integrations.ollama import LLMError
from shortforge.pipeline import HandlerRegistry, PipelineError, PipelineService
from shortforge.pipeline.default_handlers import build_handlers
from shortforge.pipeline.engine import ProjectNotFoundError
from shortforge.pipeline.runner import PipelineRunner
from shortforge.providers.base import ProviderError
from shortforge.routers import (
    budget,
    comfyui,
    content,
    health,
    library,
    production,
    projects,
    providers,
    release,
    status,
    studio,
)
from shortforge.routers import settings as settings_router
from shortforge.runtime import Runtime, build_runtime
from shortforge.services.production import ProductionError
from shortforge.services.provider_catalog import seed_providers
from shortforge.services.publish_guard import PublishBlockedError

logger = logging.getLogger("shortforge")

# Origines de la fenetre Tauri (Windows / macOS-Linux) et du serveur Vite en developpement.
ALLOWED_ORIGINS = ["tauri://localhost", "http://tauri.localhost", "https://tauri.localhost",
                   "http://localhost:1420", "http://127.0.0.1:1420"]


def create_app(settings: Settings | None = None, registry: HandlerRegistry | None = None,
               runtime: Runtime | None = None) -> FastAPI:
    """Fabrique l'application. `settings`, `registry` et `runtime` sont injectables pour les tests."""
    settings = settings or get_settings()
    runtime = runtime or build_runtime(settings)
    registry = registry or build_handlers(runtime)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(settings.database_url)
        db.create_all()
        with db.session() as session:
            seed_providers(session)
            recovered = PipelineService(session, settings, registry).recover_interrupted()
        if recovered:
            logger.warning("%s étape(s) interrompue(s) remise(s) en attente.", recovered)
        app.state.db = db
        app.state.runner = PipelineRunner(db, settings, registry)
        yield
        app.state.runner.shutdown()
        db.engine.dispose()

    app = FastAPI(title="ShortForge", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.registry = registry
    app.state.runtime = runtime
    app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(PublishBlockedError)
    async def _publish_blocked(_: Request, exc: PublishBlockedError) -> JSONResponse:
        return JSONResponse(status_code=http.HTTP_403_FORBIDDEN,
                            content={"detail": str(exc), "reasons": exc.reasons})

    @app.exception_handler(PipelineError)
    async def _pipeline_error(_: Request, exc: PipelineError) -> JSONResponse:
        code = http.HTTP_404_NOT_FOUND if isinstance(exc, ProjectNotFoundError) else http.HTTP_409_CONFLICT
        return JSONResponse(status_code=code, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def _value_error(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=http.HTTP_400_BAD_REQUEST, content={"detail": str(exc)})

    @app.exception_handler(LLMError)
    @app.exception_handler(ComfyUIError)
    @app.exception_handler(ProviderError)
    @app.exception_handler(ProductionError)
    async def _service_error(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=http.HTTP_502_BAD_GATEWAY, content={"detail": str(exc)})

    for module in (health, status, projects, content, production, providers, budget, comfyui, settings_router,
                   library, release, studio):
        app.include_router(module.router)
    return app
