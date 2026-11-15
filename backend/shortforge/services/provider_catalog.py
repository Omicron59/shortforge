"""Catalogue des moteurs video connus, enregistre en base au demarrage.

Les couts par seconde ne sont renseignes que lorsqu'ils ont ete verifies ; `None` signifie
« a configurer dans les parametres » et bloque tout appel payant tant qu'il n'est pas renseigne.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from shortforge.models import Provider


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    id: str
    name: str
    kind: str  # local | external
    tier: str  # economique | standard | premium
    cost_per_second_usd: float | None = None
    is_default: bool = False


CATALOG: tuple[ProviderSpec, ...] = (
    ProviderSpec("comfyui_local", "ComfyUI local", "local", "economique", 0.0, is_default=True),
    ProviderSpec("wan22_local", "Wan 2.2 local", "local", "economique", 0.0),
    ProviderSpec("ltx_video_local", "LTX Video local", "local", "economique", 0.0),
    ProviderSpec("cogvideox_local", "CogVideoX local", "local", "economique", 0.0),
    ProviderSpec("pika_h3_flex", "Pika H3 Flex", "external", "standard"),
    ProviderSpec("hailuo_fast", "Hailuo / MiniMax", "external", "standard"),
    ProviderSpec("kling", "Kling", "external", "standard"),
    ProviderSpec("runway", "Runway", "external", "standard"),
    # 0,07 $/s en 720p : tarif annonce par Google le 05/11/2026.
    ProviderSpec("gemini_omni_12_flash", "Gemini Omni 1.2 Flash", "external", "economique", 0.07),
    ProviderSpec("veo3_fast", "Veo 3 Fast", "external", "premium"),
    ProviderSpec("veo3", "Veo 3", "external", "premium"),
)


def seed_providers(session: Session) -> int:
    """Ajoute les moteurs absents sans ecraser les reglages deja modifies. Renvoie le nombre ajoute."""
    added = 0
    for spec in CATALOG:
        if session.get(Provider, spec.id) is None:
            session.add(Provider(id=spec.id, name=spec.name, kind=spec.kind, tier=spec.tier,
                                 cost_per_second_usd=spec.cost_per_second_usd, is_default=spec.is_default))
            added += 1
    session.flush()
    return added
