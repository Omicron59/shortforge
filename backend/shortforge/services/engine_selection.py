"""Choix du moteur video de chaque scene : modes economique, standard, premium ou personnalise.

Ordre de decision pour une scene :
1. moteur choisi a la main pour cette scene ;
2. moteur unique du Short (si le projet est regle « un moteur pour tout le Short ») ;
3. regle du mode selon l'importance de la scene ;
4. si le moteur est desactive ou si le budget est depasse : ComfyUI local.
Veo 3 n'est jamais choisi par defaut : uniquement en mode premium, pour les scenes exceptionnelles.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from shortforge.models import Project, Scene
from shortforge.providers.base import ProviderError, VideoRequest
from shortforge.providers.registry import ProviderRegistry
from shortforge.services.app_settings import get_value
from shortforge.services.budget import BudgetService

FALLBACK = "comfyui_local"
IMPORTANCE_LABELS = {"simple": "scène simple", "transition": "scène de transition",
                     "important": "scène importante", "exceptional": "scène exceptionnelle"}

PRESET_RULES: dict[str, dict[str, str]] = {
    "economique": {"simple": "comfyui_local", "transition": "ltx_video_local", "important": "comfyui_local",
                   "exceptional": "comfyui_local"},
    "standard": {"simple": "comfyui_local", "transition": "ltx_video_local", "important": "gemini_omni_12_flash",
                 "exceptional": "gemini_omni_12_flash"},
    "premium": {"simple": "comfyui_local", "transition": "ltx_video_local", "important": "gemini_omni_12_flash",
                "exceptional": "veo3"},
}


@dataclass(slots=True)
class EngineChoice:
    scene_id: str
    position: int
    provider_id: str
    reason: str
    estimated_cost_usd: float | None


def rules_for(session: Session, project: Project) -> dict[str, str]:
    if project.video_mode == "personnalise":
        custom = get_value(session, "engine_rules")
        if isinstance(custom, dict) and custom:
            return {**PRESET_RULES["economique"], **{str(k): str(v) for k, v in custom.items()}}
        return PRESET_RULES["standard"]
    return PRESET_RULES.get(project.video_mode, PRESET_RULES["economique"])


def preferred_provider(scene: Scene, project: Project, rules: dict[str, str], enabled: set[str]) -> tuple[str, str]:
    """(moteur, raison) avant prise en compte du budget."""
    if scene.provider_locked and scene.provider_id:
        provider_id, reason = scene.provider_id, "choisi à la main pour cette scène"
    elif project.engine_scope == "short":
        provider_id, reason = project.default_provider, "moteur unique du Short"
    else:
        provider_id = rules.get(scene.importance, FALLBACK)
        reason = f"mode {project.video_mode} : {IMPORTANCE_LABELS.get(scene.importance, scene.importance)}"
    if provider_id not in enabled and provider_id != FALLBACK:
        return FALLBACK, f"{provider_id} désactivé : ComfyUI local"
    return provider_id, reason


def scene_request(scene: Scene) -> VideoRequest:
    return VideoRequest(prompt=scene.visual_prompt or "-", negative_prompt=scene.negative_prompt,
                        duration_s=scene.duration_s, seed=scene.seed)


def plan_scenes(session: Session, project: Project, scenes: list[Scene], registry: ProviderRegistry,
                budget: BudgetService) -> list[EngineChoice]:
    """Choisit le moteur de chaque scene, estime son cout et l'enregistre sur la scene."""
    rules = rules_for(session, project)
    pending = 0.0
    choices = []
    for scene in sorted(scenes, key=lambda s: s.position):
        provider_id, reason = preferred_provider(scene, project, rules, registry.enabled)
        try:
            provider = registry.get(provider_id)
        except ProviderError:
            provider_id, reason = FALLBACK, f"moteur {provider_id} inconnu : ComfyUI local"
            provider = registry.get(FALLBACK)
        cost = provider.estimate_cost(scene_request(scene))
        if provider.kind != "local":
            decision = budget.check(cost, project_id=project.id, provider_name=provider.name, pending_usd=pending)
            if not decision.allowed:
                prefix = "Tarif inconnu" if cost is None else "Budget dépassé"
                reason = f"{prefix} : ComfyUI local ({'; '.join(decision.reasons)})"
                provider_id, cost = FALLBACK, 0.0
            else:
                pending += cost or 0.0
        scene.provider_id, scene.provider_reason, scene.estimated_cost_usd = provider_id, reason, cost or 0.0
        choices.append(EngineChoice(scene.id, scene.position, provider_id, reason, cost))
    session.flush()
    return choices
