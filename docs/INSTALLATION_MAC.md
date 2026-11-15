# Installation sur macOS

ShortForge fonctionne sur les Mac à puce Apple (M1 à M4) et sur les Mac Intel, macOS 11 ou plus récent.

## 1. Installer l'application

1. Télécharge le bon fichier depuis les Releases ou l'onglet Actions du dépôt :
   - puce Apple : `ShortForge_…_aarch64.dmg` ;
   - Intel : `ShortForge_…_x64.dmg`.
2. Ouvre le `.dmg` et glisse **ShortForge** dans **Applications**.
3. L'application n'est pas encore signée par Apple. Au premier lancement, macOS peut dire qu'elle « ne peut pas être
   ouverte » ou qu'elle « est endommagée ». Dans ce cas, ouvre le Terminal et tape :

   ```bash
   xattr -cr /Applications/ShortForge.app
   ```

   Puis relance ShortForge. Autre méthode : **Réglages Système → Confidentialité et sécurité → Ouvrir quand même**.

Le moteur local démarre tout seul. Tes projets sont dans `~/Library/Application Support/org.shortforge.app`, et ton
fichier de réglages est `reglages.env` dans `~/Library/Application Support/org.shortforge.app/` (l'assistant te le
montre dans le Finder).

## 2. Outils à installer

Avec [Homebrew](https://brew.sh) :

```bash
brew install ffmpeg
```

| Outil | Pourquoi | Comment |
|---|---|---|
| FFmpeg | Montage, voix, contrôle vidéo | `brew install ffmpeg` |
| Ollama | Idées et scripts (modèle local) | ollama.com, puis `ollama pull <modèle>` et `OLLAMA_MODEL=` dans les réglages |
| ComfyUI Desktop | Images et vidéos locales | comfy.org (version Apple Silicon) |

Sur Mac, ComfyUI utilise la puce Apple (Metal) : les images marchent bien, la vidéo locale est plus lente qu'avec une
carte NVIDIA. Les moteurs en ligne (Gemini Omni Flash, Kling…) sont une bonne alternative, avec le budget plafonné.

## 3. Voix off

- **Voix de macOS** : marche tout de suite (commande `say`). Pour une voix française de meilleure qualité, ajoute-en
  une dans **Réglages Système → Accessibilité → Contenu énoncé → Voix du système → Gérer les voix**, puis indique
  son nom dans `SYSTEM_VOICE=` (exemple : `Thomas`).
- **Piper** (plus naturel, gratuit) : `pip3 install piper-tts`, télécharge une voix française `.onnx`, puis renseigne
  `PIPER_PATH=` et `PIPER_VOICE=`.
- **ElevenLabs** (payant, ta voix clonée) : clé et voix dans les réglages ; chaque génération demande ta confirmation.

## 4. Vidéo longue → Shorts

La transcription (faster-whisper) est incluse. Au premier usage, le modèle est téléchargé (environ 500 Mo pour
`small`).

## Installer depuis le code (développeurs)

```bash
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,media]" && cp ../.env.example ../.env && python -m shortforge
# second terminal
cd apps/desktop && npm install && npm run tauri dev
```
