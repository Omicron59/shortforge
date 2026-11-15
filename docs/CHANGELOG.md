# Journal des changements

## 0.4.0 — 15/11/2026

### Ajouté
- Montage FFmpeg : MP4 1080x1920, H.264 + AAC, 30 images/s, recadrage 9:16, durée exacte par scène, fondu et flash, sous-titres incrustés, piste muette sans voix off ; fichier contrôlé avec ffprobe.
- Sous-titres calculés depuis le texte des scènes (fichier .srt), style réglable dans l'écran Voix et sous-titres.
- Écran Aperçu et publication : lecture du rendu, revue de l'aperçu, validation du rendu final possible seulement après lecture complète et confirmation cochée.
- Brouillon YouTube local (titre, description avec mention IA, tags, confidentialité privée par défaut), modifiable.
- Vérification finale en 14 points, visible à tout moment et refaite juste avant l'envoi.
- Connexion OAuth de la chaîne et envoi en deux temps vers YouTube, déclaré « contenu synthétique ». Publication toujours désactivée par défaut.
- Étapes voix off et musique : se terminent en indiquant qu'elles ne sont pas encore disponibles.
- Extension Tauri « opener » limitée à l'ouverture de liens (connexion Google dans le navigateur).

### Modifié
- La validation du rendu final exige une confirmation explicite et vérifie que le fichier n'a pas changé.
- L'intégration continue installe FFmpeg pour tester le vrai montage.

## 0.3.0 — 15/11/2026

### Ajouté
- Interface Tauri complète en français : tableau de bord, niche et idées, éditeur de script, revue des scènes, voix et sous-titres, aperçu vidéo, file de production, historique, statistiques, paramètres.
- Suivi en direct du pipeline par WebSocket, confirmation explicite des dépenses avec le message exact du backend.
- Routes de lecture : fichiers générés, générations vidéo, historique, statistiques.
- Icônes de l'application, tests de l'interface (vitest), contrôle de l'interface dans l'intégration continue.

### Modifié
- Un réglage de moteur laissé vide revient à la valeur par défaut.
- L'origine `http://127.0.0.1:1420` est autorisée (serveur de développement).

## 0.2.0 — 15/11/2026

### Ajouté
- Idées avec Ollama : tendances (manuelles, Google Trends, YouTube), historique des sujets, filtre des doublons et des contenus interdits, risque de contenu réutilisé.
- Scripts : hook, corps, conclusion, appel à l'action, scènes avec prompts visuels et négatifs, transitions ; régénérer, raccourcir, modifier, valider ; versions successives.
- ComfyUI : vérification du serveur, workflows au format API, remplacement des entrées (prompt, dimensions, seed, modèle, images), suivi WebSocket avec repli, téléchargement, erreurs en français, workflows personnels.
- Interface commune `VideoProvider` et 11 moteurs : ComfyUI, Wan 2.2, LTX Video, CogVideoX (locaux), Gemini Omni 1.2 Flash, Veo 3, Veo 3 Fast, Hailuo/MiniMax, Kling, Runway, Pika (listé, pas encore disponible).
- Choix du moteur par mode (économique, standard, premium, personnalisé), par scène ou pour tout le Short, repli automatique sur ComfyUI local.
- Budget : plafonds par scène, Short, jour et mois, confirmation obligatoire de chaque dépense, historique, blocage automatique.
- Étapes du pipeline branchées : idées, choix, script, validation, découpage, images, vidéos. Exécution en arrière-plan et suivi WebSocket.
- État des services locaux (ComfyUI, Ollama, FFmpeg, carte graphique).

## 0.1.0 — 15/11/2026

### Ajouté
- Arborescence du projet, licence MIT, configuration `.env.example` (publication YouTube désactivée).
- Backend FastAPI : santé, catalogue des moteurs vidéo, projets, pilotage du pipeline.
- Base SQLite : 15 tables du cahier des charges + `pipeline_steps`.
- Pipeline en 15 étapes avec validations humaines, rejet, « Refaire », annulation et reprise après interruption.
- Garde-fou de publication : option `.env`, rendu final validé et confirmation explicite par une personne.
- Squelette de l'application Tauri 2 + React (écran provisoire).
- Tests (pytest), ruff, mypy strict, intégration continue Windows et Linux.
