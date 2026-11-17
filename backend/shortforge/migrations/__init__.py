"""Migrations de la base (Alembic), avec sauvegarde avant tout changement.

- Base neuve : les tables sont creees d'un coup et marquees a la derniere version.
- Base d'une version 0.5.x (sans numero de version) : marquee `0001`, puis mise a niveau.
- Avant chaque mise a niveau, le fichier SQLite est copie dans `sauvegardes/` et la copie est verifiee.
  Si la copie echoue, rien n'est modifie.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import inspect

from shortforge.db import Database

logger = logging.getLogger("shortforge.migrations")
BASELINE = "0001"
SCRIPTS = Path(__file__).resolve().parent


class MigrationError(RuntimeError):
    """La base n'a pas pu etre mise a niveau ; le message est destine a l'utilisateur."""


@dataclass(frozen=True, slots=True)
class MigrationReport:
    previous: str | None
    current: str
    backup: Path | None


def _config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(SCRIPTS))
    return config


def sqlite_file(url: str) -> Path | None:
    """Fichier SQLite derriere l'URL, ou None (base en memoire, autre moteur)."""
    if not url.startswith("sqlite:///") or ":memory:" in url:
        return None
    return Path(url.removeprefix("sqlite:///"))


def backup_database(db: Database, folder: Path, label: str) -> Path | None:
    """Copie coherente de la base (API de sauvegarde SQLite), verifiee avant d'etre rendue."""
    source = sqlite_file(db.url)
    if source is None or not source.is_file():
        return None
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"shortforge-avant-migration-{label}-{datetime.now():%Y%m%d-%H%M%S}.sqlite3"
    src, dst = sqlite3.connect(source), sqlite3.connect(target)
    try:
        src.backup(dst)
        verdict = dst.execute("PRAGMA integrity_check").fetchone()
    finally:
        src.close()
        dst.close()
    if not verdict or verdict[0] != "ok":
        target.unlink(missing_ok=True)
        raise MigrationError("La sauvegarde de la base a échoué : la mise à niveau est annulée, rien n'a été modifié.")
    return target


def migrate(db: Database, backup_dir: Path) -> MigrationReport:
    config = _config()
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise MigrationError("Aucune migration trouvée dans l'application.")
    with db.engine.connect() as connection:
        tables = set(inspect(connection).get_table_names()) - {"alembic_version"}
        current = MigrationContext.configure(connection).get_current_revision()

    def run(action: str, revision: str) -> None:
        with db.engine.begin() as connection:
            config.attributes["connection"] = connection
            getattr(command, action)(config, revision)

    if not tables:  # premiere installation
        db.create_all()
        run("stamp", head)
        return MigrationReport(previous=None, current=head, backup=None)
    previous = current
    if current is None:  # base creee par une version 0.5.x
        run("stamp", BASELINE)
        current = BASELINE
    if current == head:
        return MigrationReport(previous=previous, current=head, backup=None)
    backup = backup_database(db, backup_dir, current)
    try:
        run("upgrade", head)
    except CommandError as exc:
        raise MigrationError("Cette base vient d'une version plus récente de ShortForge : installe la dernière "
                             f"version. ({exc})") from exc
    logger.warning("Base mise à niveau de %s vers %s (sauvegarde : %s).", current, head, backup)
    return MigrationReport(previous=previous, current=head, backup=backup)
