"""ComfyUI : etat du serveur local et workflows."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from shortforge.deps import get_runtime
from shortforge.integrations.comfyui import WorkflowSpec
from shortforge.runtime import Runtime
from shortforge.schemas import WorkflowIn, WorkflowOut

router = APIRouter(prefix="/api/comfyui", tags=["comfyui"])


def _out(spec: WorkflowSpec) -> WorkflowOut:
    return WorkflowOut(id=spec.id, name=spec.name, kind=spec.kind, inputs=sorted(spec.inputs), user=spec.user)


@router.get("/status")
def status(runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return {"url": runtime.comfy.base_url, "running": runtime.comfy.is_running()}


@router.get("/workflows", response_model=list[WorkflowOut])
def list_workflows(runtime: Runtime = Depends(get_runtime)) -> list[WorkflowOut]:
    return [_out(s) for s in runtime.library.list()]


@router.post("/workflows", response_model=WorkflowOut, status_code=201)
def add_workflow(payload: WorkflowIn, runtime: Runtime = Depends(get_runtime)) -> WorkflowOut:
    spec = runtime.library.add(payload.id, payload.workflow, name=payload.name, kind=payload.kind,
                               inputs=payload.inputs)
    return _out(spec)
