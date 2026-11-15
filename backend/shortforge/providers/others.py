"""Fournisseurs externes : Hailuo / MiniMax, Kling, Runway et Pika.

Les noms de modeles et les adresses sont reglables dans la configuration de chaque fournisseur
(`model`, `base_url`) : verifie-les dans la documentation officielle avant le premier usage.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Any

from shortforge.providers.base import (
    JobState,
    JobStatus,
    Operation,
    ProviderError,
    ProviderNotConfiguredError,
    VideoProvider,
    VideoRequest,
    data_uri,
    file_base64,
)
from shortforge.providers.http_base import HttpVideoProvider


class MiniMaxProvider(HttpVideoProvider):
    """Hailuo / MiniMax : `POST /v1/video_generation`, suivi par `task_id`, fichier par `file_id`."""

    id, name = "hailuo_fast", "Hailuo / MiniMax"
    base_url = "https://api.minimax.io"
    operations = frozenset({Operation.TEXT, Operation.IMAGE, Operation.FIRST_LAST})
    allowed_durations = (6.0, 10.0)
    min_duration_s, max_duration_s = 6, 10
    resolutions = ("720p", "1080p")

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _submit(self, operation: Operation, request: VideoRequest) -> str:
        body: dict[str, Any] = {
            "model": self.config.get("model", "MiniMax-Hailuo-02"), "prompt": request.prompt,
            "duration": int(self.billed_duration(request.duration_s)),
            "resolution": "1080P" if request.resolution == "1080p" else "768P",
        }
        if operation in (Operation.IMAGE, Operation.FIRST_LAST) and request.image_path:
            body["first_frame_image"] = data_uri(Path(request.image_path))
        if operation is Operation.FIRST_LAST and request.last_frame_path:
            body["last_frame_image"] = data_uri(Path(request.last_frame_path))
        data = self.request("POST", "/v1/video_generation", json=body)
        self._check(data)
        return str(data["task_id"])

    def get_status(self, job_id: str) -> JobStatus:
        data = self.request("GET", "/v1/query/video_generation", params={"task_id": job_id})
        self._check(data)
        status = str(data.get("status", ""))
        if status == "Success":
            return JobStatus(JobState.SUCCEEDED, progress=1.0, result={"file_id": data.get("file_id")})
        if status == "Fail":
            return JobStatus(JobState.FAILED, error=f"{self.name} : génération échouée.")
        return JobStatus(JobState.QUEUED if status in ("Queueing", "Preparing") else JobState.RUNNING)

    def download_result(self, job_id: str, dest_dir: Path) -> Path:
        status = self.get_status(job_id)
        if status.state is not JobState.SUCCEEDED:
            raise ProviderError(status.error or "La vidéo n'est pas encore prête.")
        data = self.request("GET", "/v1/files/retrieve", params={"file_id": status.result["file_id"]})
        url = data.get("file", {}).get("download_url")
        if not url:
            raise ProviderError(f"{self.name} n'a pas renvoyé de lien de téléchargement.")
        return self.download_url(url, dest_dir, f"minimax_{job_id}.mp4")

    def _check(self, data: dict[str, Any]) -> None:
        base = data.get("base_resp") or {}
        if base.get("status_code", 0) != 0:
            raise ProviderError(f"{self.name} : {base.get('status_msg', 'erreur inconnue')}")


class KlingProvider(HttpVideoProvider):
    """Kling : authentification par jeton JWT signe avec la cle d'acces et la cle secrete."""

    id, name = "kling", "Kling"
    base_url = "https://api-singapore.klingai.com"
    operations = frozenset({Operation.TEXT, Operation.IMAGE, Operation.FIRST_LAST})
    allowed_durations = (5.0, 10.0)
    min_duration_s, max_duration_s = 5, 10
    resolutions = ("720p", "1080p")

    def __init__(self, *, secret_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.secret_key = secret_key or ""

    def is_configured(self) -> bool:
        return bool(self.api_key and self.secret_key)

    def not_configured_message(self) -> str:
        return "Kling n'est pas configuré : ajoute KLING_ACCESS_KEY et KLING_SECRET_KEY dans le fichier .env."

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token()}"}

    def token(self, now: float | None = None) -> str:
        """Jeton JWT HS256 valable 30 minutes."""
        now = time.time() if now is None else now
        header = {"alg": "HS256", "typ": "JWT"}
        payload = {"iss": self.api_key, "exp": int(now) + 1800, "nbf": int(now) - 5}
        signing_input = f"{_b64url(json.dumps(header).encode())}.{_b64url(json.dumps(payload).encode())}"
        signature = hmac.new(self.secret_key.encode(), signing_input.encode(), hashlib.sha256).digest()
        return f"{signing_input}.{_b64url(signature)}"

    def _submit(self, operation: Operation, request: VideoRequest) -> str:
        kind = "text2video" if operation is Operation.TEXT else "image2video"
        body: dict[str, Any] = {
            "model_name": self.config.get("model", "kling-v2-1"), "prompt": request.prompt,
            "negative_prompt": request.negative_prompt, "aspect_ratio": request.aspect_ratio,
            "duration": str(int(self.billed_duration(request.duration_s))),
            "mode": "pro" if request.resolution == "1080p" else "std",
        }
        if operation in (Operation.IMAGE, Operation.FIRST_LAST) and request.image_path:
            body["image"] = file_base64(Path(request.image_path))[0]
        if operation is Operation.FIRST_LAST and request.last_frame_path:
            body["image_tail"] = file_base64(Path(request.last_frame_path))[0]
        data = self.request("POST", f"/v1/videos/{kind}", json=body)
        self._check(data)
        return f"{kind}:{data['data']['task_id']}"

    def get_status(self, job_id: str) -> JobStatus:
        kind, task_id = job_id.split(":", 1)
        data = self.request("GET", f"/v1/videos/{kind}/{task_id}")
        self._check(data)
        task = data.get("data", {})
        state = task.get("task_status")
        if state == "succeed":
            videos = task.get("task_result", {}).get("videos") or []
            if not videos:
                return JobStatus(JobState.FAILED, error="Kling n'a renvoyé aucune vidéo.")
            return JobStatus(JobState.SUCCEEDED, progress=1.0, result={"url": videos[0]["url"]})
        if state == "failed":
            return JobStatus(JobState.FAILED, error=f"Kling : {task.get('task_status_msg', 'génération échouée')}")
        return JobStatus(JobState.QUEUED if state == "submitted" else JobState.RUNNING)

    def download_result(self, job_id: str, dest_dir: Path) -> Path:
        status = self.get_status(job_id)
        if status.state is not JobState.SUCCEEDED:
            raise ProviderError(status.error or "La vidéo n'est pas encore prête.")
        return self.download_url(status.result["url"], dest_dir, f"kling_{job_id.split(':', 1)[1]}.mp4")

    def _check(self, data: dict[str, Any]) -> None:
        if data.get("code", 0) != 0:
            raise ProviderError(f"Kling : {data.get('message', 'erreur inconnue')}")


class RunwayProvider(HttpVideoProvider):
    """Runway : image vers video (`/v1/image_to_video`), suivi par `/v1/tasks/{id}`."""

    id, name = "runway", "Runway"
    base_url = "https://api.dev.runwayml.com"
    operations = frozenset({Operation.IMAGE})
    allowed_durations = (5.0, 10.0)
    min_duration_s, max_duration_s = 5, 10

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}",
                "X-Runway-Version": str(self.config.get("api_version", "2024-11-06"))}

    def _submit(self, operation: Operation, request: VideoRequest) -> str:
        body: dict[str, Any] = {
            "model": self.config.get("model", "gen4_turbo"), "promptText": request.prompt,
            "promptImage": data_uri(Path(request.image_path)) if request.image_path else None,
            "ratio": "720:1280", "duration": int(self.billed_duration(request.duration_s)),
        }
        if request.seed is not None:
            body["seed"] = request.seed
        data = self.request("POST", "/v1/image_to_video", json=body)
        if not data.get("id"):
            raise ProviderError("Runway n'a pas renvoyé d'identifiant de tâche.")
        return str(data["id"])

    def get_status(self, job_id: str) -> JobStatus:
        data = self.request("GET", f"/v1/tasks/{job_id}")
        state = data.get("status")
        if state == "SUCCEEDED":
            output = data.get("output") or []
            if not output:
                return JobStatus(JobState.FAILED, error="Runway n'a renvoyé aucune vidéo.")
            return JobStatus(JobState.SUCCEEDED, progress=1.0, result={"url": output[0]})
        if state in ("FAILED", "CANCELLED"):
            return JobStatus(JobState.FAILED, error=f"Runway : {data.get('failure', 'génération échouée')}")
        return JobStatus(JobState.RUNNING if state == "RUNNING" else JobState.QUEUED,
                         progress=float(data.get("progress") or 0))

    def download_result(self, job_id: str, dest_dir: Path) -> Path:
        status = self.get_status(job_id)
        if status.state is not JobState.SUCCEEDED:
            raise ProviderError(status.error or "La vidéo n'est pas encore prête.")
        return self.download_url(status.result["url"], dest_dir, f"runway_{job_id}.mp4")


class PikaProvider(VideoProvider):
    """Pika : aucune API publique verifiee a ce jour. Le moteur est liste mais pas encore utilisable."""

    id, name = "pika_h3_flex", "Pika H3 Flex"
    operations = frozenset({Operation.TEXT, Operation.IMAGE})
    MESSAGE = "Pika H3 Flex n'est pas encore disponible : aucune API publique vérifiée pour ce moteur."

    def is_configured(self) -> bool:
        return False

    def not_configured_message(self) -> str:
        return self.MESSAGE

    def _submit(self, operation: Operation, request: VideoRequest) -> str:
        raise ProviderNotConfiguredError(self.MESSAGE)

    def get_status(self, job_id: str) -> JobStatus:
        raise ProviderNotConfiguredError(self.MESSAGE)

    def download_result(self, job_id: str, dest_dir: Path) -> Path:
        raise ProviderNotConfiguredError(self.MESSAGE)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
