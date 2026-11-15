from __future__ import annotations

from typing import Any

import pytest

from shortforge.config import Settings
from shortforge.db import Database
from shortforge.pipeline import (
    PIPELINE,
    HandlerRegistry,
    PipelineError,
    PipelineService,
    StepName,
    StepStatus,
)
from shortforge.pipeline.engine import INTERRUPTED_MESSAGE, InvalidTransitionError, StepNotAvailableError
from shortforge.pipeline.handlers import StepContext
from shortforge.pipeline.steps import can_transition


def status_of(service: PipelineService, project_id: str, name: StepName) -> str:
    return service.get_step(project_id, name).status


def run_until(service: PipelineService, project_id: str, target: StepName) -> None:
    """Avance (et valide les etapes humaines) jusqu'a ce que `target` soit la prochaine etape."""
    while (nxt := service.next_step(project_id)) is not None and nxt.name != target.value:
        if nxt.status == StepStatus.NEEDS_VALIDATION.value:
            service.approve(project_id, nxt.name, actor="utilisateur")
        else:
            service.advance(project_id)


def test_pipeline_has_15_ordered_steps() -> None:
    assert [d.name.value for d in PIPELINE] == [
        "generate_ideas", "select_idea", "write_script", "approve_script", "create_storyboard",
        "generate_images", "generate_videos", "generate_voice", "create_subtitles", "select_music",
        "render_video", "review_preview", "approve_final_render", "create_youtube_draft", "publish",
    ]


def test_new_project_has_all_steps_pending(service: PipelineService) -> None:
    project = service.create_project("Mon premier Short", niche="humour")
    assert [s.status for s in project.steps] == ["pending"] * 15
    assert project.current_step == "generate_ideas"
    assert project.status == "draft"


def test_empty_title_is_refused(service: PipelineService) -> None:
    with pytest.raises(PipelineError):
        service.create_project("   ")


def test_auto_step_runs_and_saves_output(service: PipelineService) -> None:
    project = service.create_project("Short")
    step = service.advance(project.id)
    assert step.name == "generate_ideas"
    assert step.status == "done"
    assert step.output == {"step": "generate_ideas"}
    assert step.attempts == 1
    assert project.status == "in_progress"
    assert project.current_step == "select_idea"


def test_human_gate_waits_for_validation(service: PipelineService) -> None:
    project = service.create_project("Short")
    service.advance(project.id)
    gate = service.advance(project.id)
    assert gate.name == "select_idea" and gate.status == "needs_validation"
    with pytest.raises(InvalidTransitionError):
        service.advance(project.id)
    service.approve(project.id, StepName.SELECT_IDEA, actor="utilisateur")
    assert status_of(service, project.id, StepName.SELECT_IDEA) == "done"
    assert service.get_step(project.id, StepName.SELECT_IDEA).validated_by == "utilisateur"


@pytest.mark.parametrize("actor", ["", "system", "auto", "agent", "IA"])
def test_validation_requires_a_human(service: PipelineService, actor: str) -> None:
    project = service.create_project("Short")
    service.advance(project.id)
    service.advance(project.id)
    with pytest.raises(PipelineError):
        service.approve(project.id, StepName.SELECT_IDEA, actor=actor)


def test_cannot_approve_step_that_is_not_waiting(service: PipelineService) -> None:
    project = service.create_project("Short")
    with pytest.raises(InvalidTransitionError):
        service.approve(project.id, StepName.APPROVE_SCRIPT, actor="utilisateur")


def test_failed_handler_is_recorded_and_retried(session: Any, settings: Settings) -> None:
    calls = {"n": 0}

    def flaky(ctx: StepContext) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Ollama ne répond pas")
        return {"ok": True}

    registry = HandlerRegistry()
    registry.register(StepName.GENERATE_IDEAS, flaky)
    service = PipelineService(session, settings, registry)
    project = service.create_project("Short")
    step = service.advance(project.id)
    assert step.status == "failed" and step.error == "Ollama ne répond pas"
    step = service.advance(project.id)
    assert step.status == "done" and step.attempts == 2 and step.error is None


def test_missing_handler_is_reported(session: Any, settings: Settings) -> None:
    service = PipelineService(session, settings, HandlerRegistry())
    project = service.create_project("Short")
    with pytest.raises(StepNotAvailableError):
        service.advance(project.id)
    assert status_of(service, project.id, StepName.GENERATE_IDEAS) == "pending"


def test_reject_script_relaunches_writing(service: PipelineService) -> None:
    project = service.create_project("Short")
    run_until(service, project.id, StepName.APPROVE_SCRIPT)
    service.advance(project.id)
    origin = service.reject(project.id, StepName.APPROVE_SCRIPT, reason="trop long")
    assert origin.name == "write_script" and origin.status == "pending"
    assert origin.error == "Refusé : trop long"
    assert status_of(service, project.id, StepName.APPROVE_SCRIPT) == "pending"
    assert status_of(service, project.id, StepName.SELECT_IDEA) == "done"


def test_redo_resets_step_and_following(service: PipelineService) -> None:
    project = service.create_project("Short")
    run_until(service, project.id, StepName.CREATE_STORYBOARD)
    service.redo(project.id, StepName.SELECT_IDEA)
    steps = service.steps(project.id)
    assert steps[0].status == "done"
    assert all(s.status == "pending" and s.validated_by is None for s in steps[1:])
    assert project.current_step == "select_idea"


def test_cancel_then_resume(service: PipelineService) -> None:
    project = service.create_project("Short")
    service.advance(project.id)
    service.cancel(project.id)
    assert project.status == "cancelled"
    with pytest.raises(InvalidTransitionError):
        service.advance(project.id)
    nxt = service.resume(project.id)
    assert nxt is not None and nxt.name == "select_idea" and nxt.status == "pending"
    assert project.status == "in_progress"


def test_interrupted_project_resumes_after_restart(settings: Settings, registry: HandlerRegistry) -> None:
    """Simule un plantage pendant une etape : apres redemarrage, l'etape est relancable."""
    db = Database(settings.database_url)
    db.create_all()
    with db.session() as s:
        service = PipelineService(s, settings, registry)
        project = service.create_project("Short")
        service.advance(project.id)
        step = service.get_step(project.id, StepName.SELECT_IDEA)
        step.status = StepStatus.RUNNING.value  # etat laisse par un plantage
        project_id = project.id
    db.engine.dispose()

    db2 = Database(settings.database_url)
    with db2.session() as s:
        service = PipelineService(s, settings, registry)
        assert service.recover_interrupted() == 1
        step = service.get_step(project_id, StepName.SELECT_IDEA)
        assert step.status == "pending" and step.error == INTERRUPTED_MESSAGE
        assert status_of(service, project_id, StepName.GENERATE_IDEAS) == "done"
    db2.engine.dispose()


def test_full_pipeline_stops_before_publish_when_disabled(service: PipelineService) -> None:
    project = service.create_project("Short")
    run_until(service, project.id, StepName.PUBLISH)
    gate = service.advance(project.id)
    assert gate.name == "publish" and gate.status == "needs_validation"
    with pytest.raises(PermissionError):
        service.approve(project.id, StepName.PUBLISH, actor="utilisateur", confirmed=True)
    assert project.status == "in_progress"


def test_full_pipeline_publishes_only_with_flag_and_confirmation(session: Any, tmp_path: Any,
                                                                 registry: HandlerRegistry) -> None:
    settings = Settings(_env_file=None, shortforge_data_dir=tmp_path,  # type: ignore[call-arg]
                        youtube_publish_enabled=True)
    service = PipelineService(session, settings, registry)
    project = service.create_project("Short")
    run_until(service, project.id, StepName.PUBLISH)
    service.advance(project.id)
    with pytest.raises(PermissionError):
        service.approve(project.id, StepName.PUBLISH, actor="utilisateur", confirmed=False)
    service.approve(project.id, StepName.PUBLISH, actor="utilisateur", confirmed=True)
    assert project.status == "done" and project.current_step is None


def test_transition_table() -> None:
    assert can_transition(StepStatus.PENDING, StepStatus.RUNNING)
    assert not can_transition(StepStatus.DONE, StepStatus.RUNNING)
    assert not can_transition(StepStatus.PENDING, StepStatus.DONE)
