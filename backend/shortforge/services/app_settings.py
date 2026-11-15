"""Reglages modifiables depuis l'interface, stockes dans la table `settings`.

Les valeurs du `.env` servent de valeurs par defaut ; ce que l'utilisateur change dans
l'application est enregistre ici et prend le dessus. Les cles API n'y sont JAMAIS stockees.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.models import Setting

# Cles autorisees : rien d'autre ne peut etre ecrit (et surtout pas un secret).
BUDGET_KEYS = ("budget_max_per_scene", "budget_max_per_short", "budget_max_per_day", "budget_max_per_month")
ALLOWED_KEYS = frozenset({*BUDGET_KEYS, "engine_rules", "manual_trends", "comfyui_image_workflow"})


class SettingsError(ValueError):
    pass


def get_value(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(Setting, key)
    return default if row is None else row.value


def set_value(session: Session, key: str, value: Any) -> None:
    if key not in ALLOWED_KEYS:
        raise SettingsError(f"Réglage inconnu : {key}.")
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    session.flush()


def budget_limits(session: Session, settings: Settings) -> dict[str, float]:
    """Plafonds effectifs : valeur enregistree dans l'application, sinon celle du `.env`."""
    limits: dict[str, float] = {}
    for key in BUDGET_KEYS:
        value = get_value(session, key, getattr(settings, key))
        limits[key] = float(value)
    return limits


def set_budget_limits(session: Session, values: dict[str, float]) -> None:
    for key, value in values.items():
        if key not in BUDGET_KEYS:
            raise SettingsError(f"Plafond inconnu : {key}.")
        if value < 0:
            raise SettingsError("Un plafond de budget ne peut pas être négatif.")
        set_value(session, key, float(value))
