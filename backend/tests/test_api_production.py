"""Routes de l'API branchees sur de faux services."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from shortforge.config import Settings
from shortforge.main import create_app
from tests.fakes import ASSETS_WORKFLOWS, FakeLLM, ideas_response, make_runtime, script_response


@pytest.fixture
def api(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(_env_file=None, shortforge_data_dir=tmp_path)  # type: ignore[call-arg]
    llm = FakeLLM(ideas_response("Le pigeon poli", "La machine à café rebelle"), script_response(),
                  script_response(("simple",)))
    with TestClient(create_app(settings, runtime=make_runtime(settings, llm))) as client:
        yield client


def new_project(api: TestClient) -> str:
    return str(api.post("/api/projects", json={"title": "Pigeon", "niche": "animaux"}).json()["id"])


def to_script(api: TestClient, project_id: str) -> None:
    assert api.post(f"/api/projects/{project_id}/pipeline/advance").json()["status"] == "done"
    api.post(f"/api/projects/{project_id}/pipeline/advance")
    ideas = api.get(f"/api/projects/{project_id}/ideas").json()
    assert len(ideas) == 2 and {"hook", "reuse_risk", "potential_score"} <= set(ideas[0])
    api.post(f"/api/projects/{project_id}/ideas/{ideas[0]['id']}/select")
    assert api.post(f"/api/projects/{project_id}/steps/select_idea/approve", json={}).json()["status"] == "done"
    assert api.post(f"/api/projects/{project_id}/pipeline/advance").json()["status"] == "done"


def test_status_reports_local_services(api: TestClient) -> None:
    body = api.get("/api/status").json()
    assert body["comfyui"]["running"] is True and body["ollama"]["running"] is True
    assert body["gpu"] == {"available": True, "name": "NVIDIA RTX 4080", "vram_total_mb": 16384,
                           "vram_free_mb": 12288}
    assert set(body["ffmpeg"]) == {"available", "path"}


def test_providers_show_configuration_state(api: TestClient) -> None:
    providers = {p["id"]: p for p in api.get("/api/providers").json()}
    assert providers["gemini_omni_12_flash"]["configured"] is False
    assert ".env" in providers["gemini_omni_12_flash"]["configuration_hint"]
    assert "generate_from_image" in providers["gemini_omni_12_flash"]["operations"]
    assert providers["veo3"]["tier"] == "premium" and not providers["veo3"]["is_default"]


def test_provider_settings_refuse_secrets(api: TestClient) -> None:
    res = api.patch("/api/providers/kling", json={"config": {"api_key": "secret"}})
    assert res.status_code == 409 and ".env" in res.json()["detail"]
    ok = api.patch("/api/providers/kling", json={"cost_per_second_usd": 0.1, "config": {"model": "kling-v2-1"}})
    assert ok.json()["cost_per_second_usd"] == 0.1 and ok.json()["config"] == {"model": "kling-v2-1"}
    assert api.patch("/api/providers/comfyui_local", json={"enabled": False}).status_code == 409
    reset = api.patch("/api/providers/kling", json={"config": {"model": "  "}})
    assert reset.json()["config"] == {}


def test_script_editing_flow(api: TestClient) -> None:
    project_id = new_project(api)
    to_script(api, project_id)
    detail = api.get(f"/api/projects/{project_id}/script").json()
    assert detail["script"]["version"] == 1 and len(detail["scenes"]) == 2

    edited = api.put(f"/api/projects/{project_id}/script", json={"hook": "Ce pigeon dit bonjour à tout le monde."})
    assert edited.json()["script"]["hook"].startswith("Ce pigeon")
    shorter = api.post(f"/api/projects/{project_id}/script/shorten", json={"target_duration_s": 10}).json()
    assert shorter["script"]["version"] == 2 and len(shorter["scenes"]) == 1

    api.post(f"/api/projects/{project_id}/pipeline/advance")
    api.post(f"/api/projects/{project_id}/steps/approve_script/approve", json={})
    locked = api.put(f"/api/projects/{project_id}/script", json={"hook": "trop tard"})
    assert locked.status_code == 409 and "validé" in locked.json()["detail"]


def test_scene_engine_choice_and_cost_estimate(api: TestClient) -> None:
    project_id = new_project(api)
    to_script(api, project_id)
    scene = api.get(f"/api/projects/{project_id}/scenes").json()[0]
    patched = api.patch(f"/api/scenes/{scene['id']}", json={"provider_id": "gemini_omni_12_flash",
                                                            "duration_s": 5})
    assert patched.json()["provider_locked"] is True
    assert api.patch(f"/api/scenes/{scene['id']}", json={"provider_id": "inconnu"}).status_code == 409
    estimate = api.get(f"/api/projects/{project_id}/cost-estimate").json()
    assert estimate["estimated_total_usd"] == 0.35
    assert estimate["pending_confirmations"][0]["estimated_cost_usd"] == 0.35
    engine = api.put(f"/api/projects/{project_id}/engine", json={"video_mode": "premium", "engine_scope": "short",
                                                                 "default_provider": "ltx_video_local"})
    assert engine.json()["engine_scope"] == "short" and engine.json()["video_mode"] == "premium"


def test_budget_endpoints(api: TestClient) -> None:
    summary = api.get("/api/budget").json()
    assert summary["budget_max_per_month"] == 30 and summary["spent_month"] == 0
    updated = api.put("/api/budget/limits", json={"budget_max_per_day": 3}).json()
    assert updated["budget_max_per_day"] == 3
    assert api.put("/api/budget/limits", json={"budget_max_per_day": -1}).status_code == 422
    assert api.get("/api/budget/history").json() == []


def test_settings_endpoints(api: TestClient) -> None:
    body = api.put("/api/settings", json={"engine_rules": {"simple": "wan22_local"},
                                          "manual_trends": ["  Les pigeons  ", ""]}).json()
    assert body["engine_rules"] == {"simple": "wan22_local"} and body["manual_trends"] == ["Les pigeons"]
    assert api.put("/api/settings", json={"engine_rules": {"enorme": "veo3"}}).status_code == 409


def test_workflow_endpoints(api: TestClient) -> None:
    import json

    workflows = api.get("/api/comfyui/workflows").json()
    assert any(w["id"] == "image_default" for w in workflows)
    workflow = json.loads((ASSETS_WORKFLOWS / "image_default.json").read_text(encoding="utf-8"))
    created = api.post("/api/comfyui/workflows", json={"id": "wan22_local", "kind": "video", "workflow": workflow})
    assert created.status_code == 201 and created.json()["user"] is True
    bad = api.post("/api/comfyui/workflows", json={"id": "x", "workflow": {"nodes": []}})
    assert bad.status_code == 502 and "Export (API)" in bad.json()["detail"]
    providers = {p["id"]: p for p in api.get("/api/providers").json()}
    assert providers["wan22_local"]["configured"] is True


def test_background_advance(api: TestClient) -> None:
    project_id = new_project(api)
    res = api.post(f"/api/projects/{project_id}/pipeline/advance?background=true")
    assert res.status_code == 202
    for _ in range(50):
        if api.get(f"/api/projects/{project_id}").json()["steps"][0]["status"] == "done":
            break
        time.sleep(0.05)
    assert api.get(f"/api/projects/{project_id}").json()["steps"][0]["status"] == "done"


def test_websocket_sends_pipeline_state(api: TestClient) -> None:
    project_id = new_project(api)
    with api.websocket_connect(f"/api/projects/{project_id}/events") as ws:
        first = ws.receive_json()
        assert first["id"] == project_id and len(first["steps"]) == 15
