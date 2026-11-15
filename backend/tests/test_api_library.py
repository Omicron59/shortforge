"""Routes de lecture pour l'interface : fichiers, file de production, historique, statistiques."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from shortforge.models import Asset, Cost


def test_history_lists_steps_and_costs(client: TestClient) -> None:
    project_id = client.post("/api/projects", json={"title": "Pigeon"}).json()["id"]
    client.post(f"/api/projects/{project_id}/pipeline/advance")
    client.post(f"/api/projects/{project_id}/pipeline/advance")
    client.post(f"/api/projects/{project_id}/steps/select_idea/approve", json={})
    with client.app.state.db.session() as session:  # type: ignore[attr-defined]
        session.add(Cost(project_id=project_id, amount_usd=0.35, kind="actual", description="scène 1"))
    events = client.get("/api/history").json()
    assert events[0]["type"] == "cost_actual" and events[0]["amount_usd"] == 0.35
    labels = {e["label"] for e in events}
    assert {"Génération des idées", "Choix de l'idée"} <= labels
    assert all(e["project_title"] == "Pigeon" for e in events)


def test_stats_counts_production(client: TestClient) -> None:
    client.post("/api/projects", json={"title": "A"})
    body = client.get("/api/stats").json()
    assert body["projects_total"] == 1 and body["spent_total_usd"] == 0
    assert body["youtube"]["available"] is False


def test_asset_file_is_served_only_inside_data_dir(client: TestClient, tmp_path: Path) -> None:
    project_id = client.post("/api/projects", json={"title": "A"}).json()["id"]
    inside = tmp_path / "projects" / "img.png"
    inside.parent.mkdir(parents=True)
    inside.write_bytes(b"png")
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("non")
    with client.app.state.db.session() as session:  # type: ignore[attr-defined]
        session.add_all([Asset(id="a1", project_id=project_id, kind="image", path=str(inside), mime_type="image/png"),
                         Asset(id="a2", project_id=project_id, kind="image", path=str(outside))])
    assert [a["id"] for a in client.get(f"/api/projects/{project_id}/assets").json()] == ["a1", "a2"]
    assert client.get("/api/assets/a1/file").content == b"png"
    assert client.get("/api/assets/a2/file").status_code == 404
    assert client.get("/api/assets/zz/file").status_code == 404
    assert client.get("/api/jobs").json() == []


def test_release_endpoints_without_render(client: TestClient) -> None:
    project_id = client.post("/api/projects", json={"title": "A"}).json()["id"]
    assert client.get(f"/api/projects/{project_id}/render").json() is None
    assert client.get(f"/api/projects/{project_id}/youtube-draft").json() is None
    check = client.get(f"/api/projects/{project_id}/final-check").json()
    assert check["ready"] is False
    first = check["checks"][0]
    assert first["id"] == "publish_enabled" and first["ok"] is False and "false" in first["detail"]
    missing = client.put(f"/api/projects/{project_id}/youtube-draft", json={"title": "x"})
    assert missing.status_code == 502 and "Brouillon YouTube" in missing.json()["detail"]
    style = client.put(f"/api/projects/{project_id}/subtitles",
                       json={"position": "top", "style": {"color": "#FF0000", "inconnu": 1}}).json()
    assert style["position"] == "top" and style["style"]["color"] == "#FF0000" and "inconnu" not in style["style"]
    status = client.get("/api/youtube/status").json()
    assert status["publish_enabled"] is False and status["channel"] is None
    connect = client.post("/api/youtube/connect")
    assert connect.status_code == 502 and "YOUTUBE_CLIENT_SECRETS_FILE" in connect.json()["detail"]
    page = client.get("/api/youtube/oauth/callback?error=access_denied")
    assert "Connexion annulée" in page.text


def test_comfyui_check_and_settings(client: TestClient) -> None:
    body = client.get("/api/comfyui/check").json()
    assert set(body) >= {"running", "url", "checkpoints", "message", "ready"}
    assert body["running"] is False and "Comfy Desktop" in body["message"]
    saved = client.put("/api/comfyui/settings", json={"url": "http://127.0.0.1:8000", "checkpoint": "mon.safetensors"})
    assert saved.json()["url"] == "http://127.0.0.1:8000" and saved.json()["chosen_checkpoint"] == "mon.safetensors"
    assert client.put("/api/comfyui/settings", json={"url": "pas une adresse"}).status_code == 422
