# Règles YouTube et contenu responsable

ShortForge aide à créer, il ne publie jamais à ta place.

## Publication

- Désactivée par défaut (`YOUTUBE_PUBLISH_ENABLED=false`).
- Même activée, chaque publication exige ta validation du rendu final, puis ta confirmation explicite.
- L'envoi se fait en **privé** par défaut ; la publication programmée reste ton choix.

### Les étapes, dans l'ordre

1. **Montage** : MP4 1080x1920, H.264 + AAC, contrôlé avec ffprobe (format, codecs, 180 s au plus).
2. **Revue de l'aperçu** : tu regardes la vidéo ; « Refaire le montage » relance le rendu.
3. **Validation du rendu final** : le bouton ne s'active qu'une fois la vidéo regardée jusqu'au bout et la case
   « J'ai regardé le rendu final en entier » cochée. Une validation faite par un automatisme est refusée.
   L'empreinte du fichier est gardée : s'il change ensuite, la publication est bloquée.
4. **Brouillon YouTube** : titre, description (avec la mention IA et #Shorts), tags, confidentialité « privée ».
   Le brouillon reste sur ton ordinateur : rien n'est envoyé.
5. **Vérification finale**, visible à tout moment dans l'écran Aperçu. Toutes les lignes doivent être au vert :
   publication activée, rendu présent et conforme, fichier inchangé depuis la validation, validation humaine,
   brouillon complet (titre, description, tags), mention IA présente, contenu autorisé, idée originale,
   chaîne connectée.
6. **Publication** : case de confirmation puis « Publier sur YouTube ». Le backend refait le garde-fou et la
   vérification finale juste avant l'envoi. La vidéo est déclarée « contenu synthétique » (`containsSyntheticMedia`).

### Connexion de la chaîne

- Identifiant OAuth « Application de bureau » créé dans Google Cloud (API YouTube Data v3 activée), fichier
  indiqué dans `YOUTUBE_CLIENT_SECRETS_FILE`.
- Droits demandés : envoi de vidéos et lecture de la chaîne, rien d'autre.
- Le jeton est gardé dans `data/youtube/token.json`, jamais en base ni dans le code.

## Contenu synthétique

- YouTube impose de déclarer les contenus réalistes modifiés ou générés par IA : ShortForge coche cette déclaration par défaut et ajoute une mention configurable (`AI_DISCLOSURE_TEXT`).
- **Jamais de personne réelle** (visage, voix, nom) sans autorisation, et aucune tromperie sur l'identité.

## Monétisation

- YouTube ne rémunère pas le contenu « produit en masse », répétitif ou non authentique. Une vraie écriture, un vrai point de vue et une série cohérente font la différence.
- Les idées trop proches d'un sujet déjà traité sont écartées, et une idée à risque élevé de contenu réutilisé bloque la publication.

## Droits

- Aucune vidéo YouTube existante n'est téléchargée ni réutilisée sans licence.
- Les tendances servent d'inspiration : on en garde l'idée générale, jamais le contenu.
- Les fichiers importés (images, musiques) doivent être accompagnés de leurs droits ; ShortForge te demande de les confirmer.
- Musiques : uniquement libres de droits ou sous licence compatible.

## Contenus refusés

Contenu violent, sexuel, haineux, illégal ou trompeur, et conseils médicaux, juridiques ou financiers personnalisés.
