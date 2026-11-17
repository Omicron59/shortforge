"""Idees et script d'un projet."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from shortforge.deps import build_service, get_runtime, get_session
from shortforge.models import Idea, Project
from shortforge.pipeline import PipelineError, StepName, StepStatus
from shortforge.runtime import Runtime
from shortforge.schemas import (
    IdeaOut,
    RegeneratePayload,
    SceneOut,
    ScriptDetail,
    ScriptEdit,
    ScriptOut,
    ShortenPayload,
)
from shortforge.services import ideas as idea_service
from shortforge.services import scripts as script_service

router = APIRouter(prefix="/api/projects/{project_id}", tags=["contenu"])


def _detail(result: script_service.ScriptResult) -> ScriptDetail:
    return ScriptDetail(script=ScriptOut.model_validate(result.script),
                        scenes=[SceneOut.model_validate(s) for s in result.scenes], warnings=result.warnings)


def _editable(request: Request, session: Session, project_id: str) -> Project:
    service = build_service(request, session)
    project = service.get_project(project_id)
    if service.get_step(project_id, StepName.APPROVE_SCRIPT).status == StepStatus.DONE.value:
        raise PipelineError("Le script est validé : utilise « Refaire » sur l'écriture du script pour le changer.")
    return project


@router.get("/ideas", response_model=list[IdeaOut])
def list_ideas(project_id: str, session: Session = Depends(get_session)) -> list[IdeaOut]:
    rows = session.scalars(select(Idea).where(Idea.project_id == project_id).order_by(Idea.potential_score.desc()))
    return [IdeaOut.model_validate(i) for i in rows]


@router.post("/ideas/{idea_id}/select", response_model=IdeaOut)
def choose_idea(project_id: str, idea_id: str, request: Request, session: Session = Depends(get_session)) -> IdeaOut:
    service = build_service(request, session)
    if service.get_step(project_id, StepName.SELECT_IDEA).status == StepStatus.DONE.value:
        raise PipelineError("Une idée est déjà validée : utilise « Refaire » sur le choix de l'idée.")
    try:
        return IdeaOut.model_validate(idea_service.select_idea(session, project_id, idea_id))
    except ValueError as exc:
        raise PipelineError(str(exc)) from exc


@router.get("/script", response_model=ScriptDetail)
def get_script(project_id: str, session: Session = Depends(get_session)) -> ScriptDetail:
    script = script_service.current_script(session, project_id)
    if script is None:
        raise PipelineError("Aucun script pour ce projet.")
    return _detail(script_service.ScriptResult(script, script_service.scenes_of(session, script.id),
                                               script_service.check_script(script)))


@router.put("/script", response_model=ScriptDetail)
def edit_script(project_id: str, payload: ScriptEdit, request: Request,
                session: Session = Depends(get_session)) -> ScriptDetail:
    _editable(request, session, project_id)
    script = script_service.current_script(session, project_id)
    if script is None:
        raise PipelineError("Aucun script à modifier.")
    scenes = [s.model_dump() for s in payload.scenes] if payload.scenes is not None else None
    try:
        result = script_service.update_script(session, script, payload.model_dump(exclude={"scenes"}), scenes)
    except ValueError as exc:
        raise PipelineError(str(exc)) from exc
    return _detail(result)


@router.post("/script/shorten", response_model=ScriptDetail)
def shorten(project_id: str, payload: ShortenPayload, request: Request, session: Session = Depends(get_session),
            runtime: Runtime = Depends(get_runtime)) -> ScriptDetail:
    project = _editable(request, session, project_id)
    script = script_service.current_script(session, project_id)
    if script is None:
        raise PipelineError("Aucun script à raccourcir.")
    llm = runtime.llm_for("script")
    return _detail(script_service.shorten_script(session, llm, project, script, payload.target_duration_s))


@router.post("/script/regenerate", response_model=ScriptDetail)
def regenerate(project_id: str, payload: RegeneratePayload, request: Request,
               session: Session = Depends(get_session), runtime: Runtime = Depends(get_runtime)) -> ScriptDetail:
    project = _editable(request, session, project_id)
    idea = idea_service.selected_idea(session, project_id)
    if idea is None:
        raise PipelineError("Choisis d'abord une idée.")
    llm = runtime.llm_for("script")
    return _detail(script_service.write_script(session, llm, project, idea, instructions=payload.instructions))


class RevisePayload(BaseModel):
    instruction: str = Field(min_length=3, max_length=2000)


@router.post("/script/revise", response_model=ScriptDetail)
def revise(project_id: str, payload: RevisePayload, request: Request, session: Session = Depends(get_session),
           runtime: Runtime = Depends(get_runtime)) -> ScriptDetail:
    """Correction en langage naturel du script actuel (nouvelle version)."""
    project = _editable(request, session, project_id)
    script = script_service.current_script(session, project_id)
    if script is None:
        raise PipelineError("Aucun script à corriger.")
    llm = runtime.llm_for("script")
    return _detail(script_service.revise_script(session, llm, project, script, payload.instruction))
