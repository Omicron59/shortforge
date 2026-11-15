"""Faux services pour les tests : modele de texte, serveur ComfyUI et API Google simules."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.integrations.comfyui import ComfyUIClient, WorkflowLibrary
from shortforge.integrations.trends import ManualTrendSource, TrendSource
from shortforge.providers.registry import build_registry
from shortforge.runtime import Runtime

ASSETS_WORKFLOWS = Path(__file__).resolve().parents[2] / "assets" / "workflows"


class FakeLLM:
    """Renvoie les reponses prevues, dans l'ordre ; garde les prompts recus."""

    def __init__(self, *responses: dict[str, Any]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def generate_json(self, system: str, prompt: str, *, temperature: float | None = None) -> dict[str, Any]:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("FakeLLM : plus de réponse prévue")
        return self.responses.pop(0)

    def is_running(self) -> bool:
        return True


def ideas_response(*titles: str) -> dict[str, Any]:
    return {"ideas": [{"title": t, "hook": f"Accroche : {t}", "original_angle": "angle neuf",
                       "estimated_duration_s": 20, "potential_score": 70, "keywords": ["humour"],
                       "visual_style": "réaliste"} for t in titles]}


def script_response(importances: tuple[str, ...] = ("simple", "important")) -> dict[str, Any]:
    return {
        "hook": "Tu ne devineras jamais ce que fait ce grille-pain.",
        "body": "Il chante chaque matin. Personne ne sait pourquoi.",
        "conclusion": "Depuis, plus personne ne mange de pain grillé.",
        "call_to_action": "Abonne-toi pour la suite.",
        "scenes": [{"text": f"Scène {i}", "visual_prompt": f"a singing toaster in a kitchen, shot {i}",
                    "negative_prompt": "", "transition": "zoom" if i else "inconnue", "duration_s": 5,
                    "importance": imp} for i, imp in enumerate(importances)],
    }


class FakeComfyServer:
    """Simule l'API HTTP de ComfyUI (prompt, history, view, upload, system_stats)."""

    def __init__(self, *, output_name: str = "out.png", fail: bool = False) -> None:
        self.output_name = output_name
        self.fail = fail
        self.queued: list[dict[str, Any]] = []
        self.uploads: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/system_stats":
            return httpx.Response(200, json={"devices": [{"name": "NVIDIA RTX 4080", "vram_total": 16 * 2**30,
                                                          "vram_free": 12 * 2**30}]})
        if path == "/prompt":
            body = json.loads(request.content)
            self.queued.append(body["prompt"])
            return httpx.Response(200, json={"prompt_id": f"p{len(self.queued)}"})
        if path.startswith("/history/"):
            pid = path.rsplit("/", 1)[1]
            if self.fail:
                status = {"status_str": "error", "completed": False,
                          "messages": [["execution_error", {"exception_message": "CUDA out of memory"}]]}
                return httpx.Response(200, json={pid: {"status": status, "outputs": {}}})
            key = "gifs" if self.output_name.endswith(".mp4") else "images"
            return httpx.Response(200, json={pid: {"status": {"status_str": "success", "completed": True},
                                                   "outputs": {"9": {key: [{"filename": self.output_name,
                                                                            "subfolder": "", "type": "output"}]}}}})
        if path == "/view":
            return httpx.Response(200, content=b"fichier-genere-" + request.url.params["filename"].encode())
        if path == "/upload/image":
            self.uploads.append("upload")
            return httpx.Response(200, json={"name": "entree.png", "subfolder": ""})
        return httpx.Response(404)

    def client(self) -> ComfyUIClient:
        return ComfyUIClient("http://comfy.test", use_websocket=False, poll_interval_s=0,
                             transport=httpx.MockTransport(self.handler), sleep=lambda _: None)


class FakeGoogleApi:
    """Simule l'API Gemini (generation longue, operation, telechargement)."""

    def __init__(self) -> None:
        self.submitted: list[dict[str, Any]] = []
        self.polls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers.get("x-goog-api-key") == "cle-test" or request.url.host == "files.test"
        path = request.url.path
        if path.endswith(":predictLongRunning"):
            self.submitted.append(json.loads(request.content))
            return httpx.Response(200, json={"name": f"models/x/operations/op{len(self.submitted)}"})
        if "/operations/" in path:
            self.polls += 1
            if self.polls == 1:
                return httpx.Response(200, json={"name": path, "done": False})
            return httpx.Response(200, json={"done": True, "response": {"generateVideoResponse": {
                "generatedSamples": [{"video": {"uri": "https://files.test/video.mp4"}}]}}})
        if request.url.host == "files.test":
            return httpx.Response(200, content=b"mp4-video")
        return httpx.Response(404)


def make_runtime(settings: Settings, llm: FakeLLM, comfy: FakeComfyServer | None = None,
                 provider_handler: Callable[[httpx.Request], httpx.Response] | None = None,
                 trends: list[TrendSource] | None = None) -> Runtime:
    comfy = comfy or FakeComfyServer()
    client = comfy.client()
    library = WorkflowLibrary([ASSETS_WORKFLOWS], settings.shortforge_data_dir / "workflows")
    transport = httpx.MockTransport(provider_handler) if provider_handler else None

    def providers(session: Session) -> Any:
        return build_registry(session, settings, client, library, transport=transport)

    return Runtime(settings=settings, llm=llm, comfy=client, library=library,
                   trend_sources=lambda _s: trends if trends is not None else [ManualTrendSource([])],
                   providers=providers, sleep=lambda _: None)


def add_video_workflow(library: WorkflowLibrary, workflow_id: str = "comfyui_local") -> None:
    """Ajoute un faux workflow video local (meme structure que l'exemple d'image)."""
    workflow = json.loads((ASSETS_WORKFLOWS / "image_default.json").read_text(encoding="utf-8"))
    library.add(workflow_id, workflow, name=f"Vidéo {workflow_id}", kind="video")
