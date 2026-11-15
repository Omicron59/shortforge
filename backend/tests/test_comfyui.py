from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from shortforge.integrations.comfyui import (
    ComfyUIClient,
    ComfyUIError,
    WorkflowLibrary,
    apply_inputs,
    guess_inputs,
    validate_api_workflow,
)
from tests.fakes import ASSETS_WORKFLOWS, FakeComfyServer


def example() -> dict:
    return json.loads((ASSETS_WORKFLOWS / "image_default.json").read_text(encoding="utf-8"))


def library(tmp_path: Path) -> WorkflowLibrary:
    return WorkflowLibrary([ASSETS_WORKFLOWS], tmp_path / "workflows")


def test_ui_format_is_rejected() -> None:
    with pytest.raises(ComfyUIError, match="Export \\(API\\)"):
        validate_api_workflow({"nodes": [], "links": []})
    with pytest.raises(ComfyUIError, match="nœud 1"):
        validate_api_workflow({"1": {"inputs": {}}})


def test_guess_inputs_on_example_workflow() -> None:
    refs = guess_inputs(example())
    assert (refs["prompt"].node, refs["negative_prompt"].node, refs["seed"].node) == ("6", "7", "3")
    assert refs["width"].node == "5" and refs["model"].field == "ckpt_name"


def test_apply_inputs_replaces_values_without_touching_original(tmp_path: Path) -> None:
    lib = library(tmp_path)
    workflow, spec = lib.load("image_default")
    filled = apply_inputs(workflow, spec, {"prompt": "un chat", "seed": 42, "width": 720, "height": 1280,
                                           "negative_prompt": None, "input_image": "ignoré"})
    assert filled["6"]["inputs"]["text"] == "un chat" and filled["3"]["inputs"]["seed"] == 42
    assert filled["5"]["inputs"]["width"] == 720 and filled["7"]["inputs"]["text"] == ""
    assert workflow["6"]["inputs"]["text"] == ""


def test_library_lists_project_and_user_workflows(tmp_path: Path) -> None:
    lib = library(tmp_path)
    spec = lib.add("mon_wan", example(), name="Mon Wan", kind="video")
    assert spec.user and spec.kind == "video" and "prompt" in spec.inputs
    ids = {s.id: s for s in lib.list()}
    assert ids["image_default"].name == "Image verticale SDXL (exemple)" and not ids["image_default"].user
    assert ids["mon_wan"].name == "Mon Wan"


def test_library_rejects_bad_mapping_and_ids(tmp_path: Path) -> None:
    lib = library(tmp_path)
    with pytest.raises(ComfyUIError, match="99"):
        lib.add("x", example(), inputs={"prompt": {"node": "99", "field": "text"}})
    with pytest.raises(ComfyUIError, match="Identifiant"):
        lib.add("../evil", example())
    with pytest.raises(ComfyUIError, match="introuvable"):
        lib.get("absent")


def test_run_queues_waits_and_downloads(tmp_path: Path) -> None:
    server = FakeComfyServer()
    client = server.client()
    paths = client.run(example(), tmp_path / "out")
    assert paths[0].read_bytes() == b"fichier-genere-out.png"
    assert server.queued and client.is_running()


def test_failed_generation_is_reported(tmp_path: Path) -> None:
    client = FakeComfyServer(fail=True).client()
    with pytest.raises(ComfyUIError, match="CUDA out of memory"):
        client.run(example(), tmp_path)


def test_node_errors_are_described() -> None:
    body = {"error": {"message": "Prompt invalide"},
            "node_errors": {"4": {"class_type": "CheckpointLoaderSimple",
                                  "errors": [{"message": "Value not in list", "details": "ckpt_name"}]}}}
    client = ComfyUIClient("http://c.test", use_websocket=False,
                           transport=httpx.MockTransport(lambda _: httpx.Response(400, json=body)))
    with pytest.raises(ComfyUIError, match="nœud 4 \\(CheckpointLoaderSimple\\) : Value not in list"):
        client.queue(example(), "id")


def test_not_running() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("non", request=request)

    client = ComfyUIClient("http://c.test", transport=httpx.MockTransport(handler))
    assert client.is_running() is False
    with pytest.raises(ComfyUIError, match="Lance ComfyUI Desktop"):
        client.system_stats()


def test_progress_callback_on_polling(tmp_path: Path) -> None:
    progress: list[float] = []
    FakeComfyServer().client().wait("p1", "c", on_progress=lambda f, _m: progress.append(f))
    assert progress == [1.0]
