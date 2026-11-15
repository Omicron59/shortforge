"""Garde-fous de contenu et detection de doublons.

Premiere version volontairement simple (mots-cles) : elle bloque les cas evidents. Le module de
securite complet (droits des fichiers, licences) viendra avec l'import de fichiers.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# Categories interdites -> motifs (francais et anglais), recherches sur des mots entiers.
FORBIDDEN: dict[str, tuple[str, ...]] = {
    "violence": ("tuer", "massacre", "torture", "decapit", "kill", "murder", "gore", "attentat", "bomb"),
    "sexuel": ("porno", "sexe explicite", "nude", "nsfw", "porn", "erotique"),
    "haine": ("race inferieure", "sale arabe", "sale juif", "sale noir", "nazi", "hate speech"),
    "illegal": ("drogue a vendre", "fabriquer une arme", "pirater un compte", "how to make a bomb", "contrefacon"),
    "tromperie": ("fausse information", "deepfake de", "faux temoignage", "fake news"),
}
PERSONAL_ADVICE: tuple[str, ...] = (
    "arrete ton traitement", "arrete ton medicament", "prends une dose de", "investis tout", "achete cette action",
    "conseil juridique personnalise", "porte plainte contre", "garanti de gagner",
)


def normalize(text: str) -> str:
    """Minuscules, sans accents ni ponctuation, espaces simples."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _contains(text: str, pattern: str) -> bool:
    return re.search(rf"\b{re.escape(normalize(pattern))}", text) is not None


def content_issues(text: str) -> list[str]:
    """Problemes detectes dans un texte (liste vide = rien de bloquant)."""
    norm = normalize(text)
    issues = [f"contenu {category} interdit" for category, patterns in FORBIDDEN.items()
              if any(_contains(norm, p) for p in patterns)]
    if any(_contains(norm, p) for p in PERSONAL_ADVICE):
        issues.append("conseil médical, juridique ou financier personnalisé")
    return issues


def similarity(a: str, b: str) -> float:
    """Ressemblance entre deux textes, de 0 (rien en commun) a 1 (identiques)."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def best_match(text: str, candidates: list[str]) -> tuple[float, str]:
    """Le candidat le plus proche et son score."""
    scored = [(similarity(text, c), c) for c in candidates]
    return max(scored, default=(0.0, ""))


def reuse_risk(score: float) -> str:
    """Risque de contenu reutilise selon la ressemblance avec une tendance existante."""
    if score >= 0.75:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"
