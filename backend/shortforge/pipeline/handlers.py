"""Registre des fonctions qui executent les etapes automatiques.

Chaque integration (Ollama, ComfyUI, voix, montage...) enregistrera sa fonction ici aux
etapes suivantes du projet. Une etape sans fonction enregistree n'est pas encore disponible.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.pipeline.steps import StepName


@dataclass(frozen=True, slots=True)
class StepContext:
    """Ce que recoit une fonction d'etape."""

    project_id: str
    step: StepName
    session: Session
    settings: Settings
    actor: str = ""  # personne qui valide (crochets de validation seulement)
    confirmed: bool = False  # confirmation explicite donnee avec la validation


StepHandler = Callable[[StepContext], dict[str, Any]]
ApproveHook = Callable[[StepContext], None]


class ConfirmationRequired(Exception):
    """Levee par une etape qui a besoin d'une confirmation humaine avant de continuer
    (ex. une depense). L'etape passe a `needs_validation` avec `items` dans son resultat."""

    def __init__(self, message: str, items: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.message = message
        self.items = items


class HandlerRegistry:
    """Associe une etape a la fonction qui l'execute, et a ce qu'il faut faire quand on la valide."""

    def __init__(self) -> None:
        self._handlers: dict[StepName, StepHandler] = {}
        self._approve_hooks: dict[StepName, ApproveHook] = {}

    def register(self, step: StepName, handler: StepHandler) -> None:
        self._handlers[step] = handler

    def get(self, step: StepName) -> StepHandler | None:
        return self._handlers.get(step)

    def on_approve(self, step: StepName, hook: ApproveHook) -> None:
        """`hook` est appele a la validation ; il peut la refuser en levant une `PipelineError`."""
        self._approve_hooks[step] = hook

    def approve_hook(self, step: StepName) -> ApproveHook | None:
        return self._approve_hooks.get(step)

    def __contains__(self, step: object) -> bool:
        return step in self._handlers
