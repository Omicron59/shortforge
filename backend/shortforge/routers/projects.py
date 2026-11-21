"""Projets et pilotage de leur pipeline."""

from __future__ import annotations

import asyncio
import json
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from shortforge.deps import build_service, get_session
from shortforge.models import PipelineStep, Project
from shortforge.pipeline import PipelineError
from shortforge.pipeline.steps import DEFINITIONS, StepName
from shortforge.schemas import (
    ApprovePayload,
    ProjectCreate,
    ProjectDetail,
    ProjectOut,
    RejectPayload,
    StepOut,
)
from shortforge.services import projects as project_service

router = APIRouter(prefix="/api/projects", tags=["projets"])


def step_out(step: PipelineStep) -> StepOut:
    definition = DEFINITIONS[StepName(step.name)]
    out = StepOut.model_validate(step)
    out.label, out.human_gate = definition.label, definition.human_gate
    return out


def detail(project: Project) -> ProjectDetail:
    base = ProjectOut.model_validate(project).model_dump()
    return ProjectDetail(**base, steps=[step_out(s) for s in project.steps])


@router.post("", response_model=ProjectDetail, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, request: Request, session: Session = Depends(get_session)) -> ProjectDetail:
    project = build_service(request, session).create_project(
        payload.title, niche=payload.niche, language=payload.language, video_mode=payload.video_mode
    )
    return detail(project)


@router.get("", response_model=list[ProjectOut])
def list_projects(request: Request, archived: bool = Query(default=False),
                  session: Session = Depends(get_session)) -> list[ProjectOut]:
    return [ProjectOut.model_validate(p) for p in build_service(request, session).list_projects(archived=archived)]


@router.get("/{project_id}/footprint")
def project_footprint(project_id: str, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Espace disque et medias du projet, a afficher avant une suppression."""
    project = build_service(request, session).get_project(project_id)
    return project_service.footprint(session, request.app.state.settings.shortforge_data_dir, project)


@router.post("/{project_id}/archive", response_model=ProjectOut)
def archive_project(project_id: str, request: Request, session: Session = Depends(get_session)) -> ProjectOut:
    project = build_service(request, session).get_project(project_id)
    return ProjectOut.model_validate(project_service.archive(session, project))


@router.post("/{project_id}/unarchive", response_model=ProjectOut)
def unarchive_project(project_id: str, request: Request, session: Session = Depends(get_session)) -> ProjectOut:
    project = build_service(request, session).get_project(project_id)
    return ProjectOut.model_validate(project_service.unarchive(session, project))


@router.delete("/{project_id}")
def delete_project(project_id: str, request: Request, confirm: bool = Query(default=False),
                   session: Session = Depends(get_session)) -> dict[str, Any]:
    """Suppression definitive : exige `confirm=true`, envoye seulement apres l'accord explicite dans l'interface."""
    project = build_service(request, session).get_project(project_id)
    if not confirm:
        raise PipelineError("Confirme la suppression définitive (confirm=true).")
    try:
        report = project_service.delete_project(session, request.app.state.settings.shortforge_data_dir, project,
                                                running=request.app.state.runner.is_running(project_id))
    except project_service.ProjectDeletionError as exc:
        raise PipelineError(str(exc)) from exc
    return {"deleted": True, "title": report.title, "freed_bytes": report.freed_bytes, "leftover": report.leftover}


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: str, request: Request, session: Session = Depends(get_session)) -> ProjectDetail:
    return detail(build_service(request, session).get_project(project_id))


@router.post("/{project_id}/pipeline/advance", response_model=StepOut,
             responses={202: {"description": "Étape lancée en arrière-plan"}})
def advance(project_id: str, request: Request, background: bool = Query(default=False),
            session: Session = Depends(get_session)) -> StepOut | JSONResponse:
    """Lance l'etape suivante. `background=true` : l'etape tourne en arriere-plan (suivi par WebSocket)."""
    if not background:
        return step_out(build_service(request, session).advance(project_id))
    build_service(request, session).get_project(project_id)
    if not request.app.state.runner.submit(project_id):
        raise PipelineError("Une étape de ce projet est déjà en cours.")
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content={"detail": "Étape lancée.",
                                                                       "project_id": project_id})


@router.post("/{project_id}/steps/{step}/approve", response_model=StepOut)
def approve(project_id: str, step: str, payload: ApprovePayload, request: Request,
            session: Session = Depends(get_session)) -> StepOut:
    service = build_service(request, session)
    return step_out(service.approve(project_id, step, actor=payload.validated_by, confirmed=payload.confirm))


@router.post("/{project_id}/steps/{step}/reject", response_model=StepOut)
def reject(project_id: str, step: str, payload: RejectPayload, request: Request,
           session: Session = Depends(get_session)) -> StepOut:
    return step_out(build_service(request, session).reject(project_id, step, reason=payload.reason))


@router.post("/{project_id}/steps/{step}/redo", response_model=StepOut)
def redo(project_id: str, step: str, request: Request, session: Session = Depends(get_session)) -> StepOut:
    return step_out(build_service(request, session).redo(project_id, step))


@router.post("/{project_id}/pipeline/cancel", response_model=ProjectOut)
def cancel(project_id: str, request: Request, session: Session = Depends(get_session)) -> ProjectOut:
    return ProjectOut.model_validate(build_service(request, session).cancel(project_id))


@router.post("/{project_id}/pipeline/resume", response_model=ProjectDetail)
def resume(project_id: str, request: Request, session: Session = Depends(get_session)) -> ProjectDetail:
    service = build_service(request, session)
    service.resume(project_id)
    return detail(service.get_project(project_id))


@router.websocket("/{project_id}/events")
async def project_events(websocket: WebSocket, project_id: str) -> None:
    """Envoie l'etat du pipeline a chaque changement (progression en direct pour l'interface)."""
    expected = websocket.app.state.api_token
    if expected and not secrets.compare_digest(websocket.query_params.get("token", "").encode(), expected.encode()):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    db = websocket.app.state.db
    last = ""
    try:
        while True:
            with db.session() as session:
                project = session.get(Project, project_id)
                if project is None:
                    await websocket.send_json({"error": "Projet introuvable."})
                    await websocket.close()
                    return
                payload = detail(project).model_dump(mode="json")
            snapshot = json.dumps(payload, sort_keys=True)
            if snapshot != last:
                await websocket.send_json(payload)
                last = snapshot
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return
