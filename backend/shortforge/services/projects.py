"""Archiver, restaurer et supprimer un projet.

Archiver est reversible : le projet disparait des listes et de « A valider », rien n'est efface.
Supprimer est definitif : les donnees du projet sont retirees de la base et son dossier
(`<donnees>/projects/<id>`) est efface. Les fichiers partages (bibliotheque musicale, logo, videos
longues importees) ne sont jamais touches, meme si le projet les utilisait.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shortforge.models import Asset, Project, PublishJob, SocialPost, utcnow

SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ProjectDeletionError(ValueError):
    """Suppression refusee ; le message est destine a l'utilisateur."""


@dataclass(frozen=True, slots=True)
class DeletionReport:
    title: str
    freed_bytes: int
    leftover: str  # dossier qui n'a pas pu etre efface (fichier ouvert...), sinon vide


def project_dir(data_dir: Path, project: Project) -> Path:
    """Dossier propre au projet, en refusant tout identifiant qui sortirait du dossier des projets."""
    if not SAFE_ID.match(project.id):
        raise ProjectDeletionError("Identifiant de projet inattendu : suppression des fichiers refusée.")
    root = (data_dir / "projects").resolve()
    folder = (root / project.id).resolve()
    if folder.parent != root:
        raise ProjectDeletionError("Dossier de projet inattendu : suppression des fichiers refusée.")
    return folder


def folder_size(folder: Path) -> tuple[int, int]:
    """(octets, nombre de fichiers) du dossier ; (0, 0) s'il n'existe pas."""
    if not folder.is_dir():
        return 0, 0
    sizes = [p.stat().st_size for p in folder.rglob("*") if p.is_file()]
    return sum(sizes), len(sizes)


def footprint(session: Session, data_dir: Path, project: Project) -> dict[str, Any]:
    """Ce que la suppression effacerait, et ce qu'elle ne peut pas annuler ailleurs."""
    size, files = folder_size(project_dir(data_dir, project))
    kinds = dict(session.execute(select(Asset.kind, func.count()).where(Asset.project_id == project.id)
                                 .group_by(Asset.kind)).all())
    scheduled = session.scalar(select(func.count()).select_from(SocialPost).where(
        SocialPost.project_id == project.id, SocialPost.status == "scheduled")) or 0
    youtube_scheduled = session.scalar(select(func.count()).select_from(PublishJob).where(
        PublishJob.project_id == project.id, PublishJob.scheduled_at.is_not(None))) or 0
    return {"project_id": project.id, "title": project.title, "bytes": size, "files": files,
            "images": kinds.get("image", 0), "videos": kinds.get("video", 0), "audio": kinds.get("audio", 0),
            "renders": kinds.get("render", 0), "scheduled_posts": int(scheduled) + int(youtube_scheduled),
            "archived": project.archived_at is not None}


def archive(session: Session, project: Project) -> Project:
    if project.archived_at is None:
        project.archived_at = utcnow()
        session.flush()
    return project


def unarchive(session: Session, project: Project) -> Project:
    if project.archived_at is not None:
        project.archived_at = None
        session.flush()
    return project


def delete_project(session: Session, data_dir: Path, project: Project, *, running: bool) -> DeletionReport:
    """Supprime definitivement. Refuse pendant qu'une etape tourne."""
    if running or any(step.status == "running" for step in project.steps):
        raise ProjectDeletionError("Une étape de ce projet est en cours : attends qu'elle se termine "
                                   "pour le supprimer.")
    folder = project_dir(data_dir, project)
    size, _ = folder_size(folder)
    title = project.title
    session.delete(project)  # les tables liees suivent (cles etrangeres en cascade)
    session.flush()
    leftover = ""
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
        if folder.exists():  # fichier ouvert ailleurs (lecteur video...) : on le dit plutot que d'echouer
            leftover = str(folder)
    return DeletionReport(title=title, freed_bytes=size, leftover=leftover)
