"""Nouveau parcours de creation : brief, idees, script et storyboard, versions, reprise, annulation.

Le modele de texte est SIMULE (FakeLLM) : ces tests ne prouvent pas la qualite d'une vraie generation.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from shortforge.integrations.ollama import LLMError
from shortforge.main import create_app
from tests.conftest import full_registry, make_settings
from tests.fakes import FakeLLM, make_runtime
from tests.test_migrations import old_database

BRIEF = {"subject": "Pourquoi les chats ronronnent", "niche": "animaux", "audience": "curieux de 18 à 35 ans",
         "tone": "humour", "duration_s": 30, "avoid": "politique"}


def ideas_json(*titles: str) -> dict[str, Any]:
    return {"ideas": [{"title": t, "hook": f"Accroche {t}", "angle": "angle neuf", "summary": "Résumé en deux phrases.",
                       "duration_s": 30, "difficulty": "facile", "resources": ["images de chats"],
                       "fit_reason": "répond au brief", "virality_score": 99} for t in titles]}


def script_json(count: int = 3) -> dict[str, Any]:
    return {"hook": "Ton chat te parle.", "body": "Il ronronne.", "conclusion": "Voilà.", "call_to_action": "",
            "scenes": [{"text": f"Texte de la scène {i}", "on_screen_text": f"ÉCRAN {i}",
                        "visual_intent": f"montrer un chat {i}", "visual_prompt": f"a cat, shot {i}, vertical",
                        "negative_prompt": "", "transition": "cut", "duration_s": 4, "importance": "simple"}
                       for i in range(count)]}


class Flow:
    def __init__(self, client: TestClient, llm: FakeLLM) -> None:
        self.client, self.llm = client, llm

    def create(self, **changes: Any) -> dict[str, Any]:
        res = self.client.post("/api/wizard/projects", json={**BRIEF, **changes})
        assert res.status_code == 201, res.text
        state: dict[str, Any] = res.json()
        return state

    def post(self, path: str, body: dict[str, Any] | None = None, status: int = 200) -> dict[str, Any]:
        res = self.client.post(f"/api/wizard{path}", json=body or {})
        assert res.status_code == status, res.text
        data: dict[str, Any] = res.json()
        return data

    def state(self, pid: str) -> dict[str, Any]:
        data: dict[str, Any] = self.client.get(f"/api/wizard/projects/{pid}").json()
        return data

    def with_script(self) -> tuple[str, dict[str, Any]]:
        """Projet avec 5 idees, une idee choisie et un script de 3 scenes."""
        pid = self.create()["project"]["id"]
        self.llm.responses += [ideas_json("A1 chat", "B2 ronron", "C3 moustache", "D4 griffe", "E5 sieste"),
                               script_json()]
        ideas = self.post(f"/projects/{pid}/ideas")["ideas"]
        self.post(f"/projects/{pid}/ideas/{ideas[0]['id']}/choose")
        return pid, self.post(f"/projects/{pid}/script/generate")


@pytest.fixture
def flow(tmp_path: Path) -> Iterator[Flow]:
    settings = make_settings(tmp_path)
    llm = FakeLLM()
    runtime = make_runtime(settings, llm)
    with TestClient(create_app(settings, full_registry(), runtime)) as client:
        yield Flow(client, llm)


def step(state: dict[str, Any], name: str) -> str:
    return str(next(s["status"] for s in state["project"]["steps"] if s["name"] == name))


# --- brief ---
def test_options_give_defaults_for_a_short_form(flow: Flow) -> None:
    options = flow.client.get("/api/wizard/options").json()
    assert options["defaults"]["language"] == "fr" and options["defaults"]["duration_s"] == 30
    assert options["durations"] == [20, 30, 45, 60] and "youtube_shorts" in options["platforms"]


def test_brief_creates_a_draft_project_and_is_autosaved(flow: Flow) -> None:
    assert flow.client.post("/api/wizard/projects", json={"subject": " ", "niche": ""}).status_code == 400
    state = flow.create(goal="inconnu", duration_s=33)
    pid = state["project"]["id"]
    assert state["step"] == "ideas" and state["project"]["title"] == "Pourquoi les chats ronronnent"
    assert state["brief"]["goal"] == "vues" and state["brief"]["duration_s"] == 30  # valeurs invalides corrigees
    assert state["ideas"] == [] and state["script"] is None
    saved = flow.client.put(f"/api/wizard/projects/{pid}/brief", json={**BRIEF, "audience": "enfants"}).json()
    assert saved["audience"] == "enfants" and flow.state(pid)["brief"]["audience"] == "enfants"
    assert pid in [p["id"] for p in flow.client.get("/api/projects").json()]  # visible aussi dans l'ancien parcours


# --- idees ---
def test_five_ideas_are_generated_from_the_brief_without_any_score(flow: Flow) -> None:
    pid = flow.create()["project"]["id"]
    flow.llm.responses.append(ideas_json("Un", "Deux chats", "Trois ronrons", "Quatre pattes", "Cinq siestes", "Six"))
    state = flow.post(f"/projects/{pid}/ideas")
    assert len(state["ideas"]) == 5 and len(state["new_idea_ids"]) == 5
    idea = state["ideas"][0]
    assert idea["summary"] and idea["difficulty"] == "facile" and idea["resources"] == ["images de chats"]
    assert idea["fit_reason"] == "répond au brief" and idea["potential_score"] == 0  # aucun score invente
    prompt = flow.llm.prompts[-1]
    assert "curieux de 18 à 35 ans" in prompt and "politique" in prompt and "Humour" in prompt
    assert step(state, "generate_ideas") == "done" and state["step"] == "ideas"


def test_new_ideas_keep_the_previous_ones_and_drop_duplicates(flow: Flow) -> None:
    pid = flow.create()["project"]["id"]
    flow.llm.responses += [ideas_json("Alpha chat", "Beta ronron"), ideas_json("Alpha chat", "Gamma moustache")]
    first = flow.post(f"/projects/{pid}/ideas")
    second = flow.post(f"/projects/{pid}/ideas")
    titles = [i["title"] for i in second["ideas"]]
    assert sorted(titles) == ["Alpha chat", "Beta ronron", "Gamma moustache"]
    assert any("trop proche" in r for r in second["rejected"]) and len(first["ideas"]) == 2
    assert "Alpha chat" in flow.llm.prompts[-1]  # le modele sait ce qui a deja ete propose


def test_variant_edit_and_save_for_later(flow: Flow) -> None:
    pid = flow.create()["project"]["id"]
    flow.llm.responses += [ideas_json("Idée mère"), ideas_json("Variante émotion", "Variante choc")]
    base = flow.post(f"/projects/{pid}/ideas")["ideas"][0]
    state = flow.post(f"/projects/{pid}/ideas", {"variant_of": base["id"]})
    variants = [i for i in state["ideas"] if i["parent_id"] == base["id"]]
    assert len(variants) == 2 and "Idée mère" in flow.llm.prompts[-1] and len(state["ideas"]) == 3
    patched = flow.client.patch(f"/api/wizard/ideas/{base['id']}", json={"title": "Idée retouchée", "saved": True})
    assert patched.json()["title"] == "Idée retouchée" and patched.json()["saved"] is True
    assert flow.client.patch(f"/api/wizard/ideas/{base['id']}", json={"title": "x"}).status_code == 422


def test_choosing_an_idea_then_changing_it_before_the_script_is_validated(flow: Flow) -> None:
    pid = flow.create()["project"]["id"]
    flow.llm.responses.append(ideas_json("Première", "Deuxième idée"))
    ideas = flow.post(f"/projects/{pid}/ideas")["ideas"]
    state = flow.post(f"/projects/{pid}/ideas/{ideas[0]['id']}/choose")
    assert state["selected_idea_id"] == ideas[0]["id"] and step(state, "select_idea") == "done"
    state = flow.post(f"/projects/{pid}/ideas/{ideas[1]['id']}/choose")
    assert state["selected_idea_id"] == ideas[1]["id"] and step(state, "select_idea") == "done"
    assert state["step"] == "ideas"  # pas encore de script


# --- script et storyboard ---
def test_script_and_storyboard_are_generated_and_validated_by_the_backend(flow: Flow) -> None:
    pid, state = flow.with_script()
    scenes = state["script"]["scenes"]
    assert state["step"] == "script" and [s["position"] for s in scenes] == [0, 1, 2]
    assert scenes[1]["on_screen_text"] == "ÉCRAN 1" and scenes[1]["visual_intent"] == "montrer un chat 1"
    assert state["script"]["estimated_duration_s"] > 0 and step(state, "write_script") == "done"
    assert "30 secondes" in flow.llm.prompts[-1] and "curieux" in flow.llm.prompts[-1]

    flow.llm.responses.append({"hook": "", "scenes": []})  # reponse incomplete du modele
    res = flow.client.post(f"/api/wizard/projects/{pid}/script/generate", json={})
    assert res.status_code == 502 and "incomplet" in res.json()["detail"]
    assert flow.state(pid)["script"]["version"] == state["script"]["version"]  # rien n'est ecrase


def test_scene_edit_add_delete_and_reorder(flow: Flow) -> None:
    pid, state = flow.with_script()
    a, b, c = (s["id"] for s in state["script"]["scenes"])
    edited = flow.client.patch(f"/api/wizard/scenes/{b}", json={"text": "Texte réécrit à la main", "duration_s": 99})
    assert edited.status_code == 422
    edited = flow.client.patch(f"/api/wizard/scenes/{b}", json={"text": "Texte réécrit à la main"})
    assert edited.json()["text"] == "Texte réécrit à la main"

    state = flow.post(f"/projects/{pid}/scenes", {"after": 0})
    new = state["scene_id"]
    assert [s["id"] for s in state["script"]["scenes"]] == [a, new, b, c]
    assert any("prompt visuel manquant" in p for p in state["problems"])

    order = flow.client.put(f"/api/wizard/projects/{pid}/scenes/order", json={"ids": [c, a, new, b]})
    assert [s["id"] for s in order.json()["script"]["scenes"]] == [c, a, new, b]
    assert flow.client.put(f"/api/wizard/projects/{pid}/scenes/order", json={"ids": [c, a]}).status_code == 400

    after = flow.client.delete(f"/api/wizard/scenes/{new}").json()
    scenes = after["script"]["scenes"]
    assert [s["id"] for s in scenes] == [c, a, b] and [s["position"] for s in scenes] == [0, 1, 2]
    assert scenes[2]["text"] == "Texte réécrit à la main" and after["problems"] == []


def test_targeted_regeneration_changes_one_field_of_one_scene_only(flow: Flow) -> None:
    pid, state = flow.with_script()
    first, second, third = state["script"]["scenes"]
    flow.client.patch(f"/api/wizard/scenes/{first['id']}", json={"text": "Ma phrase écrite à la main"})
    flow.llm.responses.append({"value": "a fluffy cat purring on a sofa, vertical"})
    res = flow.post(f"/scenes/{second['id']}/regenerate-field", {"field": "visual_prompt"})
    assert res["scene"]["visual_prompt"] == "a fluffy cat purring on a sofa, vertical"
    assert res["scene"]["text"] == second["text"] and res["scene"]["on_screen_text"] == second["on_screen_text"]
    scenes = flow.state(pid)["script"]["scenes"]
    assert scenes[0]["text"] == "Ma phrase écrite à la main" and scenes[2] == third

    flow.llm.responses.append({"value": "  "})  # reponse vide : rien ne change
    res2 = flow.client.post(f"/api/wizard/scenes/{second['id']}/regenerate-field", json={"field": "text"})
    assert res2.status_code == 502 and flow.state(pid)["script"]["scenes"][1]["text"] == second["text"]
    assert flow.client.post(f"/api/wizard/scenes/{second['id']}/regenerate-field",
                            json={"field": "seed"}).status_code == 400


def test_hook_variants_are_proposals_and_change_nothing(flow: Flow) -> None:
    pid, state = flow.with_script()
    flow.llm.responses.append({"hooks": ["Et si ton chat te mentait ?", "Trois secondes pour comprendre.", 12]})
    res = flow.post(f"/projects/{pid}/script/hooks")
    assert res["hooks"] == ["Et si ton chat te mentait ?", "Trois secondes pour comprendre."]
    assert flow.state(pid)["script"] == state["script"]


def test_shorten_and_tone_create_a_new_version_and_history_can_be_restored(flow: Flow) -> None:
    pid, state = flow.with_script()
    v1 = state["script"]["version"]
    flow.llm.responses += [script_json(2), script_json(2)]
    shorter = flow.post(f"/projects/{pid}/script/transform", {"kind": "shorten"})
    assert shorter["script"]["version"] == v1 + 1 and len(shorter["script"]["scenes"]) == 2
    assert "Raccourcis" in flow.llm.prompts[-1] and "Texte de la scène 2" in flow.llm.prompts[-1]
    toned = flow.post(f"/projects/{pid}/script/transform", {"kind": "tone", "tone": "choc"})
    assert toned["brief"]["tone"] == "choc" and toned["script"]["version"] == v1 + 2
    assert flow.client.post(f"/api/wizard/projects/{pid}/script/transform",
                            json={"kind": "tone", "tone": "x"}).status_code == 400

    versions = flow.client.get(f"/api/wizard/projects/{pid}/script/versions").json()
    assert [v["version"] for v in versions] == [v1 + 2, v1 + 1, v1] and versions[0]["current"]
    restored = flow.post(f"/projects/{pid}/script/versions/{v1}/restore")
    assert restored["script"]["version"] == v1 + 3 and len(restored["script"]["scenes"]) == 3
    assert len(flow.client.get(f"/api/wizard/projects/{pid}/script/versions").json()) == 4  # rien n'est efface

    ids_before = [s["id"] for s in restored["script"]["scenes"]]
    history = flow.post(f"/projects/{pid}/script/snapshot")  # une liste, pas un etat
    assert len(history) == 5
    assert [s["id"] for s in flow.state(pid)["script"]["scenes"]] == ids_before  # le script courant garde ses scenes


def test_manual_script_needs_no_model(flow: Flow) -> None:
    pid = flow.create()["project"]["id"]
    state = flow.post(f"/projects/{pid}/script/manual")
    assert state["step"] == "script" and len(state["script"]["scenes"]) == 1 and flow.llm.prompts == []
    assert state["selected_idea_id"] and step(state, "write_script") == "done"
    assert state["problems"]  # scene vide : pas encore validable
    assert flow.client.post(f"/api/wizard/projects/{pid}/script/approve", json={}).status_code == 409


def test_model_error_keeps_the_brief_and_what_exists(flow: Flow) -> None:
    pid = flow.create()["project"]["id"]

    def broken(*_: Any, **__: Any) -> dict[str, Any]:
        raise LLMError("Ollama ne répond pas à http://127.0.0.1:11434. Lance Ollama puis réessaie.")

    flow.llm.generate_json = broken  # type: ignore[method-assign]
    res = flow.client.post(f"/api/wizard/projects/{pid}/ideas", json={})
    assert res.status_code == 502 and "Ollama ne répond pas" in res.json()["detail"]
    state = flow.state(pid)
    assert state["brief"]["subject"] == BRIEF["subject"] and state["ideas"] == []
    assert step(state, "generate_ideas") == "pending"


def test_cancelled_generation_saves_nothing(flow: Flow) -> None:
    pid = flow.create()["project"]["id"]
    flow.llm.responses.append(ideas_json("Idée annulée"))
    assert flow.client.post("/api/wizard/cancel/req-1").json() == {"cancelled": True}
    res = flow.client.post(f"/api/wizard/projects/{pid}/ideas", json={"request_id": "req-1"})
    assert res.status_code == 409 and "annulée" in res.json()["detail"]
    assert flow.state(pid)["ideas"] == []
    flow.llm.responses.append(ideas_json("Idée gardée"))
    again = flow.post(f"/projects/{pid}/ideas", {"request_id": "req-1"})  # l'annulation ne sert qu'une fois
    assert len(again["ideas"]) == 1


# --- studio ---
def test_approval_opens_the_studio_and_edits_flag_stale_media(flow: Flow) -> None:
    pid, _ = flow.with_script()
    studio = flow.post(f"/projects/{pid}/script/approve")
    assert studio["step"] == "studio" and studio["script_approved"] and studio["script"]["status"] == "approved"
    assert step(studio, "approve_script") == "done" and step(studio, "create_storyboard") == "done"
    assert step(studio, "generate_images") == "pending"  # aucune generation de media lancee
    assert studio["stale"] == {"images": [], "voice": False, "subtitles": False, "render": False}

    scene = studio["script"]["scenes"][0]
    assert flow.client.post(f"/api/wizard/projects/{pid}/scenes", json={}).status_code == 409  # structure figee
    assert flow.client.delete(f"/api/wizard/scenes/{scene['id']}").status_code == 409
    for _ in range(7):  # images, videos, voix, sous-titres, musique, montage (faux gestionnaires)
        flow.client.post(f"/api/projects/{pid}/pipeline/advance")
    assert step(flow.state(pid), "render_video") == "done"
    flow.client.patch(f"/api/wizard/scenes/{scene['id']}", json={"text": "Nouveau texte dit"})
    stale = flow.state(pid)["stale"]
    assert stale["voice"] and stale["subtitles"] and stale["render"]
    assert step(flow.state(pid), "generate_voice") == "done"  # signale, mais rien n'est relance


def test_reopening_the_script_keeps_everything_and_allows_structure_changes(flow: Flow) -> None:
    pid, _ = flow.with_script()
    flow.post(f"/projects/{pid}/script/approve")
    reopened = flow.post(f"/projects/{pid}/script/reopen")
    assert reopened["step"] == "script" and not reopened["script_approved"]
    assert reopened["script"]["status"] == "draft" and len(reopened["script"]["scenes"]) == 3
    assert flow.client.post(f"/api/wizard/projects/{pid}/scenes", json={}).status_code == 200


def test_user_image_can_replace_a_generation(flow: Flow, media: dict[str, bytes]) -> None:
    pid, state = flow.with_script()
    scene = state["script"]["scenes"][0]["id"]
    refused = flow.client.put(f"/api/wizard/scenes/{scene}/image?filename=chat.png", content=media["png"])
    assert refused.status_code == 502 and "droit" in refused.json()["detail"]
    assert flow.client.put(f"/api/wizard/scenes/{scene}/image?filename=chat.gif&rights_confirmed=true",
                           content=media["png"]).status_code == 502
    ok = flow.client.put(f"/api/wizard/scenes/{scene}/image?filename=chat.png&rights_confirmed=true",
                         content=media["png"])
    assert ok.status_code == 200 and ok.json()["image_status"] == "done"
    assets = flow.client.get(f"/api/projects/{pid}/assets?kind=image").json()
    assert len(assets) == 1 and assets[0]["origin"] == "imported" and assets[0]["scene_id"] == scene


# --- reprise, duplication, compatibilite ---
def test_draft_is_resumed_after_a_restart(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    llm = FakeLLM(ideas_json("Idée un", "Idée deux chats"), script_json())
    with TestClient(create_app(settings, full_registry(), make_runtime(settings, llm))) as client:
        flow = Flow(client, llm)
        pid = flow.create()["project"]["id"]
        ideas = flow.post(f"/projects/{pid}/ideas")["ideas"]
        flow.post(f"/projects/{pid}/ideas/{ideas[1]['id']}/choose")
        scenes = flow.post(f"/projects/{pid}/script/generate")["script"]["scenes"]
        client.patch(f"/api/wizard/scenes/{scenes[0]['id']}", json={"text": "Modifié avant de quitter"})
    with TestClient(create_app(settings, full_registry(), make_runtime(settings, FakeLLM()))) as client:
        state = client.get(f"/api/wizard/projects/{pid}").json()
        assert state["step"] == "script" and state["selected_idea_id"] == ideas[1]["id"]
        assert state["brief"]["audience"] == BRIEF["audience"] and len(state["ideas"]) == 2
        assert state["script"]["scenes"][0]["text"] == "Modifié avant de quitter"


def test_duplicate_copies_brief_idea_and_script_but_no_media(flow: Flow) -> None:
    pid, state = flow.with_script()
    copy = flow.post(f"/projects/{pid}/duplicate", status=201)
    assert copy["project"]["id"] != pid and copy["project"]["title"].endswith("(copie)")
    assert copy["brief"] == state["brief"] and copy["step"] == "script" and len(copy["ideas"]) == 1
    assert [s["text"] for s in copy["script"]["scenes"]] == [s["text"] for s in state["script"]["scenes"]]
    assert not {s["id"] for s in copy["script"]["scenes"]} & {s["id"] for s in state["script"]["scenes"]}
    assert all(s["image_status"] == "pending" for s in copy["script"]["scenes"])
    flow.client.patch(f"/api/wizard/scenes/{copy['script']['scenes'][0]['id']}", json={"text": "Copie modifiée"})
    assert flow.state(pid)["script"] == state["script"]  # l'original ne bouge pas


def test_project_from_the_old_flow_opens_in_the_new_one(tmp_path: Path) -> None:
    old_database(tmp_path / "shortforge.sqlite3")
    con = sqlite3.connect(tmp_path / "shortforge.sqlite3")
    steps = ["generate_ideas", "select_idea", "write_script", "approve_script", "create_storyboard",
             "generate_images", "generate_videos", "generate_voice", "create_subtitles", "select_music",
             "render_video", "review_preview", "approve_final_render", "create_youtube_draft", "publish"]
    for position, name in enumerate(steps):
        con.execute("INSERT INTO pipeline_steps (project_id, name, position, status, attempts, created_at, "
                    "updated_at) VALUES ('p1', ?, ?, 'pending', 0, '2026-11-01', '2026-11-01')", (name, position))
    con.execute("INSERT INTO ideas (id, project_id, title, hook, original_angle, estimated_duration_s, "
                "potential_score, keywords, reuse_risk, visual_style, sources, selected, created_at) VALUES "
                "('i1', 'p1', 'Ancienne idée', 'h', 'a', 30, 70, '[]', 'low', '', '[]', 0, '2026-11-01')")
    con.commit()
    con.close()
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings, full_registry(), make_runtime(settings, FakeLLM()))) as client:
        state = client.get("/api/wizard/projects/p1").json()
        assert state["step"] == "ideas" and state["brief"]["niche"] == "cuisine" and state["brief"]["language"] == "fr"
        assert state["ideas"][0]["title"] == "Ancienne idée" and state["ideas"][0]["summary"] == ""
        chosen = client.post("/api/wizard/projects/p1/ideas/i1/choose").json()
        assert chosen["selected_idea_id"] == "i1"
        assert client.get("/api/projects/p1/ideas").json()[0]["selected"] is True  # l'ancien parcours le voit aussi


# --- anciens projets ---
def old_project_without_steps(tmp_path: Path, idea_seconds: float) -> None:
    old_database(tmp_path / "shortforge.sqlite3")  # projet p1, cree en 0.5.3, sans ses etapes
    con = sqlite3.connect(tmp_path / "shortforge.sqlite3")
    con.execute("INSERT INTO ideas (id, project_id, title, hook, original_angle, estimated_duration_s, "
                "potential_score, keywords, reuse_risk, visual_style, sources, selected, created_at) VALUES "
                "('i1', 'p1', 'Ancienne idée', 'h', 'a', ?, 70, '[]', 'low', '', '[]', 1, '2026-11-01')",
                (idea_seconds,))
    con.commit()
    con.close()


def test_project_without_steps_opens_and_gets_its_steps_back(tmp_path: Path) -> None:
    old_project_without_steps(tmp_path, 44)
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings, full_registry(), make_runtime(settings, FakeLLM()))) as client:
        res = client.get("/api/wizard/projects/p1")
        assert res.status_code == 200, res.text
        state = res.json()
        assert len(state["project"]["steps"]) == 15 and step(state, "generate_ideas") == "pending"
        assert state["brief"]["duration_s"] == 45  # duree de son idee (44 s), pas 30 s par defaut
        assert len(client.get("/api/wizard/projects/p1").json()["project"]["steps"]) == 15  # rien en double


def test_legacy_brief_created_with_30_s_is_corrected_once(tmp_path: Path) -> None:
    old_project_without_steps(tmp_path, 58)
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings, full_registry(), make_runtime(settings, FakeLLM()))):
        pass  # premier demarrage : mise a niveau de la base
    con = sqlite3.connect(tmp_path / "shortforge.sqlite3")  # brief vide cree par la 0.7.0 avec 30 s
    con.execute("INSERT INTO briefs (project_id, subject, niche, audience, goal, language, tone, duration_s, platform, "
                "visual_style, constraints, avoid, updated_at) VALUES ('p1', '', 'cuisine', '', 'vues', 'fr', "
                "'educatif', 30, 'youtube_shorts', '', '', '', '2026-11-17')")
    con.commit()
    con.close()
    with TestClient(create_app(settings, full_registry(), make_runtime(settings, FakeLLM()))) as client:
        assert client.get("/api/wizard/projects/p1").json()["brief"]["duration_s"] == 60
        brief = {**client.get("/api/wizard/projects/p1").json()["brief"], "duration_s": 20}
        client.put("/api/wizard/projects/p1/brief", json=brief)  # choix de l'utilisateur : respecte ensuite
        assert client.get("/api/wizard/projects/p1").json()["brief"]["duration_s"] == 20


def test_new_flow_brief_keeps_its_default_duration(flow: Flow) -> None:
    pid = flow.create(subject="", niche="jardinage")["project"]["id"]  # seulement une niche : 30 s par defaut
    flow.llm.responses.append(ideas_json("Une idée de 60 secondes"))
    ideas = flow.post(f"/projects/{pid}/ideas")["ideas"]
    flow.client.patch(f"/api/wizard/ideas/{ideas[0]['id']}", json={"title": "Une idée retouchée"})
    flow.post(f"/projects/{pid}/ideas/{ideas[0]['id']}/choose")
    assert flow.state(pid)["brief"]["duration_s"] == 30
