from __future__ import annotations

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.db import Database
from shortforge.models import PipelineStep, Project, Provider
from shortforge.services.provider_catalog import CATALOG, seed_providers

EXPECTED_TABLES = {
    "projects", "ideas", "scripts", "scenes", "assets", "voice_takes", "subtitles", "renders", "providers",
    "provider_jobs", "costs", "settings", "youtube_channels", "publish_jobs", "analytics", "pipeline_steps",
}


def test_all_tables_are_created(database: Database) -> None:
    assert set(inspect(database.engine).get_table_names()) >= EXPECTED_TABLES


def test_sqlite_file_is_created_in_data_dir(settings: Settings, database: Database) -> None:
    assert (settings.shortforge_data_dir / "shortforge.sqlite3").exists()


def test_foreign_keys_are_enforced(database: Database) -> None:
    with database.engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_providers_are_seeded_once(session: Session) -> None:
    assert seed_providers(session) == 0
    providers = {p.id: p for p in session.scalars(select(Provider))}
    assert len(providers) == len(CATALOG)
    defaults = [p.id for p in providers.values() if p.is_default]
    assert defaults == ["comfyui_local"]
    assert providers["veo3"].tier == "premium" and not providers["veo3"].is_default
    assert providers["gemini_omni_12_flash"].cost_per_second_usd == 0.07


def test_seed_keeps_user_changes(session: Session) -> None:
    session.get(Provider, "kling").cost_per_second_usd = 0.12  # type: ignore[union-attr]
    seed_providers(session)
    assert session.get(Provider, "kling").cost_per_second_usd == 0.12  # type: ignore[union-attr]


def test_deleting_project_deletes_its_steps(session: Session) -> None:
    project = Project(title="Test")
    project.steps = [PipelineStep(name="generate_ideas", position=0)]
    session.add(project)
    session.flush()
    session.delete(project)
    session.flush()
    assert session.scalars(select(PipelineStep)).all() == []
