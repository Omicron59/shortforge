from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from shortforge.integrations.ollama import LLMError
from shortforge.models import Idea, Project
from shortforge.services.scripts import (
    DEFAULT_NEGATIVE,
    check_script,
    current_script,
    scenes_of,
    shorten_script,
    spoken_duration,
    update_script,
    write_script,
)
from tests.fakes import FakeLLM, script_response


def setup(session: Session) -> tuple[Project, Idea]:
    project = Project(title="Grille-pain", language="fr")
    session.add(project)
    session.flush()
    idea = Idea(project_id=project.id, title="Le grille-pain qui chante", hook="Il chante !", estimated_duration_s=20,
                selected=True)
    session.add(idea)
    session.flush()
    return project, idea


def test_write_script_creates_version_and_scenes(session: Session) -> None:
    project, idea = setup(session)
    llm = FakeLLM(script_response())
    result = write_script(session, llm, project, idea)
    assert result.script.version == 1 and result.script.hook.startswith("Tu ne devineras")
    assert result.script.estimated_duration_s == spoken_duration(
        " ".join([result.script.hook, result.script.body, result.script.conclusion, result.script.call_to_action]))
    assert [s.position for s in result.scenes] == [0, 1]
    assert result.scenes[0].transition == "cut"  # transition inconnue -> coupe franche
    assert result.scenes[1].transition == "zoom" and result.scenes[1].importance == "important"
    assert result.scenes[0].negative_prompt == DEFAULT_NEGATIVE
    assert "20 secondes" in llm.prompts[0]


def test_regenerating_creates_a_new_version(session: Session) -> None:
    project, idea = setup(session)
    write_script(session, FakeLLM(script_response()), project, idea)
    second = write_script(session, FakeLLM(script_response(("simple",))), project, idea)
    assert second.script.version == 2
    current = current_script(session, project.id)
    assert current is not None and current.id == second.script.id
    assert len(scenes_of(session, current.id)) == 1


def test_shorten_script(session: Session) -> None:
    project, idea = setup(session)
    first = write_script(session, FakeLLM(script_response()), project, idea)
    llm = FakeLLM(script_response(("simple",)))
    short = shorten_script(session, llm, project, first.script, 10)
    assert short.script.version == 2 and "10 secondes" in llm.prompts[0]


def test_manual_edit_updates_duration_and_scenes(session: Session) -> None:
    project, idea = setup(session)
    script = write_script(session, FakeLLM(script_response()), project, idea).script
    result = update_script(session, script, {"hook": "Un hook bien plus court ici."},
                           [{"visual_prompt": "a toaster on fire", "duration_s": 4}])
    assert result.script.hook == "Un hook bien plus court ici."
    assert [s.visual_prompt for s in result.scenes] == ["a toaster on fire"]


def test_approved_script_cannot_be_edited(session: Session) -> None:
    project, idea = setup(session)
    script = write_script(session, FakeLLM(script_response()), project, idea).script
    script.status = "approved"
    with pytest.raises(ValueError, match="validé"):
        update_script(session, script, {"hook": "x"})


def test_unsafe_script_is_refused(session: Session) -> None:
    project, idea = setup(session)
    raw = script_response()
    raw["body"] = "Ensuite on va tuer le voisin."
    with pytest.raises(LLMError, match="refusé"):
        write_script(session, FakeLLM(raw), project, idea)


def test_incomplete_script_is_refused(session: Session) -> None:
    project, idea = setup(session)
    with pytest.raises(LLMError, match="incomplet"):
        write_script(session, FakeLLM({"hook": "Salut", "scenes": []}), project, idea)


def test_hook_length_warnings(session: Session) -> None:
    project, idea = setup(session)
    script = write_script(session, FakeLLM(script_response()), project, idea).script
    script.hook = " ".join(["mot"] * 30)
    assert "maximum" in check_script(script)[0]
    script.hook = "Hop"
    assert "au moins" in check_script(script)[0]
