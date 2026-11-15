# ShortForge

Application **Windows et macOS**, **open source** (licence MIT), pour créer des Shorts avec l'IA, **en local** sur ton ordinateur. Elle prend en charge :
- les idées, les scripts écrits dans ton style, les images et vidéos via ComfyUI ;
- la voix off locale et les sous-titres animés ;
- le montage vertical 1080x1920 et le contrôle qualité ;
- la publication sur YouTube Shorts, TikTok et Instagram Reels, toujours après ta validation.

Tu choisis pour chaque Short, ou pour chaque scène, entre des moteurs vidéo **locaux gratuits** (ComfyUI, Wan 2.2, LTX Video, CogVideoX) et des **fournisseurs externes payants** (Gemini Omni 1.2 Flash, Kling, Hailuo/MiniMax, Runway, Pika, Veo 3), avec un budget qui bloque toute dépense non prévue.

> **État : version 0.5.0.** Installateurs Windows et macOS fabriqués par GitHub Actions. Publication désactivée par défaut. Voir [ROADMAP](docs/ROADMAP.md).

## Fonctions

| Créer | Grandir | Publier |
|---|---|---|
| Idées avec Ollama (tendances = inspiration) | Suivi de 5 comptes, Shorts à 2x leur médiane | YouTube Shorts (API officielle), programmation |
| Scripts dans ton style, corrigés en une phrase | Recette d'un format gagnant → Short 100 % nouveau | TikTok et Instagram par Postiz, ou export manuel |
| 11 moteurs vidéo, local ou en ligne, budget plafonné | Analyse de tes résultats → leçons pour la semaine | Créneaux horaires par plateforme |
| Voix off locale (Piper, voix Windows/macOS) ou ElevenLabs | Planning de la semaine, pilote automatique | Vérification finale et validation humaine |
| 20 styles de sous-titres animés, logo, musique | Vidéo longue → plusieurs Shorts (Whisper local) | Contrôle vidéo image par image, note sur 10 |

## Règles du projet

- **Aucune publication sans validation humaine explicite.** La publication YouTube est désactivée par défaut (`YOUTUBE_PUBLISH_ENABLED=false`).
- Les clés API restent dans le fichier `.env` local, jamais dans le code.
- Chaque étape du pipeline est enregistrée dans SQLite : un projet interrompu reprend là où il s'était arrêté.
- Les tendances et les Shorts concurrents servent d'inspiration, jamais de source à recopier : seul le **format** (accroche, structure, rythme) d'un Short qui marche peut être repris, avec une histoire entièrement nouvelle. Aucune vidéo n'est téléchargée.
- TikTok et Instagram sont désactivés par défaut aussi (`SOCIAL_PUBLISH_ENABLED=false`) : sans eux, tu publies toi-même.
- Pas de contenu violent, sexuel, haineux, illégal ou trompeur. Voir [YOUTUBE_POLICY](docs/YOUTUBE_POLICY.md).

## Le pipeline

```text
generate_ideas → select_idea* → write_script → approve_script* → create_storyboard
→ generate_images → generate_videos → generate_voice → create_subtitles → select_music
→ render_video → review_preview* → approve_final_render* → create_youtube_draft → publish*
```

`*` = étape de validation humaine. Statuts : `pending`, `running`, `done`, `failed`, `needs_validation`, `cancelled`.

## Installer l'application

Télécharge l'installateur dans l'onglet **Actions** du dépôt (workflow « Versions Windows et macOS ») ou dans les **Releases** :
- **Windows** : `ShortForge_0.5.0_x64-setup.exe` ou `.msi`. Guide : [INSTALLATION_WINDOWS](docs/INSTALLATION_WINDOWS.md).
- **macOS** : `ShortForge_0.5.0_aarch64.dmg` (puce Apple) ou `_x64.dmg` (Intel). Guide : [INSTALLATION_MAC](docs/INSTALLATION_MAC.md).

Le moteur local est inclus et démarre tout seul. Il reste à installer FFmpeg, Ollama et, si tu veux, ComfyUI : l'assistant du premier lancement te guide.

## Démarrage rapide pour développer (backend)

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
