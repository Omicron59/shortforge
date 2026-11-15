"""Definition des etapes du pipeline et des statuts possibles."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    NEEDS_VALIDATION = "needs_validation"
    CANCELLED = "cancelled"


class StepName(StrEnum):
    GENERATE_IDEAS = "generate_ideas"
    SELECT_IDEA = "select_idea"
    WRITE_SCRIPT = "write_script"
    APPROVE_SCRIPT = "approve_script"
    CREATE_STORYBOARD = "create_storyboard"
    GENERATE_IMAGES = "generate_images"
    GENERATE_VIDEOS = "generate_videos"
    GENERATE_VOICE = "generate_voice"
    CREATE_SUBTITLES = "create_subtitles"
    SELECT_MUSIC = "select_music"
    RENDER_VIDEO = "render_video"
    REVIEW_PREVIEW = "review_preview"
    APPROVE_FINAL_RENDER = "approve_final_render"
    CREATE_YOUTUBE_DRAFT = "create_youtube_draft"
    PUBLISH = "publish"


@dataclass(frozen=True, slots=True)
class StepDefinition:
    """Une etape du pipeline.

    `human_gate` : l'etape ne s'execute pas toute seule, elle attend une decision humaine.
    `redo_from` : etape a relancer quand l'utilisateur rejette cette validation.
    """

    name: StepName
    label: str
    human_gate: bool = False
    redo_from: StepName | None = None


PIPELINE: tuple[StepDefinition, ...] = (
    StepDefinition(StepName.GENERATE_IDEAS, "Génération des idées"),
    StepDefinition(StepName.SELECT_IDEA, "Choix de l'idée", human_gate=True, redo_from=StepName.GENERATE_IDEAS),
    StepDefinition(StepName.WRITE_SCRIPT, "Écriture du script"),
    StepDefinition(StepName.APPROVE_SCRIPT, "Validation du script", human_gate=True,
                   redo_from=StepName.WRITE_SCRIPT),
    StepDefinition(StepName.CREATE_STORYBOARD, "Découpage en scènes"),
    StepDefinition(StepName.GENERATE_IMAGES, "Génération des images"),
    StepDefinition(StepName.GENERATE_VIDEOS, "Génération des vidéos"),
    StepDefinition(StepName.GENERATE_VOICE, "Voix off"),
    StepDefinition(StepName.CREATE_SUBTITLES, "Sous-titres"),
    StepDefinition(StepName.SELECT_MUSIC, "Choix de la musique"),
    StepDefinition(StepName.RENDER_VIDEO, "Montage"),
    StepDefinition(StepName.REVIEW_PREVIEW, "Revue de l'aperçu", human_gate=True,
                   redo_from=StepName.RENDER_VIDEO),
    StepDefinition(StepName.APPROVE_FINAL_RENDER, "Validation du rendu final", human_gate=True,
                   redo_from=StepName.RENDER_VIDEO),
    StepDefinition(StepName.CREATE_YOUTUBE_DRAFT, "Brouillon YouTube"),
    StepDefinition(StepName.PUBLISH, "Publication", human_gate=True),
)

STEP_ORDER: dict[StepName, int] = {d.name: i for i, d in enumerate(PIPELINE)}
DEFINITIONS: dict[StepName, StepDefinition] = {d.name: d for d in PIPELINE}

# Transitions autorisees : statut actuel -> statuts suivants possibles.
TRANSITIONS: dict[StepStatus, frozenset[StepStatus]] = {
    StepStatus.PENDING: frozenset({StepStatus.RUNNING, StepStatus.NEEDS_VALIDATION, StepStatus.CANCELLED}),
    StepStatus.RUNNING: frozenset({StepStatus.DONE, StepStatus.FAILED, StepStatus.NEEDS_VALIDATION,
                                   StepStatus.CANCELLED, StepStatus.PENDING}),
    StepStatus.NEEDS_VALIDATION: frozenset({StepStatus.DONE, StepStatus.PENDING, StepStatus.CANCELLED}),
    StepStatus.FAILED: frozenset({StepStatus.RUNNING, StepStatus.PENDING, StepStatus.CANCELLED}),
    StepStatus.DONE: frozenset({StepStatus.PENDING}),
    StepStatus.CANCELLED: frozenset({StepStatus.PENDING}),
}


def can_transition(current: StepStatus, target: StepStatus) -> bool:
    return target in TRANSITIONS[current]
