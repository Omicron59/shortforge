"""Scenes, choix des moteurs, estimation des couts et regeneration."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from shortforge.deps import build_service, get_runtime, get_session
from shortforge.models import Provider, Scene
from shortforge.pipeline import PipelineError, StepName
from shortforge.runtime import Runtime
from shortforge.schemas import EngineSettings, ProjectOut, SceneOut, ScenePatch, SceneRegenerate
from shortforge.services import production as production_service
from shortforge.services.budget import BudgetService
from shortforge.services.engine_selection import scene_request
from shortforge.services.scripts import TRANSITIONS

router = APIRouter(prefix="/api", tags=["production"])


def _scene(session: Session, scene_id: str) -> Scene:
    scene = session.get(Scene, scene_id)
    if scene is None:
        raise PipelineError("Scène introuvable.")
    return scene


@router.get("/projects/{project_id}/scenes", response_model=list[SceneOut])
def list_scenes(project_id: str, session: Session = Depends(get_session)) -> list[SceneOut]:
    try:
        scenes = production_service.project_scenes(session, project_id)
    except production_service.ProductionError:
        return []
    return [SceneOut.model_validate(s) for s in scenes]


@router.patch("/scenes/{scene_id}", response_model=SceneOut)
def patch_scene(scene_id: str, payload: ScenePatch, session: Session = Depends(get_session)) -> SceneOut:
    scene = _scene(session, scene_id)
    if payload.provider_id is not None:
        if payload.provider_id == "":
            scene.provider_locked = False
        else:
            if session.get(Provider, payload.provider_id) is None:
                raise PipelineError(f"Moteur vidéo inconnu : {payload.provider_id}.")
            scene.provider_id, scene.provider_locked = payload.provider_id, True
            scene.provider_reason = "choisi à la main pour cette scène"
    for field in ("importance", "visual_prompt", "negative_prompt", "duration_s"):
        value = getattr(payload, field)
        if value is not None:
            setattr(scene, field, value)
    if payload.transition is not None:
        if payload.transition not in TRANSITIONS:
            raise PipelineError(f"Transition inconnue : {payload.transition}.")
        scene.transition = payload.transition
    session.flush()
    return SceneOut.model_validate(scene)


@router.post("/scenes/{scene_id}/regenerate", response_model=SceneOut)
def regenerate_scene(scene_id: str, payload: SceneRegenerate, request: Request,
                     session: Session = Depends(get_session)) -> SceneOut:
    scene = _scene(session, scene_id)
    service = build_service(request, session)
    step = StepName.GENERATE_IMAGES if payload.target == "image" else StepName.GENERATE_VIDEOS
    service.redo(scene.project_id, step)
    production_service.reset_scene(session, scene, payload.target)
    return SceneOut.model_validate(scene)


@router.get("/projects/{project_id}/cost-estimate")
def cost_estimate(project_id: str, request: Request, session: Session = Depends(get_session),
                  runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    registry = runtime.providers(session)
    project = build_service(request, session).get_project(project_id)
    scenes = []
    total = 0.0
    for scene in production_service.project_scenes(session, project.id):
        provider = registry.get(scene.provider_id or "comfyui_local")
        cost = provider.estimate_cost(scene_request(scene))
        total += cost or 0
        scenes.append({"scene_id": scene.id, "position": scene.position, "provider": provider.name,
                       "duration_s": scene.duration_s, "estimated_cost_usd": cost})
    return {"scenes": scenes, "estimated_total_usd": round(total, 4),
            "pending_confirmations": production_service.pending_confirmations(session, runtime, project),
            "budget": BudgetService(session, runtime.settings).summary()}


@router.put("/projects/{project_id}/engine", response_model=ProjectOut)
def set_engine(project_id: str, payload: EngineSettings, request: Request,
               session: Session = Depends(get_session)) -> ProjectOut:
    project = build_service(request, session).get_project(project_id)
    if payload.default_provider is not None:
        if session.get(Provider, payload.default_provider) is None:
            raise PipelineError(f"Moteur vidéo inconnu : {payload.default_provider}.")
        project.default_provider = payload.default_provider
    if payload.video_mode is not None:
        project.video_mode = payload.video_mode
    if payload.engine_scope is not None:
        project.engine_scope = payload.engine_scope
    session.flush()
    return ProjectOut.model_validate(project)
