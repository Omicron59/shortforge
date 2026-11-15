"""Lancement du backend : `python -m shortforge`, ou par l'application de bureau (moteur integre).

L'application installee indique ou ranger les donnees (SHORTFORGE_DATA_DIR) et le fichier de
reglages (SHORTFORGE_ENV_FILE). Au premier lancement, un fichier de reglages commente est cree a
partir du modele `.env.example` (publication desactivee, aucune cle).
"""

from __future__ import annotations

import logging
import shutil
import sys

import uvicorn

from shortforge.config import bundled_dir, env_file_path, get_settings
from shortforge.main import create_app


def ensure_env_file() -> None:
    target = env_file_path()
    if target.exists():
        return
    template = bundled_dir() / ".env.example"
    if template.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(template, target)


def main() -> None:
    if getattr(sys, "frozen", False):  # application installee : journal simple, pas de console
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
    ensure_env_file()
    settings = get_settings()
    settings.shortforge_data_dir.mkdir(parents=True, exist_ok=True)
    uvicorn.run(create_app(settings), host=settings.shortforge_host, port=settings.shortforge_port,
                log_config=None if getattr(sys, "frozen", False) else uvicorn.config.LOGGING_CONFIG)


if __name__ == "__main__":
    main()
