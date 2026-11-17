"""Nouveau parcours de creation en 4 etapes : brief, idees, script et storyboard, studio.

Il s'appuie sur les memes projets et le meme pipeline que l'ancien parcours, qui reste disponible.
Chaque generation porte un `request_id` : si l'utilisateur annule, le resultat est jete sans etre enregistre.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi import status as http
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from shortforge.ai.router import TaskRouter
from shortforge.config import Settings
from shortforge.deps import build_service, get_runtime, get_session, get_settings_dep
from shortforge.models import Asset, Idea, Project, Scene, Script
from shortforge.pipeline import PipelineError, PipelineService, StepName, StepStatus
from shortforge.routers.projects import detail
from shortforge.routers.studio import IMAGE_EXTENSIONS, save_upload
from shortforge.runtime import Runtime
from shortforge.schemas import IdeaOut, SceneOut
from shortforge.services import ideas as idea_service
from shortforge.services import scripts as script_service
from shortforge.services import wizard
from shortforge.services.production import ProductionError
from shortforge.services.production import _sha256 as file_sha256
from shortforge.services.safety import content_issues

router = APIRouter(prefix="/api/wizard", tags=["parcours de création"])
ACTOR = "utilisateur"
DONE_HERE = "Réalisé dans le nouveau parcours de création."
TASKS = ("ideas", "script", "storyboard", "variants")


# --- outils ---
def _project(request: Request, session: Session, project_id: str) -> tuple[PipelineService, Project]:
    service = build_service(request, session)
    project = service.get_project(project_id)
    service.ensure_steps(project)  # un projet sans ses etapes s'ouvre quand meme
    return service, project


def _scene(session: Session, scene_id: str) -> tuple[Scene, Project]:
    scene = session.get(Scene, scene_id)
    project = session.get(Project, scene.project_id) if scene else None
    if scene is None or project is None:
        raise HTTPException(http.HTTP_404_NOT_FOUND, "Scène introuvable.")
    return scene, project


def _approved(service: PipelineService, project_id: str) -> bool:
    return service.get_step(project_id, StepName.APPROVE_SCRIPT).status == StepStatus.DONE.value


def _must_be_open(service: PipelineService, project_id: str) -> None:
    if _approved(service, project_id):
        raise PipelineError("Le script est validé. Rouvre-le depuis le studio pour changer sa structure.")


def _mark_done(service: PipelineService, project: Project, name: StepName) -> None:
    """Une etape automatique faite ici (idees, script) est notee comme terminee dans le pipeline."""
    step = service.get_step(project.id, name)
    if step.status not in (StepStatus.PENDING.value, StepStatus.DONE.value):
        service.redo(project.id, name)
    service.skip_steps(project, [name], reason=DONE_HERE, actor=ACTOR)


def _pass_gate(service: PipelineService, project_id: str, name: StepName) -> None:
    """Validation explicite de l'utilisateur sur une etape de decision (choix de l'idee, script)."""
    step = service.get_step(project_id, name)
    if step.status == StepStatus.PENDING.value:
        upcoming = service.next_step(project_id)
        if upcoming is None or upcoming.name != name.value:
            raise PipelineError("Une étape précédente n'est pas terminée.")
        service.advance(project_id)
    if step.status == StepStatus.NEEDS_VALIDATION.value:
        service.approve(project_id, name, actor=ACTOR)


def _cancelled(request: Request, request_id: str) -> None:
    """Appele apres la reponse du modele : une demande annulee n'enregistre rien."""
    cancelled: set[str] = request.app.state.cancelled_requests
    if request_id and request_id in cancelled:
        cancelled.discard(request_id)
        raise HTTPException(http.HTTP_409_CONFLICT, "Génération annulée : rien n'a été enregistré.")


def _engines(session: Session, runtime: Runtime) -> dict[str, Any]:
    """Moteur prevu par tache (fournisseur, modele, local ou cloud). Vide si le routage n'est pas actif."""
    if not isinstance(runtime.llm, TaskRouter):
        return {}
    return {task: runtime.llm.describe(session, task) for task in TASKS}


def _used(runtime: Runtime) -> dict[str, Any] | None:
    return runtime.llm.last_used() if isinstance(runtime.llm, TaskRouter) else None


def _brief_out(brief: Any) -> dict[str, Any]:
    return {c.name: getattr(brief, c.name) for c in brief.__table__.columns if c.name not in ("project_id",
                                                                                              "updated_at")}


def _script_out(session: Session, script: Script | None) -> dict[str, Any] | None:
    if script is None:
        return None
    scenes = script_service.scenes_of(session, script.id)
    return {"id": script.id, "version": script.version, "status": script.status,
            "call_to_action": script.call_to_action,
            "estimated_duration_s": wizard.current_duration(session, script),
            "scenes": [SceneOut.model_validate(s).model_dump() for s in scenes]}


def _state(request: Request, session: Session, runtime: Runtime, project: Project,
           extra: dict[str, Any] | None = None) -> dict[str, Any]:
    service = build_service(request, session)
    brief = wizard.brief_of(session, project)
    ideas = list(session.scalars(select(Idea).where(Idea.project_id == project.id)
                                 .order_by(Idea.batch.desc(), Idea.created_at)))
    script = script_service.current_script(session, project.id)
    approved = _approved(service, project.id)
    selected = next((i for i in ideas if i.selected), None)
    step = "studio" if approved else "script" if selected is not None and script is not None else "ideas"
    scenes = script_service.scenes_of(session, script.id) if script else []
    return {
        "project": detail(project).model_dump(mode="json"), "brief": _brief_out(brief), "step": step,
        "ideas": [IdeaOut.model_validate(i).model_dump() for i in ideas],
        "selected_idea_id": selected.id if selected else None,
        "script": _script_out(session, script), "script_approved": approved,
        "problems": wizard.missing_for_approval(session, script) if script else [],
        "stale": wizard.staleness(session, project, list(project.steps), scenes),
        "engines": _engines(session, runtime), **(extra or {}),
    }


# --- brief ---
@router.get("/options")
def options() -> dict[str, Any]:
    return {"goals": wizard.GOALS, "tones": wizard.TONES, "platforms": wizard.PLATFORMS,
            "languages": wizard.LANGUAGES, "durations": list(wizard.DURATIONS),
            "defaults": wizard.BriefData().model_dump()}


@router.get("/engines")
def engines(session: Session = Depends(get_session), runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return _engines(session, runtime)


@router.post("/projects", status_code=http.HTTP_201_CREATED)
def create(payload: wizard.BriefData, request: Request, session: Session = Depends(get_session),
           runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    if not payload.subject.strip() and not payload.niche.strip():
        raise HTTPException(http.HTTP_400_BAD_REQUEST, "Indique au moins un sujet ou une niche.")
    project = build_service(request, session).create_project(wizard.project_title(payload), niche=payload.niche,
                                                             language=payload.language)
    wizard.save_brief(session, project, payload)
    return _state(request, session, runtime, project)


@router.get("/projects/{project_id}")
def state(project_id: str, request: Request, session: Session = Depends(get_session),
          runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    _, project = _project(request, session, project_id)
    return _state(request, session, runtime, project)


@router.put("/projects/{project_id}/brief")
def update_brief(project_id: str, payload: wizard.BriefData, request: Request,
                 session: Session = Depends(get_session)) -> dict[str, Any]:
    _, project = _project(request, session, project_id)
    return _brief_out(wizard.save_brief(session, project, payload))


@router.post("/cancel/{request_id}")
def cancel(request_id: str, request: Request) -> dict[str, bool]:
    """L'appel deja parti chez le fournisseur peut se terminer, mais son resultat sera ignore."""
    cancelled: set[str] = request.app.state.cancelled_requests
    if len(cancelled) > 500:
        cancelled.clear()
    cancelled.add(request_id[:64])
    return {"cancelled": True}


# --- idees ---
class IdeasIn(BaseModel):
    request_id: str = Field(default="", max_length=64)
    variant_of: str | None = None


@router.post("/projects/{project_id}/ideas")
def generate_ideas(project_id: str, payload: IdeasIn, request: Request, session: Session = Depends(get_session),
                   runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    service, project = _project(request, session, project_id)
    base = None
    if payload.variant_of:
        base = session.get(Idea, payload.variant_of)
        if base is None or base.project_id != project.id:
            raise HTTPException(http.HTTP_404_NOT_FOUND, "Idée introuvable.")
    llm = runtime.llm_for("variants" if base else "ideas")
    result = wizard.generate_ideas(session, llm, project, wizard.brief_of(session, project),
                                   count=3 if base else 5, base=base)
    _cancelled(request, payload.request_id)
    if not _approved(service, project.id):
        _mark_done(service, project, StepName.GENERATE_IDEAS)
    return _state(request, session, runtime, project, {"new_idea_ids": [i.id for i in result.ideas],
                                                       "rejected": result.rejected, "used": _used(runtime)})


class IdeaPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    hook: str | None = Field(default=None, max_length=500)
    original_angle: str | None = Field(default=None, max_length=1000)
    summary: str | None = Field(default=None, max_length=1000)
    saved: bool | None = None


@router.patch("/ideas/{idea_id}", response_model=IdeaOut)
def patch_idea(idea_id: str, payload: IdeaPatch, session: Session = Depends(get_session)) -> IdeaOut:
    idea = session.get(Idea, idea_id)
    if idea is None:
        raise HTTPException(http.HTTP_404_NOT_FOUND, "Idée introuvable.")
    changes = payload.model_dump(exclude_none=True)
    if issues := content_issues(" ".join(str(v) for v in changes.values() if isinstance(v, str))):
        raise PipelineError("Modification refusée : " + ", ".join(issues) + ".")
    for name, value in changes.items():
        setattr(idea, name, value)
    session.flush()
    return IdeaOut.model_validate(idea)


@router.post("/projects/{project_id}/ideas/{idea_id}/choose")
def choose_idea(project_id: str, idea_id: str, request: Request, session: Session = Depends(get_session),
                runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    """Choisir une idee. Changer d'idee garde le script deja ecrit dans l'historique des versions."""
    service, project = _project(request, session, project_id)
    _must_be_open(service, project.id)
    if service.get_step(project.id, StepName.SELECT_IDEA).status != StepStatus.PENDING.value:
        service.redo(project.id, StepName.SELECT_IDEA)
    _mark_done(service, project, StepName.GENERATE_IDEAS)
    idea_service.select_idea(session, project.id, idea_id)
    _pass_gate(service, project.id, StepName.SELECT_IDEA)
    return _state(request, session, runtime, project)


# --- script et storyboard ---
class GenerateIn(BaseModel):
    request_id: str = Field(default="", max_length=64)


def _selected(session: Session, project: Project) -> Idea:
    idea = idea_service.selected_idea(session, project.id)
    if idea is None:
        raise PipelineError("Choisis d'abord une idée.")
    return idea


@router.post("/projects/{project_id}/script/generate")
def generate_script(project_id: str, payload: GenerateIn, request: Request, session: Session = Depends(get_session),
                    runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    """Ecrit une nouvelle version complete (les versions precedentes restent dans l'historique)."""
    service, project = _project(request, session, project_id)
    _must_be_open(service, project.id)
    wizard.generate_script(session, runtime.llm_for("script"), project, wizard.brief_of(session, project),
                           _selected(session, project))
    _cancelled(request, payload.request_id)
    _mark_done(service, project, StepName.WRITE_SCRIPT)
    return _state(request, session, runtime, project, {"used": _used(runtime)})


@router.post("/projects/{project_id}/script/manual")
def manual_script(project_id: str, request: Request, session: Session = Depends(get_session),
                  runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    """Ecrire soi-meme, sans modele : cree un script vide (et une idee tiree du brief s'il n'y en a pas)."""
    service, project = _project(request, session, project_id)
    _must_be_open(service, project.id)
    idea = idea_service.selected_idea(session, project.id)
    if idea is None:
        idea = wizard.manual_idea(session, project, wizard.brief_of(session, project))
        _mark_done(service, project, StepName.GENERATE_IDEAS)
        idea_service.select_idea(session, project.id, idea.id)
        _pass_gate(service, project.id, StepName.SELECT_IDEA)
    wizard.manual_script(session, project, idea)
    _mark_done(service, project, StepName.WRITE_SCRIPT)
    return _state(request, session, runtime, project)


def _script(session: Session, project: Project) -> Script:
    script = script_service.current_script(session, project.id)
    if script is None:
        raise PipelineError("Aucun script pour ce projet.")
    return script


class TransformIn(BaseModel):
    request_id: str = Field(default="", max_length=64)
    kind: str
    tone: str = ""
    target_duration_s: float | None = Field(default=None, ge=5, le=180)


@router.post("/projects/{project_id}/script/transform")
def transform_script(project_id: str, payload: TransformIn, request: Request,
                     session: Session = Depends(get_session),
                     runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    service, project = _project(request, session, project_id)
    _must_be_open(service, project.id)
    wizard.transform_script(session, runtime.llm_for("script"), project, wizard.brief_of(session, project),
                            _script(session, project), payload.kind, tone=payload.tone,
                            target_duration_s=payload.target_duration_s)
    _cancelled(request, payload.request_id)
    return _state(request, session, runtime, project, {"used": _used(runtime)})


@router.post("/projects/{project_id}/script/hooks")
def hooks(project_id: str, payload: GenerateIn, request: Request, session: Session = Depends(get_session),
          runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    """Propositions seulement : rien n'est modifie tant que l'utilisateur n'en applique pas une."""
    _, project = _project(request, session, project_id)
    found = wizard.hook_variants(session, runtime.llm_for("variants"), wizard.brief_of(session, project),
                                 _script(session, project))
    _cancelled(request, payload.request_id)
    return {"hooks": found, "used": _used(runtime)}


class ScriptPatch(BaseModel):
    call_to_action: str | None = Field(default=None, max_length=500)


@router.put("/projects/{project_id}/script")
def patch_script(project_id: str, payload: ScriptPatch, request: Request, session: Session = Depends(get_session),
                 runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    _, project = _project(request, session, project_id)
    script = _script(session, project)
    if payload.call_to_action is not None and payload.call_to_action != script.call_to_action:
        if issues := content_issues(payload.call_to_action):
            raise PipelineError("Modification refusée : " + ", ".join(issues) + ".")
        script.call_to_action = payload.call_to_action
        wizard.touch(project)
    return _state(request, session, runtime, project)


@router.get("/projects/{project_id}/script/versions")
def list_versions(project_id: str, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return wizard.versions(session, project_id)


@router.post("/projects/{project_id}/script/snapshot")
def snapshot(project_id: str, request: Request, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    _, project = _project(request, session, project_id)
    wizard.snapshot(session, _script(session, project))
    return wizard.versions(session, project.id)


@router.post("/projects/{project_id}/script/versions/{version}/restore")
def restore(project_id: str, version: int, request: Request, session: Session = Depends(get_session),
            runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    service, project = _project(request, session, project_id)
    _must_be_open(service, project.id)
    try:
        wizard.restore(session, project, version)
    except ValueError as exc:
        raise HTTPException(http.HTTP_404_NOT_FOUND, str(exc)) from exc
    return _state(request, session, runtime, project)


@router.post("/projects/{project_id}/script/approve")
def approve_script(project_id: str, request: Request, session: Session = Depends(get_session),
                   runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    """Validation explicite du script, puis decoupage pour la production (aucune generation de media)."""
    service, project = _project(request, session, project_id)
    script = _script(session, project)
    if problems := wizard.missing_for_approval(session, script):
        raise PipelineError("Le script n'est pas prêt : " + " ".join(problems))
    _mark_done(service, project, StepName.WRITE_SCRIPT)
    _pass_gate(service, project.id, StepName.APPROVE_SCRIPT)
    script.status = "approved"
    warning = ""
    upcoming = service.next_step(project.id)
    if upcoming is not None and upcoming.name == StepName.CREATE_STORYBOARD.value:
        done = service.advance(project.id)
        if done.status == StepStatus.FAILED.value:
            warning = f"Le découpage pour la production a échoué : {done.error}"
    return _state(request, session, runtime, project, {"warning": warning})


@router.post("/projects/{project_id}/script/reopen")
def reopen_script(project_id: str, request: Request, session: Session = Depends(get_session),
                  runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    """Rouvre le script valide. Les medias deja produits sont gardes ; les etapes suivantes sont a refaire."""
    service, project = _project(request, session, project_id)
    if _approved(service, project.id):
        service.redo(project.id, StepName.APPROVE_SCRIPT)
        _script(session, project).status = "draft"
    return _state(request, session, runtime, project)


# --- scenes ---
class SceneAdd(BaseModel):
    after: int | None = None


@router.post("/projects/{project_id}/scenes")
def add_scene(project_id: str, payload: SceneAdd, request: Request, session: Session = Depends(get_session),
              runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    service, project = _project(request, session, project_id)
    _must_be_open(service, project.id)
    new = wizard.add_scene(session, project, _script(session, project), payload.after)
    return _state(request, session, runtime, project, {"scene_id": new.id})


class SceneOrder(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=30)


@router.put("/projects/{project_id}/scenes/order")
def reorder(project_id: str, payload: SceneOrder, request: Request, session: Session = Depends(get_session),
            runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    _, project = _project(request, session, project_id)
    wizard.reorder_scenes(session, project, _script(session, project), payload.ids)
    return _state(request, session, runtime, project)


class ScenePatch(BaseModel):
    text: str | None = Field(default=None, max_length=2000)
    on_screen_text: str | None = Field(default=None, max_length=200)
    visual_intent: str | None = Field(default=None, max_length=500)
    visual_prompt: str | None = Field(default=None, max_length=2000)
    negative_prompt: str | None = Field(default=None, max_length=2000)
    transition: str | None = None
    duration_s: float | None = Field(default=None, ge=1, le=15)


@router.patch("/scenes/{scene_id}", response_model=SceneOut)
def patch_scene(scene_id: str, payload: ScenePatch, session: Session = Depends(get_session)) -> SceneOut:
    scene, project = _scene(session, scene_id)
    return SceneOut.model_validate(wizard.patch_scene(session, project, scene, payload.model_dump(exclude_none=True)))


@router.delete("/scenes/{scene_id}")
def delete_scene(scene_id: str, request: Request, session: Session = Depends(get_session),
                 runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    scene, project = _scene(session, scene_id)
    _must_be_open(build_service(request, session), project.id)
    wizard.delete_scene(session, project, scene)
    return _state(request, session, runtime, project)


class FieldIn(BaseModel):
    request_id: str = Field(default="", max_length=64)
    field: str


@router.post("/scenes/{scene_id}/regenerate-field")
def regenerate_field(scene_id: str, payload: FieldIn, request: Request, session: Session = Depends(get_session),
                     runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    """Regenere un seul champ d'une seule scene (texte, texte a l'ecran ou prompt visuel)."""
    scene, project = _scene(session, scene_id)
    task = "storyboard" if payload.field == "visual_prompt" else "script"
    updated = wizard.regenerate_field(session, runtime.llm_for(task), project, wizard.brief_of(session, project),
                                      scene, payload.field)
    _cancelled(request, payload.request_id)
    return {"scene": SceneOut.model_validate(updated).model_dump(), "used": _used(runtime)}


@router.put("/scenes/{scene_id}/image", response_model=SceneOut)
async def import_image(scene_id: str, request: Request, filename: str, rights_confirmed: bool = False,
                       session: Session = Depends(get_session),
                       settings: Settings = Depends(get_settings_dep)) -> SceneOut:
    """Image fournie par l'utilisateur pour une scene (a la place d'une generation)."""
    scene, project = _scene(session, scene_id)
    ext = Path(filename).suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        raise ProductionError("Image attendue : PNG, JPG ou WebP.")
    if not rights_confirmed:
        raise ProductionError("Confirme que tu as le droit d'utiliser cette image.")
    count = len(list(session.scalars(select(Asset.id).where(Asset.scene_id == scene.id, Asset.kind == "image"))))
    dest = settings.shortforge_data_dir / "projects" / project.id / "images" / f"import_{scene.id}_{count}{ext}"
    await save_upload(request, dest, 20 * 2**20)
    mime = {".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")
    session.add(Asset(project_id=project.id, scene_id=scene.id, kind="image", path=str(dest), mime_type=mime,
                      origin="imported", rights_confirmed=True, license="fourni par l'utilisateur",
                      sha256=file_sha256(dest)))
    scene.image_status = "done"
    scene.status = "pending"  # une video deja faite avec l'ancienne image est a refaire
    session.flush()
    return SceneOut.model_validate(scene)


# --- projet ---
@router.post("/projects/{project_id}/duplicate", status_code=http.HTTP_201_CREATED)
def duplicate(project_id: str, request: Request, session: Session = Depends(get_session),
              runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    """Copie le brief, l'idee choisie et le script. Les images, voix et rendus ne sont pas copies."""
    service, source = _project(request, session, project_id)
    copy = service.create_project(f"{source.title[:180]} (copie)", niche=source.niche, language=source.language,
                                  video_mode=source.video_mode)
    wizard.duplicate(session, source, copy)
    if idea_service.selected_idea(session, copy.id) is not None:
        _mark_done(service, copy, StepName.GENERATE_IDEAS)
        _pass_gate(service, copy.id, StepName.SELECT_IDEA)
        if script_service.current_script(session, copy.id) is not None:
            _mark_done(service, copy, StepName.WRITE_SCRIPT)
    return _state(request, session, runtime, copy)
