"""Lancement du backend : `python -m shortforge` (processus local ou sidecar Tauri)."""

from __future__ import annotations

import uvicorn

from shortforge.config import get_settings
from shortforge.main import create_app


def main() -> None:
    settings = get_settings()
    uvicorn.run(create_app(settings), host=settings.shortforge_host, port=settings.shortforge_port)


if __name__ == "__main__":
    main()
