"""Production des scenes : decoupage (choix des moteurs), images ComfyUI et videos.

Chaque scene garde son propre statut : si une generation echoue ou si l'application est
fermee, seules les scenes non terminees sont refaites a la reprise.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from shortforge.integrations.comfyui import apply_inputs
from shortforge.models import Asset, Project, ProviderJob, Scene, Script
from shortforge.pipeline.handlers import ConfirmationRequired
from shortforge.providers.base import JobState, Operation, ProviderError, VideoRequest
from shortforge.runtime import Runtime
from shortforge.services.app_settings import get_value
from shortforge.services.budget import BudgetService, confirmation_message, format_usd
from shortforge.services.engine_selection import FALLBACK, plan_scenes
from shortforge.services.scripts import current_script, scenes_of


class ProductionError(RuntimeError):
    """Erreur de production ; le message est destine a l'utilisateur."""


def approved_script(session: Session, project_id: str) -> Script:
    script = current_script(session, project_id)
    if script is None:
        raise ProductionError("Aucun script pour ce projet.")
    return script


def project_scenes(session: Session, project_id: str) -> list[Scene]:
    scenes = scenes_of(session, approved_script(session, project_id).id)
    if not scenes:
        raise ProductionError("Le script n'a aucune scène.")
    return scenes


def scene_asset(session: Session, scene_id: str, kind: str) -> Asset | None:
    return session.scalars(select(Asset).where(Asset.scene_id == scene_id, Asset.kind == kind)
                           .order_by(Asset.created_at.desc())).first()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _new_asset(session: Session, project_id: str, scene_id: str, kind: str, path: Path, mime: str) -> Asset:
    asset = Asset(project_id=project_id, scene_id=scene_id, kind=kind, path=str(path), mime_type=mime,
                  origin="generated", rights_confirmed=True, license="généré par l'utilisateur",
                  sha256=_sha256(path))
    session.add(asset)
    session.flush()
    return asset


# ── Etape create_storyboard ──


def create_storyboard(session: Session, runtime: Runtime, project: Project) -> dict[str, Any]:
    scenes = project_scenes(session, project.id)
    budget = BudgetService(session, runtime.settings)
    choices = plan_scenes(session, project, scenes, runtime.providers(session), budget)
    total = sum(c.estimated_cost_usd or 0 for c in choices)
    return {"scenes": [{"position": c.position, "provider": c.provider_id, "reason": c.reason,
                        "estimated_cost_usd": c.estimated_cost_usd} for c in choices],
            "estimated_total_usd": round(total, 4)}


# ── Etape generate_images ──


def generate_images(session: Session, runtime: Runtime, project: Project) -> dict[str, Any]:
    workflow_id = str(get_value(session, "comfyui_image_workflow", runtime.settings.comfyui_image_workflow))
    workflow, spec = runtime.library.load(workflow_id)
    out_dir = runtime.project_dir(project.id) / "images"
    done = 0
    for scene in project_scenes(session, project.id):
        if scene.image_status == "done" and scene_asset(session, scene.id, "image"):
            done += 1
            continue
        if scene.seed is None:
            scene.seed = random.randint(0, 2**31 - 1)
        filled = apply_inputs(workflow, spec, {
            "prompt": scene.visual_prompt, "negative_prompt": scene.negative_prompt, "seed": scene.seed,
            "width": runtime.settings.image_width, "height": runtime.settings.image_height,
        })
        scene.image_status = "running"
        session.flush()
        try:
            paths = runtime.comfy.run(filled, out_dir / f"scene_{scene.position:02d}")
        except Exception:
            scene.image_status = "failed"
            session.flush()
            raise
        _new_asset(session, project.id, scene.id, "image", paths[0], "image/png")
        scene.image_status = "done"
        session.flush()
        done += 1
    return {"images": done, "workflow": workflow_id}


# ── Etape generate_videos ──


def pending_confirmations(session: Session, runtime: Runtime, project: Project) -> list[dict[str, Any]]:
    """Scenes payantes pas encore confirmees, avec le message a afficher."""
    budget = BudgetService(session, runtime.settings)
    registry = runtime.providers(session)
    items = []
    for scene in project_scenes(session, project.id):
        if scene.status == "done" or not scene.provider_id:
            continue
        provider = registry.get(scene.provider_id)
        amount = provider.estimate_cost(_request(session, scene))
        if provider.kind == "local" or (amount is not None and amount <= 0):
            continue
        if amount is not None and budget.open_confirmation(scene.id, provider.id, amount):
            continue
        items.append({"scene_id": scene.id, "position": scene.position, "provider_id": provider.id,
                      "provider": provider.name, "duration_s": scene.duration_s, "estimated_cost_usd": amount,
                      "message": confirmation_message(provider.name, scene.duration_s, amount)
                      if amount is not None else f"Tarif de {provider.name} non configuré : génération bloquée."})
    return items


def confirm_costs(session: Session, runtime: Runtime, project: Project) -> list[str]:
    """Validation humaine : enregistre les confirmations, apres un dernier controle du budget."""
    budget = BudgetService(session, runtime.settings)
    items = pending_confirmations(session, runtime, project)
    pending = 0.0
    blocked = []
    for item in items:
        amount = item["estimated_cost_usd"]
        decision = budget.check(amount, project_id=project.id, provider_name=item["provider"], pending_usd=pending)
        if not decision.allowed:
            blocked.append(f"scène {item['position'] + 1} : {'; '.join(decision.reasons)}")
            continue
        pending += amount
    if blocked:
        raise ProductionError("Budget dépassé, rien n'a été confirmé : " + " ; ".join(blocked)
                              + ". Choisis un moteur local pour ces scènes ou augmente le budget.")
    for item in items:
        budget.confirm(project_id=project.id, scene_id=item["scene_id"], provider_id=item["provider_id"],
                       amount=item["estimated_cost_usd"],
                       description=f"{item['provider']} : {format_usd(item['estimated_cost_usd'])}")
    return [i["scene_id"] for i in items]


def generate_videos(session: Session, runtime: Runtime, project: Project) -> dict[str, Any]:
    items = pending_confirmations(session, runtime, project)
    if items:
        total = sum(i["estimated_cost_usd"] or 0 for i in items)
        raise ConfirmationRequired(f"{len(items)} scène(s) payante(s) à confirmer ({format_usd(total)}).", items)

    budget = BudgetService(session, runtime.settings)
    registry = runtime.providers(session)
    spent, generated = 0.0, 0
    for scene in project_scenes(session, project.id):
        if scene.status == "done" and scene_asset(session, scene.id, "video"):
            continue
        provider = registry.get(scene.provider_id or FALLBACK)
        request = _request(session, scene)
        operation = Operation.IMAGE if request.image_path and Operation.IMAGE in provider.operations else Operation.TEXT
        if operation is Operation.TEXT and Operation.TEXT not in provider.operations:
            raise ProductionError(f"{provider.name} a besoin d'une image de départ pour la scène {scene.position + 1}.")
        amount = provider.estimate_cost(request)
        confirmation = None
        if provider.kind != "local":
            decision = budget.check(amount, project_id=project.id, provider_name=provider.name)
            if not decision.allowed:
                raise ProductionError(f"Scène {scene.position + 1} bloquée : {'; '.join(decision.reasons)}.")
            confirmation = budget.open_confirmation(scene.id, provider.id, amount or 0)
            if confirmation is None:
                raise ProductionError(f"La dépense de la scène {scene.position + 1} n'a pas été confirmée.")
        job = ProviderJob(provider_id=provider.id, project_id=project.id, scene_id=scene.id, operation=operation.value,
                          status="running", estimated_cost_usd=amount or 0,
                          params=request.model_dump(mode="json", exclude={"extra"}))
        session.add(job)
        scene.status = "running"
        session.flush()
        try:
            submit = provider.generate_from_image if operation is Operation.IMAGE else provider.generate_from_text
            job.external_id = submit(request)
            session.flush()
            status = provider.wait(job.external_id, poll_interval_s=runtime.settings.provider_poll_interval_s,
                                   timeout_s=runtime.settings.provider_timeout_s, sleep=runtime.sleep)
            if status.state is not JobState.SUCCEEDED:
                raise ProviderError(status.error or f"{provider.name} : génération échouée.")
            path = provider.download_result(job.external_id, runtime.project_dir(project.id) / "videos"
                                            / f"scene_{scene.position:02d}")
        except Exception as exc:
            job.status, job.error, scene.status = "failed", str(exc), "failed"
            session.flush()
            raise
        asset = _new_asset(session, project.id, scene.id, "video", path, "video/mp4")
        job.status, job.result_asset_id, scene.status = "succeeded", asset.id, "done"
        if amount:
            cost = budget.record(amount, project_id=project.id, scene_id=scene.id, provider_id=provider.id,
                                 provider_job_id=job.id, description=f"{provider.name}, scène {scene.position + 1}")
            spent += cost.amount_usd
            if confirmation is not None:
                confirmation.provider_job_id = job.id  # confirmation utilisee
        session.flush()
        generated += 1
    return {"videos_generated": generated, "spent_usd": round(spent, 4)}


def reset_scene(session: Session, scene: Scene, target: str) -> None:
    """Prepare la regeneration d'une scene : nouvelle seed, statuts remis a zero."""
    if target not in ("image", "video"):
        raise ProductionError("Cible inconnue : image ou video.")
    scene.seed = random.randint(0, 2**31 - 1)
    scene.status = "pending"
    if target == "image":
        scene.image_status = "pending"
    session.flush()


def _request(session: Session, scene: Scene) -> VideoRequest:
    image = scene_asset(session, scene.id, "image")
    return VideoRequest(prompt=scene.visual_prompt, negative_prompt=scene.negative_prompt, duration_s=scene.duration_s,
                        seed=scene.seed, image_path=Path(image.path) if image and Path(image.path).exists() else None)
