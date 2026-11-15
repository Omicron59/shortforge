"""Dependances FastAPI partagees par les routes."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.db import Database
from shortforge.pipeline import HandlerRegistry, PipelineService
from shortforge.runtime import Runtime


def get_session(request: Request) -> Iterator[Session]:
    db: Database = request.app.state.db
    with db.session() as session:
        yield session


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def build_service(request: Request, session: Session) -> PipelineService:
    registry: HandlerRegistry = request.app.state.registry
    return PipelineService(session, request.app.state.settings, registry)


def get_runtime(request: Request) -> Runtime:
    runtime: Runtime = request.app.state.runtime
    return runtime
