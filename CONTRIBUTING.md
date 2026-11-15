# Contribuer à ShortForge

Merci de ton aide ! Quelques règles simples :

1. **Ouvre une issue** avant un gros changement, pour en discuter.
2. **Une PR = un sujet.** Garde-la courte et lisible.
3. **Tests obligatoires** : tout nouveau comportement est couvert par un test dans `backend/tests/`.
4. Avant d'envoyer : `pytest`, `ruff check .` et `mypy shortforge` passent dans `backend/`.
5. **Jamais de secret** dans le code, les tests ou les captures : les clés vont dans `.env`.
6. **Interface en français**, code et noms techniques en anglais.
7. Ne contourne jamais le garde-fou de publication (`services/publish_guard.py`) ni la validation humaine.

## Ajouter un fournisseur vidéo

Les fournisseurs implémenteront l'interface commune `VideoProvider` (étape 7 de la feuille de route) : `generate_from_text`, `generate_from_image`, `generate_from_first_and_last_frame`, `edit_video`, `estimate_cost`, `validate_parameters`, `get_status`, `download_result`. Ajoute-le aussi au catalogue `services/provider_catalog.py`.

## Ajouter une étape automatique

Écris une fonction `(StepContext) -> dict` et enregistre-la dans le `HandlerRegistry` pour l'étape voulue. Le moteur se charge des statuts, des erreurs, des tentatives et de la sauvegarde.
