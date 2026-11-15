"""Etat du backend."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from shortforge import __version__
from shortforge.config import Settings
from shortforge.deps import get_session, get_settings_dep
from shortforge.schemas import HealthOut

router = APIRouter(tags=["etat"])


@router.get("/api/health", response_model=HealthOut)
def health(session: Session = Depends(get_session), settings: Settings = Depends(get_settings_dep)) -> HealthOut:
    session.execute(text("SELECT 1"))
    return HealthOut(status="ok", version=__version__, database="ok",
                     youtube_publish_enabled=settings.youtube_publish_enabled)
