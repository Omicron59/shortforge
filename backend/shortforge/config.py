"""Configuration lue depuis l'environnement et le fichier `.env` local.

Aucune cle API n'est ecrite dans le code : elles sont toutes lues ici, en `SecretStr`,
pour ne jamais apparaitre en clair dans les journaux ni dans les reponses de l'API.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Reglages de l'application. Chaque champ correspond a une variable du `.env`."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    shortforge_data_dir: Path = Path("./data")
    shortforge_database_url: str = ""
    shortforge_host: str = "127.0.0.1"
    shortforge_port: int = 8787
    shortforge_language: str = "fr"
    # Jeton de session exige par l'API locale (fourni par l'application de bureau a chaque lancement).
    shortforge_api_token: SecretStr | None = None

    comfyui_url: str = "http://127.0.0.1:8000"
    comfyui_timeout_s: float = 1800
    comfyui_workflows_dir: Path | None = None  # workflows personnels (en plus de assets/workflows)
    comfyui_image_workflow: str = "image_default"
    image_width: int = 768
    image_height: int = 1344

    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = ""
    ollama_temperature: float = 0.8
    ollama_timeout_s: float = 300
    ffmpeg_path: str = "ffmpeg"

    provider_poll_interval_s: float = 5
    provider_timeout_s: float = 1200

    budget_max_per_scene: float = 0.50
    budget_max_per_short: float = 2.00
    budget_max_per_day: float = 5.00
    budget_max_per_month: float = 30.00

    gemini_api_key: SecretStr | None = None
    minimax_api_key: SecretStr | None = None
    kling_access_key: SecretStr | None = None
    kling_secret_key: SecretStr | None = None
    runway_api_key: SecretStr | None = None
    pika_api_key: SecretStr | None = None
    google_cloud_project: str = ""
    youtube_api_key: SecretStr | None = None  # tendances YouTube (lecture seule)
    trends_region: str = "FR"

    # Voix off : "auto" (Piper si configure, sinon la voix du systeme), "piper", "system" ou "elevenlabs".
    tts_engine: str = "auto"
    piper_path: str = "piper"
    piper_voice: str = ""  # fichier .onnx d'une voix Piper
    system_voice: str = ""  # nom d'une voix installee (Windows ou macOS) ; vide = voix par defaut
    elevenlabs_api_key: SecretStr | None = None
    elevenlabs_voice_id: str = ""
    elevenlabs_model: str = "eleven_multilingual_v2"
    elevenlabs_cost_per_1000_chars: float | None = None  # None = tarif inconnu : generation bloquee
    whisper_model: str = "small"  # faster-whisper (transcription locale, optionnelle)
    quality_min_score: float = 7.0  # note minimale du controle qualite pour publier

    # Publication sur TikTok et Instagram par Postiz (optionnel, desactive par defaut).
    social_publish_enabled: bool = False
    postiz_url: str = "https://api.postiz.com/public/v1"
    postiz_api_key: SecretStr | None = None

    youtube_publish_enabled: bool = False
    youtube_client_secrets_file: str = ""
    ai_disclosure_text: str = "Vidéo générée avec l'aide de l'IA."

    @field_validator("*", mode="before")
    @classmethod
    def _empty_means_unset(cls, value: Any, info: ValidationInfo) -> Any:
        """Une ligne `CLE=` vide dans le fichier de reglages = valeur non renseignee (None si permis)."""
        if value == "" and info.field_name in _OPTIONAL_FIELDS:
            return None
        return value

    @property
    def workflow_dirs(self) -> list[Path]:
        """Dossiers de workflows ComfyUI : ceux du projet, puis ceux de l'utilisateur."""
        dirs = [bundled_dir() / "assets" / "workflows", self.shortforge_data_dir / "workflows"]
        if self.comfyui_workflows_dir:
            dirs.append(self.comfyui_workflows_dir)
        return dirs

    @property
    def database_url(self) -> str:
        """URL SQLAlchemy ; par defaut un fichier SQLite dans le dossier de donnees."""
        if self.shortforge_database_url:
            return self.shortforge_database_url
        return f"sqlite:///{(self.shortforge_data_dir / 'shortforge.sqlite3').as_posix()}"


def env_file_path() -> Path:
    """Fichier de reglages : SHORTFORGE_ENV_FILE (application installee) ou `.env` du dossier courant."""
    return Path(os.environ.get("SHORTFORGE_ENV_FILE", ".env"))


def bundled_dir() -> Path:
    """Dossier des fichiers fournis avec l'application (racine du depot, ou paquet PyInstaller)."""
    frozen = getattr(sys, "_MEIPASS", None)
    return Path(frozen) if frozen else Path(__file__).resolve().parents[2]


@lru_cache
def get_settings() -> Settings:
    """Reglages charges une seule fois par processus."""
    return Settings(_env_file=env_file_path())


_OPTIONAL_FIELDS = frozenset(name for name, field in Settings.model_fields.items()
                             if field.default is None)
