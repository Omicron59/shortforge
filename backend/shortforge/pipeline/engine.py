"""Moteur du pipeline : fait avancer un projet etape par etape et sauvegarde tout en SQLite.

Principes :
- les etapes s'executent strictement dans l'ordre de `PIPELINE` ;
- chaque changement de statut est ecrit en base, donc un projet interrompu (plantage,
  fermeture de l'application) se reprend la ou il s'etait arrete ;
- les etapes de validation (`human_gate`) n'avancent qu'avec une decision humaine ;
- la publication passe en plus par le garde-fou `publish_guard`.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.models import PipelineStep, Project, utcnow
from shortforge.pipeline.handlers import ConfirmationRequired, HandlerRegistry, StepContext
from shortforge.pipeline.steps import DEFINITIONS, PIPELINE, StepName, StepStatus, can_transition
from shortforge.services.publish_guard import ensure_can_publish, is_human_actor

INTERRUPTED_MESSAGE = "Étape interrompue (application fermée ou plantage) : elle sera relancée."


class PipelineError(Exception):
    """Erreur metier du pipeline ; le message est destine a l'utilisateur."""


class ProjectNotFoundError(PipelineError):
    pass


class InvalidTransitionError(PipelineError):
    pass


class StepNotAvailableError(PipelineError):
    pass


class PipelineService:
    """Operations sur les projets et leur pipeline, dans une session SQLAlchemy."""

    def __init__(self, session: Session, settings: Settings, registry: HandlerRegistry) -> None:
        self.session = session
        self.settings = settings
        self.registry = registry

    # ── Projets ──

    def create_project(
        self, title: str, *, niche: str = "", language: str = "fr", video_mode: str = "economique"
    ) -> Project:
        title = title.strip()
        if not title:
            raise PipelineError("Le titre du projet est obligatoire.")
        project = Project(title=title, niche=niche.strip(), language=language, video_mode=video_mode)
        project.steps = [
            PipelineStep(name=d.name.value, position=i, status=StepStatus.PENDING.value)
            for i, d in enumerate(PIPELINE)
        ]
        project.current_step = PIPELINE[0].name.value
        self.session.add(project)
        self.session.flush()
        return project

    def get_project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise ProjectNotFoundError("Projet introuvable.")
        return project

    def list_projects(self) -> list[Project]:
        return list(self.session.scalars(select(Project).order_by(Project.updated_at.desc())))

    # ── Etapes ──

    def steps(self, project_id: str) -> list[PipelineStep]:
        return list(self.get_project(project_id).steps)

    def get_step(self, project_id: str, name: StepName | str) -> PipelineStep:
        try:
            step_name = StepName(name)
        except ValueError as exc:
            raise PipelineError(f"Étape inconnue : {name}.") from exc
        for step in self.steps(project_id):
            if step.name == step_name.value:
                return step
        raise PipelineError(f"Étape introuvable : {name}.")

    def next_step(self, project_id: str) -> PipelineStep | None:
        """Premiere etape qui n'est pas terminee, ou None si le projet est fini."""
        return next((s for s in self.steps(project_id) if s.status != StepStatus.DONE.value), None)

    def advance(self, project_id: str) -> PipelineStep:
        """Fait progresser le projet d'une etape et renvoie l'etape traitee."""
        step = self.next_step(project_id)
        if step is None:
            raise PipelineError("Le projet est terminé : il n'y a plus d'étape à lancer.")
        status = StepStatus(step.status)
        definition = DEFINITIONS[StepName(step.name)]
        if status is StepStatus.RUNNING:
            raise InvalidTransitionError(f"« {definition.label} » est déjà en cours.")
        if status is StepStatus.NEEDS_VALIDATION:
            raise InvalidTransitionError(f"« {definition.label} » attend ta validation.")
        if status is StepStatus.CANCELLED:
            raise InvalidTransitionError("Le projet est annulé : reprends-le avant de continuer.")

        if definition.human_gate:
            self._set(step, StepStatus.NEEDS_VALIDATION)
            return step

        handler = self.registry.get(definition.name)
        if handler is None:
            raise StepNotAvailableError(f"L'étape « {definition.label} » n'est pas encore disponible.")

        self._set(step, StepStatus.RUNNING)
        step.attempts += 1
        step.error = None
        self.session.flush()
        try:
            output = handler(StepContext(project_id, definition.name, self.session, self.settings))
        except ConfirmationRequired as req:
            step.output = {"confirmation_required": req.items, "message": req.message}
            self._set(step, StepStatus.NEEDS_VALIDATION)
            return step
        except Exception as exc:  # l'echec est enregistre, jamais perdu
            step.error = str(exc) or exc.__class__.__name__
            self._set(step, StepStatus.FAILED)
            return step
        step.output = output
        self._set(step, StepStatus.DONE)
        return step

    def approve(self, project_id: str, name: StepName | str, *, actor: str,
                confirmed: bool = False) -> PipelineStep:
        """Validation humaine d'une etape qui l'attend.

        Etape de validation (`human_gate`) : elle passe a `done`. Etape automatique qui attendait une
        confirmation (ex. depense) : la confirmation est enregistree et l'etape repasse a `pending`
        pour etre relancee.
        """
        step = self.get_step(project_id, name)
        if step.status != StepStatus.NEEDS_VALIDATION.value:
            raise InvalidTransitionError("Cette étape n'attend pas de validation.")
        if not is_human_actor(actor):
            raise PipelineError("Une validation doit être faite par une personne.")
        definition = DEFINITIONS[StepName(step.name)]
        if step.name == StepName.PUBLISH.value:
            final = self.get_step(project_id, StepName.APPROVE_FINAL_RENDER)
            ensure_can_publish(
                self.settings, final_render_validated_by=final.validated_by, confirmed=confirmed, actor=actor
            )
        if not definition.human_gate and not confirmed:
            raise PipelineError("Confirme explicitement (confirm: true) pour lancer cette dépense.")
        hook = self.registry.approve_hook(definition.name)
        if hook is not None:
            hook(StepContext(project_id, definition.name, self.session, self.settings,
                             actor=actor.strip(), confirmed=confirmed))
        step.validated_at = utcnow()
        step.validated_by = actor.strip()
        self._set(step, StepStatus.DONE if definition.human_gate else StepStatus.PENDING)
        return step

    def reject(self, project_id: str, name: StepName | str, *, reason: str = "") -> PipelineStep:
        """Refus d'une validation : relance l'etape qui l'a produite, ou annule la publication."""
        step = self.get_step(project_id, name)
        if step.status != StepStatus.NEEDS_VALIDATION.value:
            raise InvalidTransitionError("Cette étape n'attend pas de validation.")
        definition = DEFINITIONS[StepName(step.name)]
        if not definition.human_gate:  # depense refusee : on change de moteur puis on relance
            step.error = reason or "Dépense refusée : choisis un autre moteur pour ces scènes puis relance."
            self._set(step, StepStatus.PENDING)
            return step
        if definition.redo_from is None:
            step.error = reason or "Refusé par l'utilisateur."
            self._set(step, StepStatus.CANCELLED)
            return step
        self.redo(project_id, definition.redo_from)
        origin = self.get_step(project_id, definition.redo_from)
        origin.error = f"Refusé : {reason}" if reason else "Refusé par l'utilisateur."
        return origin

    def redo(self, project_id: str, name: StepName | str) -> PipelineStep:
        """Remet une etape et toutes les suivantes a `pending` (bouton Refaire)."""
        target = self.get_step(project_id, name)
        later = [s for s in self.steps(project_id) if s.position >= target.position]
        if any(s.status == StepStatus.RUNNING.value for s in later):
            raise InvalidTransitionError("Impossible de refaire pendant qu'une étape est en cours.")
        for step in later:
            if step.status != StepStatus.PENDING.value:
                self._set(step, StepStatus.PENDING)
            step.output = None
            step.error = None
            step.validated_at = None
            step.validated_by = None
            step.started_at = None
            step.finished_at = None
        self._refresh_project(target.project)
        return target

    def cancel(self, project_id: str) -> Project:
        """Annule le projet : l'etape courante passe a `cancelled`."""
        step = self.next_step(project_id)
        if step is None:
            raise PipelineError("Le projet est déjà terminé.")
        self._set(step, StepStatus.CANCELLED)
        return step.project

    def resume(self, project_id: str) -> PipelineStep | None:
        """Reprend un projet annule ou interrompu ; renvoie l'etape a relancer."""
        for step in self.steps(project_id):
            if step.status == StepStatus.RUNNING.value:
                step.error = INTERRUPTED_MESSAGE
                self._set(step, StepStatus.PENDING)
            elif step.status == StepStatus.CANCELLED.value:
                step.error = None
                self._set(step, StepStatus.PENDING)
        return self.next_step(project_id)

    def recover_interrupted(self) -> int:
        """Au demarrage : toute etape restee `running` a ete interrompue. Renvoie leur nombre."""
        query = select(PipelineStep).where(PipelineStep.status == StepStatus.RUNNING.value)
        stuck = list(self.session.scalars(query))
        for step in stuck:
            step.error = INTERRUPTED_MESSAGE
            self._set(step, StepStatus.PENDING)
        return len(stuck)

    # ── Interne ──

    def _set(self, step: PipelineStep, target: StepStatus) -> None:
        current = StepStatus(step.status)
        if not can_transition(current, target):
            raise InvalidTransitionError(f"Transition impossible : {current.value} → {target.value}.")
        step.status = target.value
        now = utcnow()
        if target is StepStatus.RUNNING:
            step.started_at = now
            step.finished_at = None
        elif target in (StepStatus.DONE, StepStatus.FAILED, StepStatus.CANCELLED):
            step.finished_at = now
        self._refresh_project(step.project)
        self.session.flush()

    @staticmethod
    def _refresh_project(project: Project) -> None:
        statuses = [s.status for s in project.steps]
        nxt = next((s for s in project.steps if s.status != StepStatus.DONE.value), None)
        project.current_step = nxt.name if nxt else None
        if nxt is None:
            project.status = "done"
        elif StepStatus.CANCELLED.value in statuses:
            project.status = "cancelled"
        elif any(s != StepStatus.PENDING.value for s in statuses):
            project.status = "in_progress"
        else:
            project.status = "draft"
        project.updated_at = utcnow()
