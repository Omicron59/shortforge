"""Interface commune `VideoProvider` : tous les moteurs video, locaux ou externes, la respectent.

Un fournisseur ne fait que soumettre un travail, en suivre l'etat et telecharger le resultat.
Le budget, les confirmations de cout et l'enregistrement en base sont geres AU-DESSUS, par
`services/production.py`, pour qu'aucun fournisseur ne puisse depenser sans controle.
"""

from __future__ import annotations

import base64
import mimetypes
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Operation(StrEnum):
    TEXT = "generate_from_text"
    IMAGE = "generate_from_image"
    FIRST_LAST = "generate_from_first_and_last_frame"
    EDIT = "edit_video"


OPERATION_LABELS = {
    Operation.TEXT: "texte vers vidéo",
    Operation.IMAGE: "image vers vidéo",
    Operation.FIRST_LAST: "première et dernière image",
    Operation.EDIT: "modification de vidéo",
}


class VideoRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    duration_s: float = Field(default=5, gt=0)
    aspect_ratio: str = "9:16"
    resolution: str = "720p"
    seed: int | None = None
    image_path: Path | None = None
    last_frame_path: Path | None = None
    video_path: Path | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(slots=True)
class JobStatus:
    state: JobState
    progress: float = 0.0
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict)

    @property
    def finished(self) -> bool:
        return self.state in (JobState.SUCCEEDED, JobState.FAILED)


class ProviderError(RuntimeError):
    """Erreur d'un fournisseur ; le message est destine a l'utilisateur."""


class UnsupportedOperationError(ProviderError):
    pass


class ProviderNotConfiguredError(ProviderError):
    pass


class VideoProvider(ABC):
    """Base de tous les moteurs video."""

    id: str = ""
    name: str = ""
    kind: str = "external"  # local | external
    operations: frozenset[Operation] = frozenset()
    min_duration_s: float = 1
    max_duration_s: float = 15
    allowed_durations: tuple[float, ...] = ()  # vide = toute duree entre min et max
    resolutions: tuple[str, ...] = ("720p",)

    def __init__(self, *, cost_per_second_usd: float | None = None, config: dict[str, Any] | None = None) -> None:
        self.cost_per_second_usd = cost_per_second_usd
        self.config = config or {}

    # ── Interface commune ──

    def generate_from_text(self, request: VideoRequest) -> str:
        return self._start(Operation.TEXT, request)

    def generate_from_image(self, request: VideoRequest) -> str:
        return self._start(Operation.IMAGE, request)

    def generate_from_first_and_last_frame(self, request: VideoRequest) -> str:
        return self._start(Operation.FIRST_LAST, request)

    def edit_video(self, request: VideoRequest) -> str:
        return self._start(Operation.EDIT, request)

    def estimate_cost(self, request: VideoRequest) -> float | None:
        """Cout estime en dollars ; `None` si le tarif n'est pas configure. Toujours 0 en local."""
        if self.kind == "local":
            return 0.0
        if self.cost_per_second_usd is None:
            return None
        return round(self.cost_per_second_usd * self.billed_duration(request.duration_s), 4)

    def validate_parameters(self, request: VideoRequest, operation: Operation = Operation.TEXT) -> list[str]:
        """Problemes qui empechent la generation (liste vide = tout est bon)."""
        errors: list[str] = []
        if not self.is_configured():
            errors.append(self.not_configured_message())
        if operation not in self.operations:
            errors.append(f"{self.name} ne gère pas : {OPERATION_LABELS[operation]}.")
        if not request.prompt.strip() and operation is not Operation.EDIT:
            errors.append("Le prompt est vide.")
        if self.allowed_durations:  # une duree plus courte est facturee a la duree autorisee suivante
            if request.duration_s > max(self.allowed_durations):
                values = ", ".join(f"{d:g}" for d in self.allowed_durations)
                errors.append(f"{self.name} accepte seulement ces durées : {values} secondes.")
        elif not self.min_duration_s <= request.duration_s <= self.max_duration_s:
            errors.append(f"{self.name} accepte de {self.min_duration_s:g} à {self.max_duration_s:g} secondes.")
        if request.resolution not in self.resolutions:
            errors.append(f"Résolution {request.resolution} non gérée par {self.name} ({', '.join(self.resolutions)}).")
        required = {Operation.IMAGE: ["image_path"], Operation.FIRST_LAST: ["image_path", "last_frame_path"],
                    Operation.EDIT: ["video_path"]}.get(operation, [])
        for attr in required:
            path = getattr(request, attr)
            if path is None:
                errors.append({"image_path": "Image de départ manquante.", "last_frame_path": "Image de fin manquante.",
                               "video_path": "Vidéo à modifier manquante."}[attr])
            elif not Path(path).exists():
                errors.append(f"Fichier introuvable : {path}.")
        return errors

    @abstractmethod
    def get_status(self, job_id: str) -> JobStatus: ...

    @abstractmethod
    def download_result(self, job_id: str, dest_dir: Path) -> Path: ...

    # ── Aides ──

    def is_configured(self) -> bool:
        return True

    def not_configured_message(self) -> str:
        return f"{self.name} n'est pas configuré : ajoute sa clé API dans le fichier .env."

    def billed_duration(self, duration_s: float) -> float:
        """Duree facturee : la plus petite duree autorisee qui couvre la demande."""
        if self.allowed_durations:
            return next((d for d in sorted(self.allowed_durations) if d >= duration_s), max(self.allowed_durations))
        return duration_s

    def wait(self, job_id: str, *, poll_interval_s: float = 5, timeout_s: float = 1200,
             sleep: Callable[[float], None] = time.sleep,
             on_progress: Callable[[JobStatus], None] | None = None) -> JobStatus:
        """Attend la fin d'un travail en interrogeant `get_status`."""
        deadline = time.monotonic() + timeout_s
        while True:
            status = self.get_status(job_id)
            if on_progress:
                on_progress(status)
            if status.finished:
                return status
            if time.monotonic() > deadline:
                raise ProviderError(f"{self.name} met trop de temps : génération abandonnée.")
            sleep(poll_interval_s)

    def _start(self, operation: Operation, request: VideoRequest) -> str:
        errors = self.validate_parameters(request, operation)
        if errors:
            if operation not in self.operations:
                raise UnsupportedOperationError(" ".join(errors))
            if not self.is_configured():
                raise ProviderNotConfiguredError(" ".join(errors))
            raise ProviderError(" ".join(errors))
        return self._submit(operation, request)

    @abstractmethod
    def _submit(self, operation: Operation, request: VideoRequest) -> str: ...


def file_base64(path: Path) -> tuple[str, str]:
    """(contenu en base64, type MIME) d'un fichier local."""
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return base64.b64encode(path.read_bytes()).decode("ascii"), mime


def data_uri(path: Path) -> str:
    content, mime = file_base64(path)
    return f"data:{mime};base64,{content}"


def vertical_size(resolution: str) -> tuple[int, int]:
    """Dimensions 9:16 (multiples de 16) pour une resolution."""
    return {"480p": (480, 832), "720p": (720, 1280), "1080p": (1080, 1920)}.get(resolution, (720, 1280))
