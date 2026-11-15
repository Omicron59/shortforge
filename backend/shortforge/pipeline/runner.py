"""Execution des etapes en arriere-plan (une seule a la fois par projet)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from shortforge.config import Settings
from shortforge.db import Database
from shortforge.pipeline.engine import PipelineError, PipelineService
from shortforge.pipeline.handlers import HandlerRegistry

logger = logging.getLogger("shortforge.runner")


class PipelineRunner:
    def __init__(self, db: Database, settings: Settings, registry: HandlerRegistry, workers: int = 2) -> None:
        self.db, self.settings, self.registry = db, settings, registry
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="shortforge-step")
        self._running: set[str] = set()
        self._lock = threading.Lock()

    def submit(self, project_id: str, *, autopilot: bool = False) -> bool:
        """Lance l'etape suivante du projet ; False si une etape de ce projet tourne deja.

        `autopilot` : enchaine les etapes automatiques jusqu'a la prochaine validation humaine
        (ou un echec). Les validations restent toujours humaines.
        """
        with self._lock:
            if project_id in self._running:
                return False
            self._running.add(project_id)
        target = self._autopilot if autopilot else self._run
        future: Future[None] = self._executor.submit(target, project_id)
        future.add_done_callback(lambda _: self._release(project_id))
        return True

    def submit_task(self, key: str, task: Callable[[], None]) -> bool:
        """Tache longue hors pipeline (transcription d'une video...), une seule a la fois par cle."""
        with self._lock:
            if key in self._running:
                return False
            self._running.add(key)
        future: Future[None] = self._executor.submit(self._guard, task)
        future.add_done_callback(lambda _: self._release(key))
        return True

    def is_running(self, project_id: str) -> bool:
        with self._lock:
            return project_id in self._running

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(self, project_id: str) -> None:
        try:
            with self.db.session() as session:
                PipelineService(session, self.settings, self.registry).advance(project_id)
        except PipelineError as exc:
            logger.info("Étape non lancée pour %s : %s", project_id, exc)
        except Exception:
            logger.exception("Erreur inattendue pendant une étape du projet %s", project_id)

    def _autopilot(self, project_id: str, max_steps: int = 20) -> None:
        for _ in range(max_steps):
            try:
                with self.db.session() as session:
                    step = PipelineService(session, self.settings, self.registry).advance(project_id)
                    status = step.status
            except PipelineError as exc:
                logger.info("Pilote automatique arrêté pour %s : %s", project_id, exc)
                return
            except Exception:
                logger.exception("Erreur inattendue (pilote automatique) pour %s", project_id)
                return
            if status != "done":
                return

    @staticmethod
    def _guard(task: Callable[[], None]) -> None:
        try:
            task()
        except Exception:
            logger.exception("Erreur dans une tâche de fond")

    def _release(self, project_id: str) -> None:
        with self._lock:
            self._running.discard(project_id)
