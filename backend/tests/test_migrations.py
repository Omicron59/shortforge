"""Migrations : reprise d'une base 0.5.3, sauvegarde, et meme schema qu'une installation neuve."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from shortforge.db import Database
from shortforge.main import create_app
from shortforge.migrations import MigrationError, backup_database, migrate
from tests.conftest import full_registry, make_settings

SCHEMA_053 = Path(__file__).parent / "fixtures" / "schema_0_5_3.sql"
NEW_TABLES = {"secrets", "ai_providers", "task_models", "ai_calls", "briefs"}


def old_database(path: Path) -> None:
    """Base telle que la version 0.5.3 l'a creee, avec des donnees de l'utilisateur."""
    con = sqlite3.connect(path)
    con.executescript(SCHEMA_053.read_text(encoding="utf-8"))
    con.execute("INSERT INTO projects (id, title, niche, language, status, video_mode, default_provider, "
                "engine_scope, source, clip, created_at, updated_at) VALUES ('p1', 'Mon premier Short', 'cuisine', "
                "'fr', 'draft', 'economique', 'comfyui_local', 'scene', 'generated', '{}', '2026-11-01', '2026-11-01')")
    con.execute("INSERT INTO settings (key, value, updated_at) VALUES ('comfyui_url', '\"http://127.0.0.1:8188\"', "
                "'2026-11-01')")
    con.commit()
    con.close()


def schema(db: Database) -> dict[str, list[tuple[str, str, bool]]]:
    inspector = inspect(db.engine)
    return {t: sorted((c["name"], str(c["type"]), bool(c["nullable"])) for c in inspector.get_columns(t))
            for t in inspector.get_table_names() if t != "alembic_version"}


def test_old_database_is_backed_up_then_upgraded_without_losing_data(tmp_path: Path) -> None:
    path = tmp_path / "shortforge.sqlite3"
    old_database(path)
    db = Database(f"sqlite:///{path.as_posix()}")
    report = migrate(db, tmp_path / "sauvegardes")

    assert report.previous is None and report.current == "0004"
    assert report.backup is not None and report.backup.is_file()
    backup = sqlite3.connect(report.backup)  # la sauvegarde est la base d'avant : donnees presentes, pas les ajouts
    assert backup.execute("SELECT title FROM projects").fetchall() == [("Mon premier Short",)]
    assert not NEW_TABLES & {r[0] for r in backup.execute("SELECT name FROM sqlite_master")}
    backup.close()

    con = sqlite3.connect(path)
    assert con.execute("SELECT title, niche FROM projects").fetchall() == [("Mon premier Short", "cuisine")]
    assert con.execute("SELECT value FROM settings WHERE key='comfyui_url'").fetchone() == ('"http://127.0.0.1:8188"',)
    assert {r[0] for r in con.execute("SELECT name FROM sqlite_master")} >= NEW_TABLES
    con.close()

    again = migrate(db, tmp_path / "sauvegardes")  # deja a jour : ni changement ni nouvelle sauvegarde
    assert again.backup is None and len(list((tmp_path / "sauvegardes").iterdir())) == 1
    db.engine.dispose()


def test_upgraded_database_has_the_same_schema_as_a_new_one(tmp_path: Path) -> None:
    old = tmp_path / "ancienne.sqlite3"
    old_database(old)
    upgraded = Database(f"sqlite:///{old.as_posix()}")
    fresh = Database(f"sqlite:///{(tmp_path / 'neuve.sqlite3').as_posix()}")
    migrate(upgraded, tmp_path / "s")
    report = migrate(fresh, tmp_path / "s")
    assert report.backup is None and report.current == "0004"
    assert schema(upgraded) == schema(fresh)
    upgraded.engine.dispose()
    fresh.engine.dispose()


def test_failed_backup_cancels_the_upgrade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "shortforge.sqlite3"
    old_database(path)
    db = Database(f"sqlite:///{path.as_posix()}")

    def broken(*_: object) -> None:
        raise MigrationError("sauvegarde impossible")

    monkeypatch.setattr("shortforge.migrations.backup_database", broken)
    with pytest.raises(MigrationError):
        migrate(db, tmp_path / "sauvegardes")
    assert not NEW_TABLES & set(inspect(db.engine).get_table_names())
    db.engine.dispose()


def test_backup_is_a_readable_copy(tmp_path: Path) -> None:
    path = tmp_path / "shortforge.sqlite3"
    old_database(path)
    db = Database(f"sqlite:///{path.as_posix()}")
    copy = backup_database(db, tmp_path / "s", "0001")
    assert copy is not None and sqlite3.connect(copy).execute("SELECT count(*) FROM projects").fetchone() == (1,)
    db.engine.dispose()


def test_application_starts_on_an_old_database_and_keeps_projects(tmp_path: Path) -> None:
    old_database(tmp_path / "shortforge.sqlite3")
    with TestClient(create_app(make_settings(tmp_path), full_registry())) as client:
        titles = [p["title"] for p in client.get("/api/projects").json()]
        assert titles == ["Mon premier Short"]
        assert client.get("/api/ai/tasks").status_code == 200
    assert list((tmp_path / "sauvegardes").glob("*.sqlite3"))
