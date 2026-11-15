"""Moteurs video locaux executes par ComfyUI : ComfyUI generique, Wan 2.2, LTX Video, CogVideoX.

Chaque moteur utilise le workflow qui porte son identifiant (ex. `wan22_local.json`). Ils sont
gratuits : ils utilisent la carte graphique du PC.
"""

from __future__ import annotations

import random
import uuid
from pathlib import Path
from typing import Any

from shortforge.integrations.comfyui import ComfyUIClient, ComfyUIError, WorkflowLibrary, apply_inputs
from shortforge.providers.base import (
    JobState,
    JobStatus,
    Operation,
    ProviderError,
    VideoProvider,
    VideoRequest,
    vertical_size,
)


class ComfyUIWorkflowProvider(VideoProvider):
    kind = "local"
    operations = frozenset({Operation.TEXT, Operation.IMAGE, Operation.FIRST_LAST})
    min_duration_s = 1
    max_duration_s = 15
    resolutions = ("480p", "720p", "1080p")
    default_fps = 16

    def __init__(self, provider_id: str, name: str, client: ComfyUIClient, library: WorkflowLibrary,
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.id, self.name = provider_id, name
        self.client, self.library = client, library
        self.workflow_id = str(self.config.get("workflow", provider_id))

    def is_configured(self) -> bool:
        try:
            self.library.get(self.workflow_id)
        except ComfyUIError:
            return False
        return True

    def not_configured_message(self) -> str:
        return (f"Aucun workflow « {self.workflow_id} » pour {self.name} : exporte-le depuis ComfyUI "
                "(Workflow → Export (API)) et ajoute-le dans les paramètres.")

    def validate_parameters(self, request: VideoRequest, operation: Operation = Operation.TEXT) -> list[str]:
        errors = super().validate_parameters(request, operation)
        if (operation is Operation.FIRST_LAST and self.is_configured()
                and "last_image" not in self.library.get(self.workflow_id).inputs):
            errors.append(f"Le workflow « {self.workflow_id} » n'a pas d'entrée pour l'image de fin.")
        return errors

    def _submit(self, operation: Operation, request: VideoRequest) -> str:
        workflow, spec = self.library.load(self.workflow_id)
        width, height = vertical_size(request.resolution)
        fps = int(spec.defaults.get("fps", self.default_fps))
        values: dict[str, Any] = {
            "prompt": request.prompt, "negative_prompt": request.negative_prompt or None,
            "width": width, "height": height, "seed": request.seed if request.seed is not None
            else random.randint(0, 2**31 - 1), "duration_s": request.duration_s,
            "frames": round(request.duration_s * fps) + 1, "fps": fps,
        }
        if operation in (Operation.IMAGE, Operation.FIRST_LAST) and request.image_path:
            values["input_image"] = self.client.upload_image(Path(request.image_path))
        if operation is Operation.FIRST_LAST and request.last_frame_path:
            values["last_image"] = self.client.upload_image(Path(request.last_frame_path))
        try:
            return self.client.queue(apply_inputs(workflow, spec, values), uuid.uuid4().hex)
        except ComfyUIError as exc:
            raise ProviderError(str(exc)) from exc

    def get_status(self, job_id: str) -> JobStatus:
        try:
            entry = self.client.history(job_id)
        except ComfyUIError as exc:
            return JobStatus(JobState.FAILED, error=str(exc))
        if entry is None:
            return JobStatus(JobState.RUNNING)
        status = entry.get("status", {})
        if status.get("status_str") == "error":
            return JobStatus(JobState.FAILED, error="La génération a échoué dans ComfyUI.")
        if status.get("completed", True):
            return JobStatus(JobState.SUCCEEDED, progress=1.0)
        return JobStatus(JobState.RUNNING)

    def download_result(self, job_id: str, dest_dir: Path) -> Path:
        entry = self.client.history(job_id)
        if entry is None:
            raise ProviderError("Résultat ComfyUI introuvable.")
        files = self.client.outputs(entry)
        chosen = next((f for f in files if f.is_video), files[0] if files else None)
        if chosen is None:
            raise ProviderError("Le workflow n'a produit aucune vidéo (nœud de sauvegarde vidéo manquant ?).")
        return self.client.download(chosen, dest_dir)
