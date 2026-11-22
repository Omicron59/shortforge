"""Archiver, restaurer et supprimer un projet : donnees, fichiers et garde-fous."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from shortforge.config import Settings
from shortforge.main import create_app
from tests.conftest import full_registry, make_settings
from tests.fakes import FakeLLM, make_runtime
from tests.test_wizard import BRIEF, Flow

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")  # 1 pixel


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def flow(settings: Settings) -> Iterator[Flow]:
    llm = FakeLLM()
    with TestClient(create_app(settings, full_registry(), make_runtime(settings, llm))) as client:
        yield Flow(client, llm)


def project_with_media(flow: Flow, settings: Settings) -> tuple[str, Path]:
    """Projet avec idees, script, image importee et une piece jointe de travail dans son dossier."""
    pid, state = flow.with_script()
    scene = state["script"]["scenes"][0]["id"]
    res = flow.client.put(f"/api/wizard/scenes/{scene}/image?filename=a.png&rights_confirmed=true", content=PNG)
    assert res.status_code == 200, res.text
    folder = settings.shortforge_data_dir / "projects" / pid
    (folder / "render").mkdir(parents=True, exist_ok=True)
    (folder / "render" / "short_1080x1920.mp4").write_bytes(b"0" * 5000)
    return pid, folder


def rows(settings: Settings, table: str, pid: str) -> int:
    con = sqlite3.connect(settings.database_url.removeprefix("sqlite:///"))
    try:
        column = "project_id" if table != "projects" else "id"
        return int(con.execute(f"SELECT count(*) FROM {table} WHERE {column} = ?", (pid,)).fetchone()[0])
    finally:
        con.close()


def ids(client: TestClient, archived: bool = False) -> list[str]:
    return [p["id"] for p in client.get(f"/api/projects?archived={str(archived).lower()}").json()]


def test_archive_hides_the_project_and_restore_brings_it_back(flow: Flow, settings: Settings) -> None:
    pid, folder = project_with_media(flow, settings)
    other = flow.create(subject="Un autre sujet")["project"]["id"]
    flow.post(f"/projects/{pid}/script/approve")
    for _ in range(7):  # jusqu'a la revue de l'apercu, qui attend une validation
        flow.client.post(f"/api/projects/{pid}/pipeline/advance")
    assert any(v["project_id"] == pid for v in flow.client.get("/api/validations").json())

    archived = flow.client.post(f"/api/projects/{pid}/archive").json()
    assert archived["archived_at"] is not None
    assert pid not in ids(flow.client) and other in ids(flow.client)
    assert ids(flow.client, archived=True) == [pid]
    assert not any(v["project_id"] == pid for v in flow.client.get("/api/validations").json())
    assert flow.state(pid)["script"] is not None and folder.is_dir()  # rien n'est efface

    restored = flow.client.post(f"/api/projects/{pid}/unarchive").json()
    assert restored["archived_at"] is None and pid in ids(flow.client)
    assert ids(flow.client, archived=True) == []


def test_footprint_tells_what_deletion_would_erase(flow: Flow, settings: Settings) -> None:
    pid, _ = project_with_media(flow, settings)
    fp = flow.client.get(f"/api/projects/{pid}/footprint").json()
    assert fp["title"] == BRIEF["subject"] and fp["images"] == 1 and fp["files"] == 2
    assert fp["bytes"] >= 5000 and fp["scheduled_posts"] == 0 and fp["archived"] is False


def test_delete_needs_confirmation_then_erases_data_and_folder(flow: Flow, settings: Settings) -> None:
    pid, folder = project_with_media(flow, settings)
    other, _ = flow.with_script()
    shared = settings.shortforge_data_dir / "music" / "piste.mp3"  # fichier partage : jamais touche
    shared.parent.mkdir(parents=True, exist_ok=True)
    shared.write_bytes(b"musique")

    refused = flow.client.delete(f"/api/projects/{pid}")
    assert refused.status_code == 409 and "Confirme" in refused.json()["detail"]
    assert folder.is_dir() and rows(settings, "projects", pid) == 1

    done = flow.client.delete(f"/api/projects/{pid}?confirm=true").json()
    assert done == {"deleted": True, "title": BRIEF["subject"], "freed_bytes": done["freed_bytes"], "leftover": ""}
    assert done["freed_bytes"] >= 5000
    assert not folder.exists() and shared.read_bytes() == b"musique"
    for table in ("projects", "pipeline_steps", "ideas", "scripts", "scenes", "assets", "briefs"):
        assert rows(settings, table, pid) == 0, table
    assert flow.client.get(f"/api/projects/{pid}").status_code == 404
    assert flow.state(other)["script"] is not None  # l'autre projet est intact
    assert (settings.shortforge_data_dir / "projects").is_dir()


def test_delete_is_refused_while_a_step_runs(flow: Flow, settings: Settings) -> None:
    pid, folder = project_with_media(flow, settings)
    con = sqlite3.connect(settings.database_url.removeprefix("sqlite:///"))
    con.execute("UPDATE pipeline_steps SET status='running' WHERE project_id=? AND name='generate_images'", (pid,))
    con.commit()
    con.close()
    res = flow.client.delete(f"/api/projects/{pid}?confirm=true")
    assert res.status_code == 409 and "en cours" in res.json()["detail"]
    assert folder.is_dir() and rows(settings, "projects", pid) == 1


def test_project_folder_cannot_escape_the_projects_directory(settings: Settings) -> None:
    from shortforge.models import Project
    from shortforge.services.projects import ProjectDeletionError, project_dir

    for bad in ("../reglages", "a/b", ""):
        with pytest.raises(ProjectDeletionError):
            project_dir(settings.shortforge_data_dir, Project(id=bad, title="x"))


def test_costs_and_stats_survive_a_deletion(flow: Flow, settings: Settings) -> None:
    from shortforge.db import Database
    from shortforge.models import Cost

    pid, _ = project_with_media(flow, settings)
    db = Database(settings.database_url)
    with db.session() as session:
        session.add(Cost(amount_usd=0.25, kind="actual", project_id=pid, description="vidéo payée"))
    db.engine.dispose()
    flow.client.delete(f"/api/projects/{pid}?confirm=true")
    con = sqlite3.connect(settings.database_url.removeprefix("sqlite:///"))
    kept: Any = con.execute("SELECT amount_usd, project_id FROM costs").fetchall()
    con.close()
    assert kept == [(0.25, None)]  # la depense reste comptee dans le budget du mois
