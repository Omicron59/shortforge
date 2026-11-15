"""Bibliotheque de musiques personnelle et choix de la musique d'un Short.

Seules les musiques dont tu as confirme les droits (libres de droits ou sous licence) sont
utilisables. Aucune musique n'est telechargee automatiquement.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.media import MediaToolError, duration_of
from shortforge.models import Asset, MusicTrack, Project
from shortforge.services.production import ProductionError

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


class MusicError(ProductionError):
    """Erreur de musique ; le message est destine a l'utilisateur."""


def add_track(session: Session, settings: Settings, *, filename: str, content: bytes, title: str, license: str,
              rights_confirmed: bool, mood: str = "", volume: float = 0.15) -> MusicTrack:
    if not rights_confirmed:
        raise MusicError("Confirme que tu as le droit d'utiliser cette musique (libre de droits ou sous licence).")
    ext = Path(filename).suffix.lower()
    if ext not in AUDIO_EXTENSIONS:
        raise MusicError("Format audio non pris en charge (mp3, wav, m4a, aac, ogg ou flac).")
    folder = settings.shortforge_data_dir / "music"
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.-]+", "_", Path(filename).stem)[:60] or "musique"
    path = folder / f"{safe}{ext}"
    i = 1
    while path.exists():
        path = folder / f"{safe}_{i}{ext}"
        i += 1
    path.write_bytes(content)
    try:
        duration_of(settings, path)
    except MediaToolError as exc:
        path.unlink(missing_ok=True)
        raise MusicError("Fichier audio illisible.") from exc
    track = MusicTrack(title=title.strip() or safe, path=str(path), mood=mood.strip(), license=license.strip(),
                       rights_confirmed=True, volume=max(0.0, min(1.0, volume)))
    session.add(track)
    session.flush()
    return track


def set_default(session: Session, track_id: str | None) -> None:
    for track in session.scalars(select(MusicTrack)):
        track.is_default = track.id == track_id
    session.flush()


def delete_track(session: Session, track_id: str) -> None:
    track = session.get(MusicTrack, track_id)
    if track is None:
        raise MusicError("Musique introuvable.")
    session.delete(track)
    session.flush()


def select_music(session: Session, project: Project) -> dict[str, Any]:
    """Etape select_music : la musique par defaut de la bibliotheque, s'il y en a une."""
    track = session.scalars(select(MusicTrack).where(MusicTrack.is_default.is_(True),
                                                     MusicTrack.rights_confirmed.is_(True))).first()
    if track is None or not Path(track.path).is_file():
        return {"skipped": True, "message": "Pas de musique : ajoute-en une dans Paramètres → Musiques."}
    session.add(Asset(project_id=project.id, kind="music", path=track.path, mime_type="audio/*", origin="imported",
                      license=track.license, rights_confirmed=True))
    session.flush()
    return {"music": track.title, "license": track.license, "volume": track.volume}
