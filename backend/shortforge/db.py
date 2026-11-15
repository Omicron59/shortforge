"""Connexion SQLite et sessions SQLAlchemy 2."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Classe de base de tous les modeles."""


def _enable_sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


class Database:
    """Moteur et fabrique de sessions. Une instance par application."""

    def __init__(self, url: str) -> None:
        self.url = url
        connect_args: dict[str, Any] = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
            path = url.removeprefix("sqlite:///")
            if path and path != ":memory:" and not url.startswith("sqlite:///:memory:"):
                Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(url, connect_args=connect_args)
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", _enable_sqlite_pragmas)
        self._factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def create_all(self) -> None:
        """Cree les tables manquantes (les migrations viendront avec Alembic)."""
        from shortforge import models  # noqa: F401  (enregistre les modeles)

        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Session transactionnelle : commit en fin de bloc, rollback en cas d'erreur."""
        session = self._factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
