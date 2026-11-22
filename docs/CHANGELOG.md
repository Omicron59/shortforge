# Journal des changements

## 0.7.1 — 22/11/2026

### Ajouté
- Archiver un projet : il disparaît des listes (Tableau de bord, « Reprendre un projet », menu) sans rien effacer ; « Voir les projets archivés » permet de le restaurer. Un projet archivé n'apparaît plus dans « À valider ».
- Supprimer définitivement un projet et ses médias, avec une fenêtre qui détaille son contenu, l'espace libéré et le caractère irréversible, et une case à cocher. Refusé tant que le projet est en cours de production. Les fichiers partagés (musique, autres projets) ne sont jamais touchés ; les coûts passés sont conservés.
- Migration de base `0004` (colonne d'archivage), précédée de la sauvegarde automatique habituelle.

### Corrigé
- Le menu des projets se met à jour après la création ou la duplication d'un projet.

## 0.7.0 — 17/11/2026 (non publiée)

### Ajouté
- Nouveau parcours de création en 4 étapes (menu « Nouveau Short ») : Brief, Idées, Script et storyboard, Studio. L'ancien parcours reste disponible et les deux partagent les mêmes projets.
- Brief court avec valeurs par défaut ; réglages secondaires repliés ; brouillon gardé avant même la création du projet.
- 5 idées à partir du brief (résumé, difficulté, ressources, raison), variantes, modification, « garder pour plus tard ». Les nouvelles idées s'ajoutent aux précédentes. Aucun score de viralité.
- Script et storyboard par scène : voix off, texte à l'écran, intention visuelle, prompt visuel, transition. Ajout, suppression, réordonnancement, régénération d'un seul champ, raccourcir, changer le ton, autres accroches, écriture sans modèle.
- Enregistrement automatique avec état visible, reprise à l'étape en cours, historique et restauration des versions du script, duplication d'un projet.
- Studio : scènes, aperçu 9:16 (storyboard distinct de la vidéo rendue), propriétés par onglet, import d'une image par scène, état réel de la production.
- Signalement des images, de la voix, des sous-titres et du rendu produits avant une modification (rien n'est relancé tout seul).
- Annulation d'une génération : son résultat n'est pas enregistré.
- Tâches IA « Storyboard » et « Variantes » dans Réglages > Intelligence artificielle ; le modèle utilisé est affiché discrètement.
- Texte à l'écran incrusté dans la vidéo exportée, en haut, pendant toute sa scène.
- Appels texte payés à l'usage comptés dans les plafonds de budget du jour et du mois, et refusés au-delà (repli sur le modèle de secours s'il y en a un). Un modèle sans tarif publié est refusé. Les modèles Ollama par abonnement comptent 0 $.

### Corrigé (après les premiers tests sur Windows)
- Durée réelle d'une scène affichée une fois la voix générée ; bouton « Vidéo à jour » quand rien n'est à refaire.
- Pastille d'état d'Ollama sans test manuel ; les modèles « :cloud » sont signalés comme s'exécutant dans le cloud.
- Anciens projets : durée visée reprise de leur idée au lieu de 30 s ; un projet sans étapes s'ouvre quand même.

### Limites connues
- Taille et position du texte à l'écran fixes.
- Voix par scène et musique générée : non intégrées.
- Pas d'installateur pour les Mac Intel (bibliothèque de chiffrement incompatible sur cette plateforme).

## 0.6.0 — 16/11/2026 (non publiée)

### Ajouté
- Réglages > Intelligence artificielle : Ollama sur ton PC, Ollama Cloud et OpenRouter, test de connexion réel, liste des modèles fournie par le fournisseur, recherche et filtres, modèle différent par tâche (idées, script, analyse), modèle de secours, paramètres avancés, journal des appels.
- Coffre à secrets : les clés API sont chiffrées sur le disque ; la clé de chiffrement est gardée par le trousseau du système (Gestionnaire d'identification Windows, Trousseau macOS). Le jeton YouTube existant est chiffré sur place à sa première utilisation.
- Migrations de la base (Alembic) : la base est copiée dans `sauvegardes/` et la copie vérifiée avant toute mise à niveau.
- L'API locale exige un jeton de session créé par l'application à chaque lancement.
- Premiers composants du nouveau design (palette sombre, `components/ds.tsx`) ; menu repliable en fenêtre étroite.

### Garanties
- Sans réglage, le texte passe par Ollama et le modèle du fichier de réglages, comme avant.
- Un modèle payant n'est jamais choisi ni utilisé en secours sans accord explicite.
- Le fichier de réglages et ses clés existantes ne sont ni modifiés ni supprimés.

## 0.5.3 — 16/11/2026

### Amélioré (rendu plus propre)
- Volume réglé automatiquement à -14 LUFS (niveau de TikTok, YouTube et Instagram).
- Zoom lent sur les images : agrandissement 3x en lanczos avant le zoom, mouvement régulier sans tremblement.
- Taille des images adaptée au modèle : 512x896 pour SD 1.5 (évite les sujets déformés ou répétés), 768x1344 pour SDXL.
- Consignes de qualité ajoutées aux prompts d'image (couleurs, éclairage, netteté) et au prompt négatif (noir et blanc, flou, filigrane).

## 0.5.2 — 15/11/2026

### Corrigé
- Sans workflow vidéo ComfyUI, l'étape des vidéos échouait : la scène garde maintenant son image, animée par un zoom lent au montage.
- Un modèle Ollama écrit sans son étiquette (« modele » au lieu de « modele:cloud ») est retrouvé automatiquement.

## 0.5.1 — 15/11/2026

### Corrigé
- ComfyUI Desktop (port 8000) n'était pas trouvé : ShortForge essaie maintenant l'adresse réglée, puis les ports 8000 et 8188, et garde celle qui répond.

### Ajouté
- Paramètres et assistant : carte ComfyUI avec bouton « Tester », adresse modifiable sans ouvrir le fichier de réglages, choix du modèle d'image parmi ceux installés dans ComfyUI.

## 0.5.0 — 15/11/2026

### Ajouté
- Voix off locale : Piper, voix de Windows (SAPI), voix de macOS (`say`) ; ElevenLabs en option avec confirmation du coût. Scènes allongées si la voix dépasse.
- Sous-titres animés : 20 styles, 7 effets (surlignage, rebond, karaoké, mot à mot, pop, fondu), minutage mot à mot avec Whisper si installé.
- Musiques personnelles (droits confirmés), logo incrusté, style de sous-titres par défaut (marque).
- Contrôle vidéo image par image (passages noirs, images figées, silences, volume) avec une note sur 10 exigée pour publier.
- Formats gagnants : suivi de 5 comptes YouTube (TikTok à la main), Shorts à 2x la médiane, recette du format, nouveau Short original en un clic.
- Style d'écriture personnel et correction du script en une phrase.
- Résultats des Shorts (YouTube automatique, TikTok et Instagram à la main) et leçons utilisées pour les idées suivantes.
- Planning de la semaine, pilote automatique jusqu'à chaque validation, boîte « À valider ».
- Vidéo longue → plusieurs Shorts : transcription locale, meilleurs passages, recadrage 9:16, sous-titres.
- Publication sur YouTube (programmation), TikTok et Instagram (Postiz) ou export manuel ; créneaux par plateforme.
- Assistant de premier lancement.
- Installateurs Windows (.exe, .msi) et macOS (.dmg puce Apple et Intel) avec le moteur local inclus ; fichier de réglages créé au premier lancement.

### Modifié
- Le garde-fou de publication accepte YouTube ou Postiz, tous deux désactivés par défaut.
- Une ligne vide dans le fichier de réglages vaut « non renseigné ».

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
