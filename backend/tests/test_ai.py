"""Couche IA : adaptateurs (serveurs simules), routage par tache, repli, cles et jeton d'API.

Tous les fournisseurs sont ici SIMULES (httpx.MockTransport) : ces tests ne prouvent pas qu'une vraie
cle ou une vraie generation fonctionne.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from shortforge.ai.base import (
    AiTimeoutError,
    GenerationRequest,
    InvalidKeyError,
    ModelUnavailableError,
    NotConfiguredError,
    PaidConfirmationError,
    QuotaError,
    UnreachableError,
)
from shortforge.ai.ollama import OllamaCloudProvider, OllamaLocalProvider
from shortforge.ai.openrouter import OpenRouterProvider
from shortforge.ai.router import TaskRouter
from shortforge.main import create_app
from shortforge.runtime import build_runtime
from shortforge.vault import MemoryKeyStore, Vault
from tests.conftest import full_registry, make_settings

KEY = "sk-or-v1-0123456789abcdefWXYZ"
REQUEST = GenerationRequest(task="ideas", model="m", system="s", prompt="p", temperature=0.5)


class FakeCloud:
    """Simule Ollama (local et cloud) et OpenRouter ; garde les requetes recues."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.ollama_up = True
        self.ollama_status = 200
        self.openrouter_status = 200
        self.valid_key = KEY
        self.timeout = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host, path = request.url.host, request.url.path
        if self.timeout:
            raise httpx.ReadTimeout("trop long", request=request)
        if host == "openrouter.ai":
            return self._openrouter(request, path)
        if host == "127.0.0.1" and not self.ollama_up:
            raise httpx.ConnectError("refusé", request=request)
        if path == "/api/tags":
            return httpx.Response(200, json={"models": [
                {"name": "llama3.2:3b", "size": 2_000_000_000, "details": {"parameter_size": "3.2B"}},
                {"name": "deepseek-v4.1-flash:cloud", "size": 400, "remote_host": "https://ollama.com"}]})
        if path == "/api/chat":
            if self.ollama_status != 200:
                return httpx.Response(self.ollama_status, text="erreur")
            body = json.loads(request.content)
            return httpx.Response(200, json={"message": {"content": json.dumps({"via": host, "model": body["model"]})},
                                             "prompt_eval_count": 10, "eval_count": 20})
        return httpx.Response(404)

    def _openrouter(self, request: httpx.Request, path: str) -> httpx.Response:
        if path.endswith("/models"):
            return httpx.Response(200, json={"data": [
                {"id": "vendor/paid-model", "name": "Paid", "context_length": 200000,
                 "pricing": {"prompt": "0.000003", "completion": "0.000015"}},
                {"id": "vendor/free-model:free", "name": "Free", "context_length": 32000,
                 "pricing": {"prompt": "0", "completion": "0"}},
                {"id": "vendor/unknown-price", "name": "Unknown"}]})
        if request.headers.get("authorization") != f"Bearer {self.valid_key}":
            return httpx.Response(401, json={"error": {"message": "No auth credentials found", "code": 401}})
        if path.endswith("/key"):
            return httpx.Response(200, json={"data": {"label": "test", "limit_remaining": 4.5}})
        if self.openrouter_status != 200:
            return httpx.Response(self.openrouter_status, json={"error": {"message": "refus"}})
        body = json.loads(request.content)
        return httpx.Response(200, json={"model": body["model"], "choices": [
            {"message": {"content": json.dumps({"via": "openrouter", "model": body["model"]})}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.00105}})


@pytest.fixture
def cloud() -> FakeCloud:
    return FakeCloud()


# --- adaptateurs ---
def test_ollama_local_lists_installed_models_and_flags_cloud_ones(cloud: FakeCloud) -> None:
    provider = OllamaLocalProvider(transport=httpx.MockTransport(cloud.handler))
    models = {m.id: m for m in provider.list_models()}
    assert models["llama3.2:3b"].mode == "local" and models["llama3.2:3b"].paid is False
    assert models["llama3.2:3b"].size_bytes == 2_000_000_000
    assert models["deepseek-v4.1-flash:cloud"].mode == "cloud" and models["deepseek-v4.1-flash:cloud"].paid is True
    assert provider.test().ok and provider.is_paid("deepseek-v4.1-flash:cloud") and not provider.is_paid("llama3.2:3b")


def test_ollama_errors_are_named(cloud: FakeCloud) -> None:
    provider = OllamaLocalProvider(transport=httpx.MockTransport(cloud.handler))
    for status, error in ((401, InvalidKeyError), (429, QuotaError), (404, ModelUnavailableError)):
        cloud.ollama_status = status
        with pytest.raises(error):
            provider.generate(GenerationRequest(task="ideas", model="absent:1b", system="s", prompt="p"))
    cloud.ollama_up = False
    with pytest.raises(UnreachableError, match="Lance Ollama"):
        provider.list_models()
    cloud.timeout = True
    with pytest.raises(AiTimeoutError):
        provider.generate(REQUEST)


def test_ollama_cloud_needs_a_key_and_does_not_pretend_to_check_it(cloud: FakeCloud) -> None:
    transport = httpx.MockTransport(cloud.handler)
    without = OllamaCloudProvider(transport=transport)
    assert not without.test().ok
    with pytest.raises(NotConfiguredError):
        without.generate(REQUEST)
    result = OllamaCloudProvider(api_key="cle-ollama-123456", transport=transport).test()
    assert result.ok and result.key_checked is False and "pas vérifiée" in result.message
    assert cloud.requests[-1].url.host == "ollama.com"
    assert cloud.requests[-1].headers["authorization"] == "Bearer cle-ollama-123456"


def test_openrouter_models_prices_and_generation(cloud: FakeCloud) -> None:
    provider = OpenRouterProvider(api_key=KEY, transport=httpx.MockTransport(cloud.handler))
    models = {m.id: m for m in provider.list_models()}
    paid_model = models["vendor/paid-model"]
    assert paid_model.price_in_per_mtok == 3.0 and paid_model.price_out_per_mtok == 15.0
    assert models["vendor/paid-model"].paid is True and models["vendor/free-model:free"].paid is False
    assert models["vendor/unknown-price"].paid is None and provider.is_paid("vendor/unknown-price")
    assert provider.is_paid("inconnu") and not provider.is_paid("vendor/free-model:free")
    test = provider.test()
    assert test.ok and test.key_checked and "4.50" in test.message
    result = provider.generate(REQUEST)
    assert result.cost_usd == 0.00105 and result.input_tokens == 100 and result.output_tokens == 50


def test_openrouter_errors_are_named(cloud: FakeCloud) -> None:
    transport = httpx.MockTransport(cloud.handler)
    with pytest.raises(InvalidKeyError):
        OpenRouterProvider(api_key="mauvaise-cle-123", transport=transport).test()
    provider = OpenRouterProvider(api_key=KEY, transport=transport)
    for status, error in ((402, QuotaError), (429, QuotaError), (404, ModelUnavailableError), (504, AiTimeoutError)):
        cloud.openrouter_status = status
        with pytest.raises(error):
            provider.generate(REQUEST)


# --- application complete ---
@pytest.fixture
def app_client(tmp_path: Path, cloud: FakeCloud) -> Iterator[tuple[TestClient, TaskRouter]]:
    settings = make_settings(tmp_path, ollama_model="llama3.2:3b")
    runtime = build_runtime(settings)
    runtime.vault = Vault(MemoryKeyStore())
    router = TaskRouter(settings, runtime.vault, transport=httpx.MockTransport(cloud.handler))
    runtime.llm = router
    with TestClient(create_app(settings, full_registry(), runtime)) as client:
        yield client, router


def choose(client: TestClient, task: str, **body: Any) -> httpx.Response:
    return client.put(f"/api/ai/tasks/{task}", json=body)


def test_default_routing_is_the_previous_behaviour(app_client: tuple[TestClient, TaskRouter], cloud: FakeCloud) -> None:
    client, router = app_client
    tasks = {t["task"]: t for t in client.get("/api/ai/tasks").json()}
    assert set(tasks) == {"ideas", "script", "storyboard", "variants", "analysis"}
    assert all(t["mode"] == "local" and t["configured"] for t in tasks.values())
    assert all(t["is_default"] and t["provider_id"] == "ollama" and t["model"] == "llama3.2:3b" for t in tasks.values())
    assert router.for_task("ideas").generate_json("s", "p") == {"via": "127.0.0.1", "model": "llama3.2:3b"}
    call = client.get("/api/ai/calls").json()[0]
    assert call["ok"] and call["task"] == "ideas" and call["mode"] == "local" and call["input_tokens"] == 10


def test_key_is_stored_encrypted_and_never_returned(app_client: tuple[TestClient, TaskRouter]) -> None:
    client, _ = app_client
    res = client.put("/api/ai/providers/openrouter", json={"api_key": KEY})
    assert res.status_code == 200 and res.json()["key_set"] and res.json()["key_hint"] == "…WXYZ"
    for path in ("/api/ai/providers", "/api/ai/tasks", "/api/ai/calls", "/api/security"):
        assert KEY not in client.get(path).text
    test = client.post("/api/ai/providers/openrouter/test").json()
    assert test["ok"] and test["key_checked"]
    assert client.delete("/api/ai/providers/openrouter/key").json()["key_set"] is False
    assert client.post("/api/ai/providers/openrouter/test").json()["ok"] is False


def test_invalid_key_test_reports_the_reason(app_client: tuple[TestClient, TaskRouter]) -> None:
    client, _ = app_client
    client.put("/api/ai/providers/openrouter", json={"api_key": "sk-or-mauvaise-cle"})
    test = client.post("/api/ai/providers/openrouter/test").json()
    assert test == {"ok": False, "message": test["message"], "kind": "invalid_key", "key_checked": False,
                    "models_count": None}
    assert client.get("/api/ai/providers").json()[2]["last_test"]["ok"] is False


def test_paid_model_needs_explicit_agreement(app_client: tuple[TestClient, TaskRouter], cloud: FakeCloud) -> None:
    client, router = app_client
    client.put("/api/ai/providers/openrouter", json={"api_key": KEY})
    refused = choose(client, "script", provider_id="openrouter", model="vendor/paid-model")
    assert refused.status_code == 409 and refused.json()["kind"] == "needs_paid_confirmation"
    assert choose(client, "script", provider_id="openrouter", model="vendor/unknown-price").status_code == 409
    assert choose(client, "script", provider_id="ollama", model="deepseek-v4.1-flash:cloud").status_code == 409
    assert choose(client, "script", provider_id="openrouter", model="vendor/free-model:free").status_code == 200
    assert choose(client, "script", provider_id="openrouter", model="vendor/paid-model",
                  confirm_paid=True).status_code == 200
    assert router.for_task("script").generate_json("s", "p") == {"via": "openrouter", "model": "vendor/paid-model"}
    assert router.for_task("ideas").generate_json("s", "p")["via"] == "127.0.0.1"  # les autres taches ne bougent pas
    call = client.get("/api/ai/calls").json()[0]
    assert call["provider_id"] == "ollama" or call["cost_usd"] == 0.00105


def test_unknown_model_is_refused(app_client: tuple[TestClient, TaskRouter]) -> None:
    client, _ = app_client
    res = choose(client, "ideas", provider_id="ollama", model="modele-invente:7b")
    assert res.status_code == 400 and "ne figure pas" in res.json()["detail"]


def test_fallback_to_a_free_model_is_automatic(app_client: tuple[TestClient, TaskRouter], cloud: FakeCloud) -> None:
    client, router = app_client
    client.put("/api/ai/providers/openrouter", json={"api_key": KEY})
    assert choose(client, "ideas", provider_id="openrouter", model="vendor/free-model:free",
                  fallback_provider_id="ollama", fallback_model="llama3.2:3b").status_code == 200
    cloud.openrouter_status = 402  # credit epuise
    assert router.for_task("ideas").generate_json("s", "p") == {"via": "127.0.0.1", "model": "llama3.2:3b"}
    calls = client.get("/api/ai/calls").json()
    assert [(c["ok"], c["used_fallback"], c["error_kind"]) for c in calls[:2]] in (
        [(True, True, ""), (False, False, "quota")], [(False, False, "quota"), (True, True, "")])


def test_paid_fallback_is_never_used_without_agreement(app_client: tuple[TestClient, TaskRouter],
                                                       cloud: FakeCloud) -> None:
    client, router = app_client
    client.put("/api/ai/providers/openrouter", json={"api_key": KEY})
    body = {"provider_id": "ollama", "model": "llama3.2:3b", "fallback_provider_id": "openrouter",
            "fallback_model": "vendor/paid-model"}
    assert choose(client, "ideas", **body).status_code == 200
    cloud.ollama_up = False
    before = len(cloud.requests)
    with pytest.raises(PaidConfirmationError, match="n'a pas été utilisé"):
        router.for_task("ideas").generate_json("s", "p")
    assert not [r for r in cloud.requests[before:] if r.url.path.endswith("/chat/completions")]

    assert choose(client, "ideas", **body, allow_paid_fallback=True).status_code == 502  # Ollama eteint : invérifiable
    cloud.ollama_up = True
    assert choose(client, "ideas", **body, allow_paid_fallback=True).status_code == 200
    cloud.ollama_up = False
    assert router.for_task("ideas").generate_json("s", "p")["via"] == "openrouter"


def test_same_model_everywhere_and_reset(app_client: tuple[TestClient, TaskRouter]) -> None:
    client, _ = app_client
    tasks = choose(client, "ideas", provider_id="ollama", model="llama3.2:3b", temperature=0.4,
                   apply_to_all=True).json()
    assert all(not t["is_default"] and t["temperature"] == 0.4 for t in tasks)
    tasks = client.delete("/api/ai/tasks/script").json()
    assert {t["task"]: t["is_default"] for t in tasks} == {"ideas": False, "script": True, "storyboard": False,
                                                           "variants": False, "analysis": False}


def test_missing_vault_refuses_keys_with_a_clear_message(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path), full_registry())) as client:
        res = client.put("/api/ai/providers/openrouter", json={"api_key": KEY})
        assert res.status_code == 503 and "SHORTFORGE_SECRET_KEY" in res.json()["detail"]
        assert client.get("/api/security").json()["vault_available"] is False
        assert client.get("/api/ai/providers").json()[2]["key_set"] is False


# --- jeton de l'API locale ---
def test_local_api_requires_the_session_token(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, shortforge_api_token="jeton-de-session-123")
    with TestClient(create_app(settings, full_registry())) as client:
        assert client.get("/api/health").status_code == 200  # etat du moteur : ouvert
        assert client.get("/api/projects").status_code == 401
        assert client.get("/api/projects", headers={"Authorization": "Bearer faux"}).status_code == 401
        assert client.get("/api/projects", headers={"Authorization": "Bearer jeton-de-session-123"}).status_code == 200
        assert client.get("/api/projects?token=jeton-de-session-123").status_code == 200  # balises image et video
        assert client.post("/api/projects?token=jeton-de-session-123", json={}).status_code == 401  # GET seulement
        preflight = client.options("/api/projects", headers={"Origin": "tauri://localhost",
                                                              "Access-Control-Request-Method": "GET"})
        assert preflight.status_code == 200
        refused = client.get("/api/projects", headers={"Origin": "tauri://localhost"})
        assert refused.headers.get("access-control-allow-origin") == "tauri://localhost"  # l'interface lit le refus
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/projects/x/events"):
            pass


def test_without_token_configured_the_api_stays_open_for_development(client: TestClient) -> None:
    assert client.get("/api/projects").status_code == 200
    assert client.get("/api/security").json()["api_token_required"] is False
