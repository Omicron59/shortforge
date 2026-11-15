# Installation sous Windows

## Prérequis

| Outil | Pourquoi | Lien |
|---|---|---|
| Python 3.11 ou plus récent | Backend | python.org (coche « Add to PATH ») |
| Git | Récupérer le projet | git-scm.com |
| FFmpeg | Montage vidéo | `winget install Gyan.FFmpeg` |
| ComfyUI Desktop | Images et vidéos locales avec ta carte graphique | comfy.org |
| Ollama | Modèles de texte locaux (idées, scripts) | ollama.com |
| Node.js 20+, Rust et les outils de build C++ de Visual Studio | Application de bureau Tauri | nodejs.org, rustup.rs, visualstudio.microsoft.com |

Une carte graphique NVIDIA avec 12 Go de mémoire vidéo ou plus est conseillée pour la vidéo locale. Avec 16 Go, les modèles vidéo tournent en version allégée (480p à 720p).

## Backend

```powershell
git clone <adresse-du-depot> shortforge
cd shortforge\backend
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy ..\.env.example ..\.env
python -m shortforge
```

Ouvre <http://127.0.0.1:8787/docs> pour vérifier que l'API répond.

## Application de bureau

Laisse le backend tourner et ouvre un second terminal :

```powershell
cd shortforge\apps\desktop
npm install
npm run tauri dev
```

La première compilation Rust prend plusieurs minutes. Pour créer l'installateur : `npm run tauri build`
(fichiers dans `src-tauri\target\release\bundle`). WebView2 est déjà présent sur Windows 10 et 11.

Si l'interface affiche « Moteur local injoignable », le backend n'est pas lancé ou n'écoute pas sur le port 8787.

## Configuration

Tout se règle dans `.env` (jamais versionné) :

- `COMFYUI_URL` : adresse de ComfyUI Desktop, par défaut `http://127.0.0.1:8188`.
- `OLLAMA_URL` et `OLLAMA_MODEL` : serveur et modèle de texte local.
- `BUDGET_MAX_PER_*` : plafonds de dépense en dollars.
- Clés des fournisseurs externes : laisse vide ce que tu n'utilises pas.
- `FFMPEG_PATH` : `ffmpeg` s'il est dans le PATH, sinon le chemin complet de `ffmpeg.exe`.
- `YOUTUBE_PUBLISH_ENABLED=false` : laisse-le à `false` tant que tu n'as pas tout testé.
- `YOUTUBE_CLIENT_SECRETS_FILE` : chemin du fichier OAuth « Application de bureau » téléchargé depuis Google Cloud,
  pour connecter ta chaîne (Paramètres → Chaîne YouTube). Voir [YOUTUBE_POLICY](YOUTUBE_POLICY.md).

## Données

La base `shortforge.sqlite3` et les fichiers générés sont dans `SHORTFORGE_DATA_DIR` (par défaut `.\data`). Sauvegarde ce dossier pour garder tes projets.
