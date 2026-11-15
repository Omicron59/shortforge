from __future__ import annotations

from fastapi.testclient import TestClient


def create(client: TestClient) -> str:
    res = client.post("/api/projects", json={"title": "Le café du lundi", "niche": "humour"})
    assert res.status_code == 201
    body = res.json()
    assert len(body["steps"]) == 15
    assert body["steps"][1]["label"] == "Choix de l'idée"
    return str(body["id"])


def test_health(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["youtube_publish_enabled"] is False


def test_providers_listed_with_local_default(client: TestClient) -> None:
    providers = client.get("/api/providers").json()
    assert providers[0]["id"] == "comfyui_local" and providers[0]["is_default"]
    assert len(providers) == 11


def test_project_lifecycle(client: TestClient) -> None:
    project_id = create(client)
    assert client.post(f"/api/projects/{project_id}/pipeline/advance").json()["status"] == "done"
    gate = client.post(f"/api/projects/{project_id}/pipeline/advance").json()
    assert gate["name"] == "select_idea" and gate["status"] == "needs_validation"

    blocked = client.post(f"/api/projects/{project_id}/pipeline/advance")
    assert blocked.status_code == 409 and "validation" in blocked.json()["detail"]

    ok = client.post(f"/api/projects/{project_id}/steps/select_idea/approve", json={})
    assert ok.json()["status"] == "done"

    detail = client.get(f"/api/projects/{project_id}").json()
    assert detail["current_step"] == "write_script"
    assert [p["id"] for p in client.get("/api/projects").json()] == [project_id]


def test_unknown_project_returns_404(client: TestClient) -> None:
    assert client.get("/api/projects/inconnu").status_code == 404


def test_unknown_step_returns_409(client: TestClient) -> None:
    project_id = create(client)
    assert client.post(f"/api/projects/{project_id}/steps/nimporte/redo").status_code == 409


def test_publish_is_blocked_over_http(client: TestClient) -> None:
    project_id = create(client)
    while True:
        detail = client.get(f"/api/projects/{project_id}").json()
        step = next(s for s in detail["steps"] if s["status"] != "done")
        if step["name"] == "publish" and step["status"] == "needs_validation":
            break
        if step["status"] == "needs_validation":
            client.post(f"/api/projects/{project_id}/steps/{step['name']}/approve", json={})
        else:
            client.post(f"/api/projects/{project_id}/pipeline/advance")
    res = client.post(f"/api/projects/{project_id}/steps/publish/approve", json={"confirm": True})
    assert res.status_code == 403
    assert any("désactivée" in r for r in res.json()["reasons"])


def test_cancel_and_resume_over_http(client: TestClient) -> None:
    project_id = create(client)
    assert client.post(f"/api/projects/{project_id}/pipeline/cancel").json()["status"] == "cancelled"
    resumed = client.post(f"/api/projects/{project_id}/pipeline/resume").json()
    assert resumed["status"] == "draft" and resumed["steps"][0]["status"] == "pending"
