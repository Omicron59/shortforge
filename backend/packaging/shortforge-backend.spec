# -*- mode: python ; coding: utf-8 -*-
# Moteur local de ShortForge empaquete pour l'application de bureau (Windows et macOS).
# Construction : cd backend && pyinstaller packaging/shortforge-backend.spec --noconfirm
# Sortie : dist/shortforge-backend/ (dossier copie dans les ressources de l'application Tauri).
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parents[1]
datas = [(str(ROOT / "assets" / "workflows"), "assets/workflows"), (str(ROOT / ".env.example"), "."),
         # Alembic lit les scripts de migration sur le disque (pas dans l'archive Python).
         (str(ROOT / "backend" / "shortforge" / "migrations"), "shortforge/migrations")]
binaries = []
hiddenimports = (collect_submodules("uvicorn") + collect_submodules("shortforge") + collect_submodules("alembic")
                 + collect_submodules("keyring.backends"))  # trousseau Windows, macOS et Linux
for package in ("faster_whisper", "ctranslate2", "onnxruntime", "av", "tokenizers"):
    try:
        d, b, h = collect_all(package)
    except Exception:  # transcription facultative : paquet absent
        continue
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis([str(Path(SPECPATH) / "entry.py")], pathex=[str(ROOT / "backend")], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, excludes=["tkinter", "matplotlib", "pytest", "mypy", "ruff"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="shortforge-backend", console=False,
          upx=False, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, name="shortforge-backend", upx=False)
