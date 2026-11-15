"""Google : Gemini Omni 1.2 Flash (option economique) et Veo 3 / Veo 3 Fast (options premium).

Appels a l'API Gemini en mode « operation longue » : `models/{modele}:predictLongRunning`, puis
interrogation de l'operation et telechargement de la video. Les identifiants de modele sont
reglables (champ `model` de la configuration du fournisseur) : verifie-les dans la
documentation Google avant le premier usage, ils changent a chaque nouvelle version.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shortforge.providers.base import JobState, JobStatus, Operation, ProviderError, VideoRequest, file_base64
from shortforge.providers.http_base import HttpVideoProvider


class GoogleVideoProvider(HttpVideoProvider):
    base_url = "https://generativelanguage.googleapis.com/v1beta"
    operations = frozenset({Operation.TEXT, Operation.IMAGE, Operation.FIRST_LAST})
    resolutions = ("720p", "1080p")
    default_model = ""

    def headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key}

    @property
    def model(self) -> str:
        return str(self.config.get("model", self.default_model))

    def _submit(self, operation: Operation, request: VideoRequest) -> str:
        instance: dict[str, Any] = {"prompt": request.prompt}
        if operation in (Operation.IMAGE, Operation.FIRST_LAST) and request.image_path:
            content, mime = file_base64(Path(request.image_path))
            instance["image"] = {"bytesBase64Encoded": content, "mimeType": mime}
        if operation is Operation.FIRST_LAST and request.last_frame_path:
            content, mime = file_base64(Path(request.last_frame_path))
            instance["lastFrame"] = {"bytesBase64Encoded": content, "mimeType": mime}
        parameters: dict[str, Any] = {"aspectRatio": request.aspect_ratio, "resolution": request.resolution,
                                      "durationSeconds": int(self.billed_duration(request.duration_s))}
        if request.negative_prompt:
            parameters["negativePrompt"] = request.negative_prompt
        if request.seed is not None:
            parameters["seed"] = request.seed
        data = self.request("POST", f"/models/{self.model}:predictLongRunning",
                            json={"instances": [instance], "parameters": parameters})
        name = data.get("name")
        if not name:
            raise ProviderError(f"{self.name} n'a pas renvoyé d'identifiant de génération.")
        return str(name)

    def get_status(self, job_id: str) -> JobStatus:
        data = self.request("GET", f"/{job_id}")
        if not data.get("done"):
            return JobStatus(JobState.RUNNING)
        if error := data.get("error"):
            return JobStatus(JobState.FAILED, error=f"{self.name} : {error.get('message', 'erreur inconnue')}")
        response = data.get("response", {}).get("generateVideoResponse", {})
        samples = response.get("generatedSamples") or []
        if not samples:
            reasons = response.get("raiMediaFilteredReasons") or ["aucune vidéo renvoyée"]
            return JobStatus(JobState.FAILED, error=f"{self.name} a refusé la génération : {'; '.join(reasons)}")
        return JobStatus(JobState.SUCCEEDED, progress=1.0, result={"uri": samples[0]["video"]["uri"]})

    def download_result(self, job_id: str, dest_dir: Path) -> Path:
        status = self.get_status(job_id)
        if status.state is not JobState.SUCCEEDED:
            raise ProviderError(status.error or "La vidéo n'est pas encore prête.")
        return self.download_url(status.result["uri"], dest_dir, f"{job_id.rsplit('/', 1)[-1]}.mp4", auth=True)


class GeminiOmniFlashProvider(GoogleVideoProvider):
    """Gemini Omni 1.2 Flash : 3 a 15 s par pas d'1 s, 0,07 $/s en 720p (annonce du 05/11/2026)."""

    id, name = "gemini_omni_12_flash", "Gemini Omni 1.2 Flash"
    default_model = "gemini-omni-1.2-flash"
    min_duration_s, max_duration_s = 3, 15


class Veo3FastProvider(GoogleVideoProvider):
    id, name = "veo3_fast", "Veo 3 Fast"
    default_model = "veo-3.0-fast-generate-001"
    allowed_durations = (4.0, 6.0, 8.0)
    min_duration_s, max_duration_s = 4, 8
    operations = frozenset({Operation.TEXT, Operation.IMAGE})


class Veo3Provider(Veo3FastProvider):
    id, name = "veo3", "Veo 3"
    default_model = "veo-3.0-generate-001"
