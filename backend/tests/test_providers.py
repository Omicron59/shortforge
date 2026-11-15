from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.integrations.comfyui import WorkflowLibrary
from shortforge.providers.base import (
    JobState,
    Operation,
    ProviderError,
    ProviderNotConfiguredError,
    UnsupportedOperationError,
    VideoRequest,
)
from shortforge.providers.comfyui_local import ComfyUIWorkflowProvider
from shortforge.providers.google import GeminiOmniFlashProvider, Veo3Provider
from shortforge.providers.others import KlingProvider, MiniMaxProvider, PikaProvider, RunwayProvider
from shortforge.providers.registry import build_registry
from tests.fakes import ASSETS_WORKFLOWS, FakeComfyServer, FakeGoogleApi, add_video_workflow


def gemini(handler: Any = None, cost: float | None = 0.07) -> GeminiOmniFlashProvider:
    transport = httpx.MockTransport(handler) if handler else None
    return GeminiOmniFlashProvider(api_key="cle-test", transport=transport, cost_per_second_usd=cost)


def image(tmp_path: Path) -> Path:
    path = tmp_path / "depart.png"
    path.write_bytes(b"\x89PNG fake")
    return path


def test_all_providers_share_the_interface(session: Session, settings: Settings, tmp_path: Path) -> None:
    lib = WorkflowLibrary([ASSETS_WORKFLOWS], tmp_path / "wf")
    registry = build_registry(session, settings, FakeComfyServer().client(), lib)
    methods = ("generate_from_text", "generate_from_image", "generate_from_first_and_last_frame", "edit_video",
               "estimate_cost", "validate_parameters", "get_status", "download_result")
    assert len(registry.all()) == 11
    for provider in registry.all():
        assert all(callable(getattr(provider, m)) for m in methods), provider.id


def test_gemini_cost_estimate() -> None:
    assert gemini().estimate_cost(VideoRequest(prompt="x", duration_s=5)) == 0.35
    assert gemini(cost=None).estimate_cost(VideoRequest(prompt="x")) is None


def test_veo_bills_the_next_allowed_duration() -> None:
    veo = Veo3Provider(api_key="k", cost_per_second_usd=0.5)
    assert veo.estimate_cost(VideoRequest(prompt="x", duration_s=5)) == 3.0  # facture 6 s
    assert veo.validate_parameters(VideoRequest(prompt="x", duration_s=5)) == []
    assert "durées" in veo.validate_parameters(VideoRequest(prompt="x", duration_s=12))[0]


def test_validation_messages(tmp_path: Path) -> None:
    provider = gemini()
    errors = provider.validate_parameters(VideoRequest(prompt=" ", duration_s=40, resolution="4k"), Operation.IMAGE)
    assert "Le prompt est vide." in errors and "Image de départ manquante." in errors
    assert any("3 à 15 secondes" in e for e in errors) and any("4k" in e for e in errors)
    with pytest.raises(UnsupportedOperationError, match="modification"):
        provider.edit_video(VideoRequest(prompt="x", video_path=image(tmp_path)))


def test_missing_key_blocks_submission() -> None:
    provider = GeminiOmniFlashProvider(api_key=None)
    with pytest.raises(ProviderNotConfiguredError, match=r"\.env"):
        provider.generate_from_text(VideoRequest(prompt="x"))


def test_gemini_full_flow(tmp_path: Path) -> None:
    api = FakeGoogleApi()
    provider = gemini(api.handler)
    job = provider.generate_from_image(VideoRequest(prompt="un chat", duration_s=5, negative_prompt="flou",
                                                    image_path=image(tmp_path)))
    body = api.submitted[0]
    assert body["parameters"] == {"aspectRatio": "9:16", "resolution": "720p", "durationSeconds": 5,
                                  "negativePrompt": "flou"}
    assert body["instances"][0]["image"]["mimeType"] == "image/png"
    status = provider.wait(job, poll_interval_s=0, sleep=lambda _: None)
    assert status.state is JobState.SUCCEEDED
    assert provider.download_result(job, tmp_path / "out").read_bytes() == b"mp4-video"


def test_gemini_safety_refusal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"done": True, "response": {"generateVideoResponse": {
            "raiMediaFilteredReasons": ["personne réelle détectée"]}}})

    status = gemini(handler).get_status("models/x/operations/1")
    assert status.state is JobState.FAILED and "personne réelle" in (status.error or "")


def test_bad_key_message() -> None:
    provider = gemini(lambda _: httpx.Response(403, json={}))
    with pytest.raises(ProviderError, match="refuse la clé API"):
        provider.generate_from_text(VideoRequest(prompt="x"))


def test_minimax_flow(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/v1/"):
            assert request.headers["authorization"] == "Bearer mm"
        if request.url.path == "/v1/video_generation":
            body = json.loads(request.content)
            assert body["duration"] == 6 and body["first_frame_image"].startswith("data:image/png;base64,")
            return httpx.Response(200, json={"task_id": "t1", "base_resp": {"status_code": 0}})
        if request.url.path == "/v1/query/video_generation":
            return httpx.Response(200, json={"status": "Success", "file_id": "f1", "base_resp": {"status_code": 0}})
        if request.url.path == "/v1/files/retrieve":
            return httpx.Response(200, json={"file": {"download_url": "https://api.minimax.io/dl/f1.mp4"}})
        return httpx.Response(200, content=b"minimax-mp4")

    provider = MiniMaxProvider(api_key="mm", transport=httpx.MockTransport(handler))
    job = provider.generate_from_image(VideoRequest(prompt="x", duration_s=5, image_path=image(tmp_path)))
    assert provider.get_status(job).state is JobState.SUCCEEDED
    assert provider.download_result(job, tmp_path).read_bytes() == b"minimax-mp4"


def test_minimax_api_error() -> None:
    reply = httpx.Response(200, json={"base_resp": {"status_code": 1008, "status_msg": "solde insuffisant"}})
    provider = MiniMaxProvider(api_key="mm", transport=httpx.MockTransport(lambda _: reply))
    with pytest.raises(ProviderError, match="solde insuffisant"):
        provider.generate_from_text(VideoRequest(prompt="x", duration_s=6))


def test_kling_jwt_is_signed_with_secret_key() -> None:
    provider = KlingProvider(api_key="acces", secret_key="secret")
    token = provider.token(now=1_000_000)
    head, payload, signature = token.split(".")
    expected = hmac.new(b"secret", f"{head}.{payload}".encode(), hashlib.sha256).digest()
    assert base64.urlsafe_b64decode(signature + "==") == expected
    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    assert claims == {"iss": "acces", "exp": 1_001_800, "nbf": 999_995}
    assert not KlingProvider(api_key="acces").is_configured()


def test_kling_flow(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            assert request.url.path == "/v1/videos/text2video"
            assert json.loads(request.content)["duration"] == "5"
            return httpx.Response(200, json={"code": 0, "data": {"task_id": "k1"}})
        if request.url.path == "/v1/videos/text2video/k1":
            return httpx.Response(200, json={"code": 0, "data": {"task_status": "succeed", "task_result": {
                "videos": [{"url": "https://cdn.kling.test/v.mp4"}]}}})
        return httpx.Response(200, content=b"kling-mp4")

    provider = KlingProvider(api_key="a", secret_key="s", transport=httpx.MockTransport(handler))
    job = provider.generate_from_text(VideoRequest(prompt="x", duration_s=5))
    assert job == "text2video:k1"
    assert provider.download_result(job, tmp_path).read_bytes() == b"kling-mp4"


def test_runway_needs_an_image_and_runs(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/v1/"):
            assert request.headers["x-runway-version"] == "2024-11-06"
        if request.url.path == "/v1/image_to_video":
            return httpx.Response(200, json={"id": "r1"})
        if request.url.path == "/v1/tasks/r1":
            return httpx.Response(200, json={"status": "SUCCEEDED", "output": ["https://runway.test/r1.mp4"]})
        return httpx.Response(200, content=b"runway-mp4")

    provider = RunwayProvider(api_key="rw", transport=httpx.MockTransport(handler))
    with pytest.raises(UnsupportedOperationError):
        provider.generate_from_text(VideoRequest(prompt="x", duration_s=5))
    job = provider.generate_from_image(VideoRequest(prompt="x", duration_s=5, image_path=image(tmp_path)))
    assert provider.download_result(job, tmp_path).read_bytes() == b"runway-mp4"


def test_pika_is_listed_but_unavailable() -> None:
    provider = PikaProvider()
    assert not provider.is_configured()
    with pytest.raises(ProviderNotConfiguredError, match="pas encore disponible"):
        provider.generate_from_text(VideoRequest(prompt="x"))


def test_local_comfyui_provider(tmp_path: Path) -> None:
    server = FakeComfyServer(output_name="clip.mp4")
    lib = WorkflowLibrary([ASSETS_WORKFLOWS], tmp_path / "wf")
    provider = ComfyUIWorkflowProvider("wan22_local", "Wan 2.2 local", server.client(), lib)
    assert not provider.is_configured()
    assert "wan22_local" in provider.validate_parameters(VideoRequest(prompt="x"))[0]
    add_video_workflow(lib, "wan22_local")
    assert provider.estimate_cost(VideoRequest(prompt="x", duration_s=10)) == 0.0
    job = provider.generate_from_image(VideoRequest(prompt="un chat", seed=7, image_path=image(tmp_path)))
    assert server.queued[0]["6"]["inputs"]["text"] == "un chat" and server.queued[0]["3"]["inputs"]["seed"] == 7
    assert server.queued[0]["5"]["inputs"]["width"] == 720 and server.uploads
    assert provider.get_status(job).state is JobState.SUCCEEDED
    assert provider.download_result(job, tmp_path).name == "clip.mp4"
    errors = provider.validate_parameters(VideoRequest(prompt="x", image_path=image(tmp_path),
                                                       last_frame_path=image(tmp_path)), Operation.FIRST_LAST)
    assert "image de fin" in errors[0]
