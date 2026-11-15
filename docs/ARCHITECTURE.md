# Architecture

```text
┌──────────────────────────┐   HTTP + WebSocket   ┌─────────────────────────────────────────┐
│ App Tauri (React, TS)    │ ───────────────────▶ │ Backend FastAPI  backend/shortforge      │
│ apps/desktop             │   127.0.0.1:8787     │  routers/    routes HTTP                 │
└──────────────────────────┘                      │  pipeline/   moteur, étapes, exécution   │
                                                  │  services/   idées, script, budget...    │
                                                  │  providers/  moteurs vidéo               │
                                                  │  integrations/ Ollama, ComfyUI, tendances│
                                                  │  SQLite (data/shortforge.sqlite3)        │
                                                  └──────┬──────────────────────┬────────────┘
                                                         │                      │
                                  ComfyUI :8188, Ollama :11434, FFmpeg     API externes (clés .env)
```

## Modules

| Module | Rôle |
|---|---|
| `config.py` | Réglages lus depuis `.env` ; clés API en `SecretStr` |
| `db.py`, `models.py` | SQLite (clés étrangères, WAL), 15 tables + `pipeline_steps` |
| `runtime.py` | Assemble les dépendances (Ollama, ComfyUI, tendances, moteurs) ; remplaçable dans les tests |
| `pipeline/steps.py` | Les 15 étapes, validations humaines, transitions autorisées |
| `pipeline/engine.py` | `PipelineService` : avancer, valider, rejeter, refaire, annuler, reprendre |
| `pipeline/default_handlers.py` | Branche les services sur les étapes |
| `pipeline/runner.py` | Exécution en arrière-plan, une étape à la fois par projet |
| `integrations/ollama.py` | Modèle de texte local en mode JSON |
| `integrations/trends.py` | Tendances : manuelles, Google Trends (RSS), YouTube (API, lecture seule) |
| `integrations/comfyui.py` | Client ComfyUI et bibliothèque de workflows |
| `services/ideas.py`, `services/scripts.py` | Idées, scripts et scènes |
| `services/safety.py` | Contenus interdits, conseils personnalisés, doublons, risque de reprise |
| `services/engine_selection.py` | Choix du moteur de chaque scène |
| `services/budget.py` | Plafonds, confirmations, dépenses |
| `services/production.py` | Découpage, images, vidéos |
| `services/publish_guard.py` | Garde-fou de publication |
| `providers/` | `VideoProvider` et les 11 moteurs |

## Moteurs vidéo

Tous les moteurs héritent de `VideoProvider` et exposent `generate_from_text`, `generate_from_image`, `generate_from_first_and_last_frame`, `edit_video`, `estimate_cost`, `validate_parameters`, `get_status` et `download_result`. Un moteur ne gère ni le budget ni la base : c'est `services/production.py` qui contrôle chaque dépense avant d'appeler un moteur.

| Moteur | Type | Opérations | Durées |
|---|---|---|---|
| ComfyUI, Wan 2.2, LTX Video, CogVideoX | local, gratuit | texte, image, première et dernière image* | 1 à 15 s |
| Gemini Omni 1.2 Flash | externe, 0,07 $/s | texte, image, première et dernière image | 3 à 15 s |
| Veo 3 Fast, Veo 3 | externe, premium | texte, image | 4, 6, 8 s |
| Hailuo / MiniMax | externe | texte, image, première et dernière image | 6, 10 s |
| Kling | externe | texte, image, première et dernière image | 5, 10 s |
| Runway | externe | image | 5, 10 s |
| Pika H3 Flex | — | pas encore disponible | — |

\* si le workflow a une entrée `last_image`. La modification de vidéo n'est encore gérée par aucun moteur.

Les identifiants de modèles et les adresses sont réglables par moteur (`PATCH /api/providers/{id}`, champ `config`). **Ils n'ont pas été testés avec de vraies clés** : vérifie-les dans la documentation de chaque fournisseur avant le premier usage.

## Choix du moteur

1. Moteur choisi à la main pour la scène ;
2. sinon moteur unique du Short (`engine_scope = "short"`) ;
3. sinon règle du mode selon l'importance de la scène ;
4. moteur désactivé, tarif inconnu ou budget dépassé : ComfyUI local.

| Scène | Économique | Standard | Premium |
|---|---|---|---|
| simple | ComfyUI local | ComfyUI local | ComfyUI local |
| transition | LTX Video local | LTX Video local | LTX Video local |
| importante | ComfyUI local | Gemini Omni 1.2 Flash | Gemini Omni 1.2 Flash |
| exceptionnelle | ComfyUI local | Gemini Omni 1.2 Flash | Veo 3 |

Le mode personnalisé lit ses règles dans les paramètres. Veo 3 n'est jamais choisi par défaut.

## Budget

- Plafonds par scène, par Short, par jour et par mois (`.env`, modifiables dans l'application).
- Un tarif inconnu bloque l'appel.
- Avant toute dépense, l'étape `generate_videos` passe à `needs_validation` avec, pour chaque scène payante, le message « Cette scène utilisera … Coût estimé : … Confirmer la génération ? ». La validation (`confirm: true`) revérifie le budget, enregistre les confirmations, puis l'étape est relancée.
- Chaque confirmation ne sert qu'une fois ; chaque dépense réelle est enregistrée dans `costs`.

## Pipeline et reprise

- Les étapes s'exécutent dans l'ordre ; une erreur est enregistrée avec le nombre de tentatives.
- Les étapes de validation attendent `approve` (par une personne) ou `reject` ; un rejet relance l'étape qui a produit le résultat.
- Chaque scène garde son statut d'image et de vidéo : après un échec ou une fermeture, seules les scènes manquantes sont refaites.
- Au démarrage, toute étape restée `running` repasse à `pending`.

## API

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/api/health`, `/api/status` | Backend ; ComfyUI, Ollama, FFmpeg, carte graphique |
| POST / GET | `/api/projects`, `/api/projects/{id}` | Projets et étapes |
| POST | `/api/projects/{id}/pipeline/advance[?background=true]` | Étape suivante |
| POST | `/api/projects/{id}/steps/{étape}/approve` · `reject` · `redo` | Valider (`{"validated_by", "confirm"}`), rejeter, refaire |
| POST | `/api/projects/{id}/pipeline/cancel` · `resume` | Annuler, reprendre |
| WS | `/api/projects/{id}/events` | État du pipeline en direct |
| GET / POST | `/api/projects/{id}/ideas`, `…/ideas/{idea}/select` | Idées, choix |
| GET / PUT | `/api/projects/{id}/script` | Script et scènes, modification |
| POST | `/api/projects/{id}/script/shorten` · `regenerate` | Raccourcir, régénérer |
| GET / PATCH | `/api/projects/{id}/scenes`, `/api/scenes/{id}` | Scènes, moteur, prompts |
| POST | `/api/scenes/{id}/regenerate` | Nouvelle image ou vidéo |
| GET / PUT | `/api/projects/{id}/cost-estimate`, `/api/projects/{id}/engine` | Coûts, mode et moteur |
| GET / PATCH | `/api/providers`, `/api/providers/{id}` | Moteurs, tarifs, réglages |
| GET / PUT | `/api/budget`, `/api/budget/limits`, `/api/budget/history` | Budget |
| GET / POST | `/api/comfyui/status`, `/api/comfyui/workflows` | ComfyUI |
| GET / PUT | `/api/settings` | Règles des moteurs, tendances, workflow image |
| GET | `/api/projects/{id}/assets`, `/api/assets/{id}/file` | Fichiers générés (seulement ceux du dossier de données) |
| GET | `/api/jobs` | Générations vidéo (file de production) |
| GET | `/api/history` | Journal des étapes, validations et dépenses |
| GET | `/api/stats` | Statistiques de production |
| GET | `/api/projects/{id}/render` | Dernier rendu final (fichier, validation) |
| GET / PUT | `/api/projects/{id}/subtitles` | Sous-titres et leur style |
| GET / PUT | `/api/projects/{id}/youtube-draft` | Brouillon YouTube local |
| GET | `/api/projects/{id}/final-check` | Vérification finale avant publication (lecture seule) |
| GET / POST | `/api/youtube/status`, `/api/youtube/connect` | État de la publication, connexion de la chaîne |
| GET | `/api/youtube/oauth/callback` | Retour de la connexion Google |

## Interface (apps/desktop)

Tauri 2 + React 18 + TypeScript + Tailwind, entièrement en français. Elle parle au backend sur
`http://127.0.0.1:8787` (modifiable avec `VITE_API_URL`) et suit chaque projet en direct par WebSocket.

| Écran | Rôle |
|---|---|
| Tableau de bord | Services locaux, budget du jour et du mois, projets, prochaine étape et pipeline |
| Niche et idées | Création d'un projet (niche, langue, mode vidéo), idées notées, risque de contenu réutilisé, choix |
| Éditeur de script | Hook, corps, conclusion, appel à l'action, scènes ; raccourcir, régénérer, valider |
| Revue des scènes | Images et clips, moteur par scène, coût estimé, confirmation des dépenses, régénération |
| Voix et sous-titres | Texte et minutage par scène, aperçu du style des sous-titres (génération : étapes 9 et 10) |
| Aperçu vidéo | Clips lus à la suite, validations finales, état de la publication (désactivée par défaut) |
| File de production | Étapes en cours sur tous les projets, générations vidéo et leur coût |
| Historique | Journal filtrable par projet et par type, total dépensé |
| Statistiques | Projets, scènes, clips, dépenses par moteur et par mois |
| Paramètres | Plafonds, moteurs (activation, tarif, modèle), règles du mode personnalisé, tendances, workflows |

Aucune clé API ne se saisit dans l'interface : elles restent dans le `.env`. Une dépense n'est
confirmée qu'après avoir coché la case qui reprend le message exact du backend.

## Publication

`publish` est une validation humaine protégée par `publish_guard` : `YOUTUBE_PUBLISH_ENABLED=true`, rendu final validé par une personne, et confirmation explicite.
