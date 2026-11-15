"""ComfyUI : etat du serveur local et workflows."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from shortforge.deps import get_runtime, get_session
from shortforge.integrations.comfyui import ComfyUIError, WorkflowSpec
from shortforge.runtime import Runtime
from shortforge.schemas import WorkflowIn, WorkflowOut
from shortforge.services.app_settings import get_value, set_value

router = APIRouter(prefix="/api/comfyui", tags=["comfyui"])


def _out(spec: WorkflowSpec) -> WorkflowOut:
    return WorkflowOut(id=spec.id, name=spec.name, kind=spec.kind, inputs=sorted(spec.inputs), user=spec.user)


@router.get("/status")
def status(runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return {"url": runtime.comfy.base_url, "running": runtime.comfy.is_running()}


def _workflow_checkpoints(runtime: Runtime, workflow_id: str) -> list[str]:
    try:
        workflow, _ = runtime.library.load(workflow_id)
    except ComfyUIError:
        return []
    return [str(node.get("inputs", {}).get("ckpt_name")) for node in workflow.values()
            if isinstance(node, dict) and node.get("class_type") == "CheckpointLoaderSimple"]


@router.get("/check")
def check(session: Session = Depends(get_session), runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    """Teste ComfyUI (avec recherche du port) et les modeles d'image installes."""
    before = runtime.comfy.base_url
    url = runtime.comfy.detect()
    image_workflow = get_value(session, "comfyui_image_workflow", runtime.settings.comfyui_image_workflow)
    chosen = get_value(session, "comfyui_checkpoint") or ""
    expected = chosen or next(iter(_workflow_checkpoints(runtime, image_workflow)), "")
    installed = runtime.comfy.checkpoints() if url else []
    if url is None:
        message = ("ComfyUI ne répond pas (essayé : " + ", ".join(dict.fromkeys([before, *runtime.comfy.candidates]))
                   + "). Lance Comfy Desktop puis teste à nouveau.")
    elif not installed:
        message = "ComfyUI répond, mais aucun modèle d'image n'est installé : ajoute un checkpoint dans ComfyUI."
    elif expected and expected not in installed:
        message = f"ComfyUI répond, mais le modèle « {expected} » est absent : choisis un modèle installé."
    else:
        message = "ComfyUI est prêt."
    return {"running": url is not None, "url": runtime.comfy.base_url, "switched": url is not None and url != before,
            "checkpoints": installed, "expected_checkpoint": expected, "chosen_checkpoint": chosen,
            "ready": bool(url and installed and (not expected or expected in installed)), "message": message}


class ComfySettings(BaseModel):
    url: str | None = Field(default=None, pattern=r"^https?://[^\s/]+(:\d+)?/?$")
    checkpoint: str | None = Field(default=None, max_length=300)


@router.put("/settings")
def set_comfy(payload: ComfySettings, session: Session = Depends(get_session),
              runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    """Adresse de ComfyUI (vide = detection automatique) et modele d'image a utiliser."""
    if payload.url is not None:
        url = payload.url.strip().rstrip("/")
        set_value(session, "comfyui_url", url)
        runtime.comfy.set_base_url(url or runtime.settings.comfyui_url)
    if payload.checkpoint is not None:
        set_value(session, "comfyui_checkpoint", payload.checkpoint.strip())
    return check(session, runtime)


@router.get("/workflows", response_model=list[WorkflowOut])
def list_workflows(runtime: Runtime = Depends(get_runtime)) -> list[WorkflowOut]:
    return [_out(s) for s in runtime.library.list()]


@router.post("/workflows", response_model=WorkflowOut, status_code=201)
def add_workflow(payload: WorkflowIn, runtime: Runtime = Depends(get_runtime)) -> WorkflowOut:
    spec = runtime.library.add(payload.id, payload.workflow, name=payload.name, kind=payload.kind,
                               inputs=payload.inputs)
    return _out(spec)
