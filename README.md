# ShortForge

Application Windows **open source** (licence MIT) pour créer des YouTube Shorts avec l'IA, **en local** sur ton PC : idées, script, images et vidéos via ComfyUI et ta carte graphique, voix off, sous-titres, montage vertical 1080x1920, puis brouillon YouTube.

Tu choisis pour chaque Short, ou pour chaque scène, entre des moteurs vidéo **locaux gratuits** (ComfyUI, Wan 2.2, LTX Video, CogVideoX) et des **fournisseurs externes payants** (Gemini Omni 1.2 Flash, Kling, Hailuo/MiniMax, Runway, Pika, Veo 3), avec un budget qui bloque toute dépense non prévue.

> **État : chaîne complète de l'idée au MP4, publication YouTube gardée.** Idées et scripts avec Ollama, images et vidéos avec ComfyUI ou 11 moteurs, budget avec confirmation de chaque dépense, montage FFmpeg 1080x1920 avec sous-titres, validation humaine obligatoire, brouillon YouTube et vérification finale, interface Tauri en français. Publication désactivée par défaut. Restent : voix off, minutage Whisper, musique et miniature. Voir [ROADMAP](docs/ROADMAP.md).

## Règles du projet

- **Aucune publication sans validation humaine explicite.** La publication YouTube est désactivée par défaut (`YOUTUBE_PUBLISH_ENABLED=false`).
- Les clés API restent dans le fichier `.env` local, jamais dans le code.
- Chaque étape du pipeline est enregistrée dans SQLite : un projet interrompu reprend là où il s'était arrêté.
- Les tendances servent d'inspiration, jamais de source à recopier ; aucune vidéo YouTube n'est copiée.
- Pas de contenu violent, sexuel, haineux, illégal ou trompeur. Voir [YOUTUBE_POLICY](docs/YOUTUBE_POLICY.md).

## Le pipeline

```text
generate_ideas → select_idea* → write_script → approve_script* → create_storyboard
→ generate_images → generate_videos → generate_voice → create_subtitles → select_music
→ render_video → review_preview* → approve_final_render* → create_youtube_draft → publish*
```

`*` = étape de validation humaine. Statuts : `pending`, `running`, `done`, `failed`, `needs_validation`, `cancelled`.

## Démarrage rapide (backend)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy ..\.env.example ..\.env
python -m shortforge
```

L'API répond sur <http://127.0.0.1:8787> (documentation interactive : <http://127.0.0.1:8787/docs>). Installation complète : [INSTALLATION_WINDOWS](docs/INSTALLATION_WINDOWS.md).

## Interface (Tauri)

Le backend doit tourner (voir ci-dessus). Dans un second terminal :

```powershell
cd apps\desktop
npm install
npm run tauri dev
```

`npm run dev` ouvre la même interface dans le navigateur sur <http://localhost:1420>. `npm run tauri build` produit l'installateur Windows (MSI et NSIS).

## Tests

```powershell
cd backend
pytest
ruff check .
mypy shortforge

cd ..\apps\desktop
npm test
npm run typecheck
```

## Arborescence

```text
shortforge/
├─ backend/            API FastAPI, SQLite, pipeline (Python 3.11+)
├─ apps/desktop/       Application Tauri 2 + React + TypeScript
├─ assets/             Workflows ComfyUI, musiques libres, polices, logo
├─ docs/               Documentation
├─ .github/            Intégration continue et modèles d'issues
└─ docker-compose.yml  Lancement optionnel du backend en conteneur
```

## Documentation

[Installation Windows](docs/INSTALLATION_WINDOWS.md) · [Architecture](docs/ARCHITECTURE.md) · [Workflows ComfyUI](docs/COMFYUI_WORKFLOWS.md) · [Règles YouTube](docs/YOUTUBE_POLICY.md) · [Feuille de route](docs/ROADMAP.md) · [Contribuer](CONTRIBUTING.md) · [Changements](docs/CHANGELOG.md)

## Licence

[MIT](LICENSE)
