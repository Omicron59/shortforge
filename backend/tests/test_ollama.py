from __future__ import annotations

import json

import httpx
import pytest

from shortforge.integrations.ollama import LLMError, OllamaClient


def client(handler: httpx.MockTransport | None = None, model: str = "mon-modele") -> OllamaClient:
    return OllamaClient("http://ollama.test", model, transport=handler)


def chat_reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})


def test_generate_json_sends_json_mode_and_parses_reply() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return chat_reply('```json\n{"ideas": [1, 2]}\n```')

    result = client(httpx.MockTransport(handler)).generate_json("système", "question")
    assert result == {"ideas": [1, 2]}
    assert seen["format"] == "json" and seen["stream"] is False and seen["model"] == "mon-modele"
    assert seen["messages"][0] == {"role": "system", "content": "système"}


def test_retries_once_on_invalid_json() -> None:
    replies = iter([chat_reply("pas du json"), chat_reply('{"ok": true}')])
    result = client(httpx.MockTransport(lambda _: next(replies))).generate_json("s", "p")
    assert result == {"ok": True}


def test_invalid_json_twice_raises() -> None:
    with pytest.raises(LLMError, match="JSON valide"):
        client(httpx.MockTransport(lambda _: chat_reply("toujours pas"))).generate_json("s", "p")


def test_missing_model_is_explained() -> None:
    with pytest.raises(LLMError, match="ollama pull mon-modele"):
        client(httpx.MockTransport(lambda _: httpx.Response(404, json={"error": "not found"}))).generate_json("s", "p")


def test_no_model_configured() -> None:
    with pytest.raises(LLMError, match="OLLAMA_MODEL"):
        client(model="").generate_json("s", "p")


def test_unreachable_server() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé", request=request)

    c = client(httpx.MockTransport(handler))
    with pytest.raises(LLMError, match="Lance Ollama"):
        c.generate_json("s", "p")
    assert c.is_running() is False


def test_list_models() -> None:
    reply = httpx.Response(200, json={"models": [{"name": "qwen3:8b"}, {"name": "mistral"}]})
    assert client(httpx.MockTransport(lambda _: reply)).list_models() == ["qwen3:8b", "mistral"]
