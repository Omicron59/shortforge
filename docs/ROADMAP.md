# Feuille de route

- [x] 1. Arborescence complète
- [x] 2. Backend FastAPI de base
- [x] 3. Base SQLite (15 tables + état du pipeline)
- [x] 4. Projets et pipeline (statuts, validations humaines, reprise après interruption)
- [x] 5. Ollama pour les idées et les scripts
- [x] 6. ComfyUI (workflows API, WebSocket, régénération, workflows personnalisés)
- [x] 7. Interface `VideoProvider` et client Gemini Omni 1.2 Flash
- [x] 8. Autres fournisseurs vidéo, budget et confirmations de coût
  - [ ] À vérifier avec une vraie clé : identifiants de modèles et formats d'API de chaque fournisseur
  - [ ] Pika : pas d'API publique vérifiée
- [x] 9. Voix off locale : Piper, voix du système (Windows, macOS) ; ElevenLabs en option payante
  - [ ] XTTS ou F5-TTS (clonage de voix local)
- [ ] 10. Whisper et sous-titres (SRT, styles)
  - [x] Sous-titres calculés depuis le texte des scènes, style réglable, fichier .srt
  - [x] Minutage mot à mot avec Whisper sur la voix off (si faster-whisper est installé), 20 styles animés
- [x] 11. Montage FFmpeg (recadrage 9:16, durée par scène, fondu et flash, sous-titres incrustés)
  - [x] Voix off + musique, logo, zoom lent sur les images
  - [ ] Transitions zoom et glissement entre vidéos, suivi du visage pour le recadrage
- [x] 12. Interface Tauri complète (voix, sous-titres et aperçu monté affichés en attente des étapes 9 à 11)
- [x] 13. Aperçu et validation humaine (vidéo regardée jusqu'au bout, confirmation explicite)
- [x] 14. Export MP4 1080x1920 H.264 + AAC, vérifié avec ffprobe
  - [ ] Miniature
- [x] 15. YouTube : connexion OAuth, brouillon local, vérification finale, envoi en privé par défaut
  - [ ] À vérifier avec une vraie chaîne (testé seulement contre une API simulée)
  - [ ] Publication programmée, miniature, statistiques

## Version 0.5.0 (fonctions de croissance et versions installables)

- [x] Concurrents (5 comptes, Shorts à 2x la médiane) et formats gagnants → Short original en un clic
- [x] Style d'écriture personnel appris sur tes textes ou tes vidéos
- [x] Correction du script en langage naturel
- [x] Vidéo longue → plusieurs Shorts (transcription locale, recadrage 9:16)
- [x] Contrôle vidéo image par image avec une note sur 10
- [x] Planning de la semaine, pilote automatique, boîte de validation
- [x] TikTok et Instagram par Postiz ou export manuel, programmation par plateforme
- [x] Analyse des résultats → leçons pour les idées suivantes
- [x] Assistant de premier lancement
- [x] Installateurs Windows et macOS (moteur local inclus)
  - [ ] Signature des installateurs (certificats Windows et Apple)
  - [ ] Postiz : à vérifier avec une vraie instance
  - [ ] Suivi automatique des comptes TikTok : pas d'accès public possible
