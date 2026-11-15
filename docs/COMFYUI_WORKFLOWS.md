# Workflows ComfyUI


## Exporter un workflow

1. Dans ComfyUI, active l'option développeur, puis **Workflow → Export (API)**.
2. Enregistre le fichier JSON dans `assets/workflows/` (ou importe-le depuis l'application).

## Paramètres remplacés automatiquement

ShortForge repère les nœuds à modifier grâce à un fichier de description placé à côté du workflow (`mon_workflow.shortforge.json`). Sans ce fichier, il devine les entrées des workflows simples (KSampler, CLIPTextEncode, EmptyLatentImage, CheckpointLoaderSimple, LoadImage).

Entrées reconnues : `prompt`, `negative_prompt`, `width`, `height`, `seed`, `model`, `input_image`, `last_image`, `duration_s`, `frames`, `fps`. Une clé `defaults` permet de fixer des valeurs (ex. `{"fps": 24}`).

```json
{
  "name": "Image verticale SDXL",
  "kind": "image",
  "inputs": {
    "prompt": {"node": "6", "field": "text"},
    "negative_prompt": {"node": "7", "field": "text"},
    "width": {"node": "5", "field": "width"},
    "height": {"node": "5", "field": "height"},
    "seed": {"node": "3", "field": "seed"},
    "model": {"node": "4", "field": "ckpt_name"},
    "input_image": {"node": "10", "field": "image"}
  }
}
```

## Workflows attendus

| Usage | Identifiant du workflow |
|---|---|
| Images des scènes | `image_default` (réglable : `COMFYUI_IMAGE_WORKFLOW`) |
| Moteur ComfyUI local | `comfyui_local` |
| Wan 2.2 local | `wan22_local` |
| LTX Video local | `ltx_video_local` |
| CogVideoX local | `cogvideox_local` |

Un moteur local sans son workflow apparaît « non configuré » dans la liste des moteurs.

## Ajouter un workflow

- Dépose `mon_id.json` (et éventuellement `mon_id.shortforge.json`) dans `assets/workflows/`, dans `data/workflows/` ou dans `COMFYUI_WORKFLOWS_DIR` ;
- ou envoie-le à l'API : `POST /api/comfyui/workflows` avec `{"id", "name", "kind", "workflow", "inputs"}`.

## Fonctionnement

- Vérification du serveur (`/system_stats`), qui donne aussi le nom et la mémoire de la carte graphique.
- Envoi du workflow (`/prompt`), suivi de la progression par WebSocket (`/ws`), avec repli sur `/history` si le WebSocket est indisponible.
- Téléchargement des images ou vidéos (`/view`), images d'entrée envoyées par `/upload/image`.
- Régénération d'une scène avec une nouvelle seed : `POST /api/scenes/{id}/regenerate`.
- Les erreurs de ComfyUI (nœud manquant, modèle absent, mémoire insuffisante) sont traduites en français.
