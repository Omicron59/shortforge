from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.db import Database
from shortforge.main import create_app
from shortforge.pipeline import PIPELINE, HandlerRegistry, PipelineService, StepContext
from shortforge.services.provider_catalog import seed_providers


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    return Settings(_env_file=None, shortforge_data_dir=tmp_path,  # type: ignore[call-arg]
                    **overrides)


def ok_handler(ctx: StepContext) -> dict[str, Any]:
    return {"step": ctx.step.value}


def full_registry() -> HandlerRegistry:
    """Registre ou chaque etape automatique reussit (pour parcourir tout le pipeline)."""
    registry = HandlerRegistry()
    for definition in PIPELINE:
        if not definition.human_gate:
            registry.register(definition.name, ok_handler)
    return registry


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def database(settings: Settings) -> Iterator[Database]:
    db = Database(settings.database_url)
    db.create_all()
    with db.session() as session:
        seed_providers(session)
    yield db
    db.engine.dispose()


@pytest.fixture
def session(database: Database) -> Iterator[Session]:
    with database.session() as s:
        yield s


@pytest.fixture
def registry() -> HandlerRegistry:
    return full_registry()


@pytest.fixture
def service(session: Session, settings: Settings, registry: HandlerRegistry) -> PipelineService:
    return PipelineService(session, settings, registry)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings, full_registry())) as c:
        yield c


FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


@pytest.fixture(scope="session")
def media(tmp_path_factory: pytest.TempPathFactory) -> dict[str, bytes]:
    if not FFMPEG:
        pytest.skip("FFmpeg absent")
    folder = tmp_path_factory.mktemp("media")
    png, mp4 = folder / "img.png", folder / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=768x1344", "-frames:v", "1",
                    str(png)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=720x1280:rate=24", "-t", "2",
                    "-pix_fmt", "yuv420p", str(mp4)], check=True)  # plus court que la scene : prolonge
    return {"png": png.read_bytes(), "mp4": mp4.read_bytes()}


