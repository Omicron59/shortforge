# ShortForge — consignes pour Claude

Application Windows et macOS open source (MIT) pour créer des Shorts (YouTube, TikTok, Instagram) avec l'IA, en local.
Backend FastAPI + SQLite dans `backend/`, interface Tauri 2 + React dans `apps/desktop/`.

## Règles absolues (cahier des charges)

- Ne publie jamais sur YouTube sans validation humaine explicite.
- La publication automatique est désactivée par défaut : `YOUTUBE_PUBLISH_ENABLED=false` et `SOCIAL_PUBLISH_ENABLED=false` (TikTok/Instagram par Postiz) dans `.env.example`, `False` dans `config.py`.
- Toutes les clés API restent dans un fichier `.env` local. Jamais de clé dans le code, les tests, la base, les captures ou l'interface (l'API refuse les clés dans les réglages des moteurs).
- Ne contourne jamais le garde-fou (`services/publish_guard.py`), la vérification finale (`services/youtube.py::final_checks`) ni les validations humaines du pipeline. Une validation faite par un automatisme (`agent`, `system`, `ia`…) doit être refusée.
- Chaque étape du pipeline est sauvegardée dans SQLite ; un projet interrompu doit pouvoir reprendre.
- Aucune dépense sans confirmation explicite : un tarif inconnu bloque l'appel, les plafonds du budget sont revérifiés à la confirmation.
- Veo 3 est une option premium, jamais choisie par défaut. Gemini Omni 1.2 Flash est l'option économique à bas coût.
- L'interface est entièrement en français. Code et noms techniques en anglais, messages d'erreur destinés à l'utilisateur en français.
- Pas de contenu violent, sexuel, haineux, illégal ou trompeur ; pas de conseil médical, juridique ou financier personnalisé.
- Ne copie jamais automatiquement des vidéos existantes : les tendances et les Shorts concurrents servent d'inspiration. Seul le format abstrait (accroche, structure, rythme) peut être repris, jamais le contenu ; aucune vidéo concurrente n'est téléchargée. Pas de lecture automatique de comptes TikTok (pas d'accès public autorisé).
- Les médias importés (musique, vidéo longue, logo) exigent une confirmation des droits.
- Piper (GPL) reste un programme externe lancé à part : ne pas l'importer ni l'inclure dans le paquet.
- Les vidéos envoyées sur YouTube portent la mention IA et sont déclarées « contenu synthétique ». Envoi en privé par défaut.
- Code propre, typé, testé et documenté ; projet modulaire et facile à étendre.

## Commandes

```bash
cd backend && .venv/bin/pytest && .venv/bin/ruff check . && .venv/bin/mypy shortforge
cd apps/desktop && npm test && npm run typecheck && npm run build
cd apps/desktop/src-tauri && cargo check
```

Tout doit passer avant un commit. La CI GitHub refait ces contrôles sous Windows et Linux (avec FFmpeg).

## Repères

- Pipeline : `backend/shortforge/pipeline/` (15 étapes, statuts, validations) ; branchement des étapes dans `pipeline/default_handlers.py`.
- Moteurs vidéo : interface `providers/base.py::VideoProvider`, catalogue dans `services/provider_catalog.py`.
- Montage FFmpeg : `services/render.py` (MP4 1080x1920, H.264 + AAC, contrôlé avec ffprobe).
- YouTube : `services/youtube.py` (brouillon local, vérification finale, OAuth, envoi) ; autres plateformes : `services/social.py`.
- Voix, sous-titres animés, musique, qualité : `services/voice.py`, `subtitles.py`, `music.py`, `quality.py`.
- Croissance : `services/growth.py` (concurrents, style, résultats), `planning.py`, `clips.py` (vidéo longue).
- Paquets installables : `backend/packaging/` (PyInstaller), `apps/desktop/src-tauri/tauri.release.conf.json`, `.github/workflows/release.yml`.
- Tests : services externes simulés dans `backend/tests/fakes.py` ; ne jamais appeler une vraie API payante dans un test.
- Docs à tenir à jour avec chaque changement : `README.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`.
