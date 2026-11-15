"""Parcours complet avec les vraies etapes : idees -> script -> scenes -> images -> videos."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.models import Asset, Cost, ProviderJob
from shortforge.pipeline import PipelineError, PipelineService, StepName
from shortforge.pipeline.default_handlers import build_handlers
from shortforge.runtime import Runtime
from shortforge.services.app_settings import set_budget_limits
from shortforge.services.ideas import select_idea
from shortforge.services.production import scene_asset
from shortforge.services.scripts import current_script, scenes_of
from tests.fakes import FakeComfyServer, FakeGoogleApi, FakeLLM, add_video_workflow, ideas_response, make_runtime


def make(session: Session, tmp_path: Path, *, comfy: FakeComfyServer | None = None,
         google: FakeGoogleApi | None = None) -> tuple[PipelineService, Runtime, str]:
    settings = Settings(_env_file=None, shortforge_data_dir=tmp_path,  # type: ignore[call-arg]
                        gemini_api_key="cle-test")
    runtime = make_runtime(settings, FakeLLM(ideas_response("Le grille-pain qui chante"), script_response_two()),
                           comfy=comfy, provider_handler=(google or FakeGoogleApi()).handler)
    add_video_workflow(runtime.library, "comfyui_local")
    service = PipelineService(session, settings, build_handlers(runtime))
    project = service.create_project("Grille-pain", niche="humour", video_mode="standard")
    return service, runtime, project.id


def script_response_two() -> dict:
    from tests.fakes import script_response

    return script_response(("simple", "important"))


def run_to_videos(service: PipelineService, session: Session, project_id: str) -> None:
    service.advance(project_id)  # generate_ideas
    assert service.advance(project_id).status == "needs_validation"  # select_idea
    with pytest.raises(PipelineError, match="Choisis d'abord"):
        service.approve(project_id, StepName.SELECT_IDEA, actor="utilisateur")
    idea_id = service.get_step(project_id, StepName.GENERATE_IDEAS).output["idea_ids"][0]  # type: ignore[index]
    select_idea(session, project_id, idea_id)
    service.approve(project_id, StepName.SELECT_IDEA, actor="utilisateur")
    assert service.advance(project_id).status == "done"  # write_script
    service.advance(project_id)  # approve_script -> needs_validation
    service.approve(project_id, StepName.APPROVE_SCRIPT, actor="utilisateur")
    storyboard = service.advance(project_id)
    assert storyboard.status == "done", storyboard.error
    images = service.advance(project_id)
    assert images.status == "done", images.error


def test_full_production_with_paid_confirmation(session: Session, tmp_path: Path) -> None:
    google = FakeGoogleApi()
    service, _, project_id = make(session, tmp_path, google=google)
    run_to_videos(service, session, project_id)

    script = current_script(session, project_id)
    assert script is not None and script.status == "approved"
    scenes = scenes_of(session, script.id)
    assert [s.provider_id for s in scenes] == ["comfyui_local", "gemini_omni_12_flash"]
    assert all(scene_asset(session, s.id, "image") for s in scenes)

    # 1er passage : la scene payante demande une confirmation, rien n'est depense
    videos = service.advance(project_id)
    assert videos.status == "needs_validation"
    item = videos.output["confirmation_required"][0]  # type: ignore[index]
    assert item["message"] == ("Cette scène utilisera Gemini Omni 1.2 Flash.\nDurée : 5 secondes.\n"
                               "Coût estimé : 0,35 dollar.\nConfirmer la génération ?")
    assert google.submitted == []

    with pytest.raises(PipelineError, match="confirm"):
        service.approve(project_id, StepName.GENERATE_VIDEOS, actor="utilisateur")
    confirmed = service.approve(project_id, StepName.GENERATE_VIDEOS, actor="utilisateur", confirmed=True)
    assert confirmed.status == "pending"

    # 2e passage : generation reelle, cout enregistre, confirmation consommee
    videos = service.advance(project_id)
    assert videos.status == "done", videos.error
    assert videos.output == {"videos_generated": 2, "spent_usd": 0.35}
    assert len(google.submitted) == 1 and "image" in google.submitted[0]["instances"][0]
    actual = session.scalars(select(Cost).where(Cost.kind == "actual")).all()
    assert [c.amount_usd for c in actual] == [0.35]
    confirmation = session.scalars(select(Cost).where(Cost.kind == "confirmation")).one()
    assert confirmation.provider_job_id is not None
    jobs = session.scalars(select(ProviderJob)).all()
    assert {j.status for j in jobs} == {"succeeded"} and len(jobs) == 2
    assert len(session.scalars(select(Asset).where(Asset.kind == "video")).all()) == 2
    assert service.next_step(project_id).name == "generate_voice"  # type: ignore[union-attr]


def test_refusing_the_expense_keeps_the_step_pending(session: Session, tmp_path: Path) -> None:
    service, _, project_id = make(session, tmp_path)
    run_to_videos(service, session, project_id)
    service.advance(project_id)
    step = service.reject(project_id, StepName.GENERATE_VIDEOS)
    assert step.status == "pending" and "Dépense refusée" in (step.error or "")


def test_confirmation_is_refused_when_budget_was_lowered(session: Session, tmp_path: Path) -> None:
    service, _, project_id = make(session, tmp_path)
    run_to_videos(service, session, project_id)
    service.advance(project_id)
    set_budget_limits(session, {"budget_max_per_scene": 0.1})
    with pytest.raises(PipelineError, match="Budget dépassé"):
        service.approve(project_id, StepName.GENERATE_VIDEOS, actor="utilisateur", confirmed=True)
    assert session.scalars(select(Cost)).all() == []


def test_failed_image_generation_resumes_only_missing_scenes(session: Session, tmp_path: Path) -> None:
    comfy = FakeComfyServer()
    service, _, project_id = make(session, tmp_path, comfy=comfy)
    service.advance(project_id)
    idea_id = service.get_step(project_id, StepName.GENERATE_IDEAS).output["idea_ids"][0]  # type: ignore[index]
    service.advance(project_id)
    select_idea(session, project_id, idea_id)
    service.approve(project_id, StepName.SELECT_IDEA, actor="utilisateur")
    service.advance(project_id)
    service.advance(project_id)
    service.approve(project_id, StepName.APPROVE_SCRIPT, actor="utilisateur")
    service.advance(project_id)

    comfy.fail = True
    failed = service.advance(project_id)
    assert failed.status == "failed" and "CUDA out of memory" in (failed.error or "")
    comfy.fail = False
    assert service.advance(project_id).status == "done"
    assert len(comfy.queued) == 3  # 1 echec + 2 scenes


def test_missing_image_workflow_fails_with_clear_message(session: Session, tmp_path: Path) -> None:
    service, runtime, project_id = make(session, tmp_path)
    runtime.settings.comfyui_image_workflow = "absent"
    service.advance(project_id)
    idea_id = service.get_step(project_id, StepName.GENERATE_IDEAS).output["idea_ids"][0]  # type: ignore[index]
    service.advance(project_id)
    select_idea(session, project_id, idea_id)
    service.approve(project_id, StepName.SELECT_IDEA, actor="utilisateur")
    service.advance(project_id)
    service.advance(project_id)
    service.approve(project_id, StepName.APPROVE_SCRIPT, actor="utilisateur")
    service.advance(project_id)
    step = service.advance(project_id)
    assert step.status == "failed" and "« absent » introuvable" in (step.error or "")
