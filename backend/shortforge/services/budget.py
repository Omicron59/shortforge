"""Budget : plafonds par scene, par Short, par jour et par mois, historique et confirmations.

Regles :
- un tarif inconnu bloque l'appel (on ne depense jamais « a l'aveugle ») ;
- tout appel payant demande une confirmation explicite, enregistree dans `costs` (kind=confirmation) ;
- seules les depenses reelles (kind=actual) comptent dans les plafonds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.models import Cost, utcnow
from shortforge.services.app_settings import budget_limits

EPSILON = 1e-9


def format_usd(amount: float) -> str:
    """0.35 -> « 0,35 dollar » ; 2.5 -> « 2,50 dollars »."""
    unit = "dollar" if amount < 2 else "dollars"
    return f"{amount:.2f}".replace(".", ",") + f" {unit}"


def confirmation_message(provider_name: str, duration_s: float, amount: float) -> str:
    seconds = f"{duration_s:g}".replace(".", ",")
    return (f"Cette scène utilisera {provider_name}.\nDurée : {seconds} secondes.\n"
            f"Coût estimé : {format_usd(amount)}.\nConfirmer la génération ?")


@dataclass(slots=True)
class BudgetDecision:
    allowed: bool
    amount: float | None
    reasons: list[str] = field(default_factory=list)


class BudgetService:
    def __init__(self, session: Session, settings: Settings, now: datetime | None = None) -> None:
        self.session = session
        self.settings = settings
        self._now = now

    @property
    def now(self) -> datetime:
        return self._now or utcnow()

    def limits(self) -> dict[str, float]:
        return budget_limits(self.session, self.settings)

    def spent(self, *, project_id: str | None = None, since: datetime | None = None) -> float:
        query = select(func.coalesce(func.sum(Cost.amount_usd), 0.0)).where(Cost.kind == "actual")
        if project_id is not None:
            query = query.where(Cost.project_id == project_id)
        if since is not None:
            query = query.where(Cost.created_at >= since)
        return float(self.session.scalar(query) or 0.0)

    def day_start(self) -> datetime:
        return self.now.replace(hour=0, minute=0, second=0, microsecond=0)

    def month_start(self) -> datetime:
        return self.day_start().replace(day=1)

    def check(self, amount: float | None, *, project_id: str, provider_name: str = "",
              pending_usd: float = 0.0) -> BudgetDecision:
        """Peut-on depenser `amount` ? `pending_usd` = depenses deja prevues pour ce Short."""
        if amount is None:
            return BudgetDecision(False, None, [f"tarif de {provider_name or 'ce moteur'} non configuré"])
        if amount <= 0:
            return BudgetDecision(True, 0.0)
        limits = self.limits()
        reasons = []
        if amount > limits["budget_max_per_scene"] + EPSILON:
            reasons.append(f"dépasse le budget par scène ({format_usd(limits['budget_max_per_scene'])})")
        checks = (
            ("par Short", self.spent(project_id=project_id) + pending_usd, "budget_max_per_short"),
            ("du jour", self.spent(since=self.day_start()) + pending_usd, "budget_max_per_day"),
            ("du mois", self.spent(since=self.month_start()) + pending_usd, "budget_max_per_month"),
        )
        for label, already, key in checks:
            if already + amount > limits[key] + EPSILON:
                reasons.append(f"dépasse le budget {label} ({format_usd(limits[key])}, déjà {format_usd(already)})")
        return BudgetDecision(not reasons, amount, reasons)

    def record(self, amount: float, *, project_id: str | None, scene_id: str | None = None,
               provider_id: str | None = None, provider_job_id: str | None = None, description: str = "") -> Cost:
        cost = Cost(amount_usd=amount, kind="actual", project_id=project_id, scene_id=scene_id,
                    provider_id=provider_id, provider_job_id=provider_job_id, description=description)
        self.session.add(cost)
        self.session.flush()
        return cost

    def confirm(self, *, project_id: str, scene_id: str, provider_id: str, amount: float,
                description: str = "") -> Cost:
        """Enregistre la confirmation humaine d'une depense a venir."""
        cost = Cost(amount_usd=amount, kind="confirmation", project_id=project_id, scene_id=scene_id,
                    provider_id=provider_id, description=description or "Génération confirmée")
        self.session.add(cost)
        self.session.flush()
        return cost

    def open_confirmation(self, scene_id: str, provider_id: str, amount: float) -> Cost | None:
        """Confirmation non encore utilisee qui couvre ce montant, s'il y en a une."""
        rows = self.session.scalars(
            select(Cost).where(Cost.kind == "confirmation", Cost.scene_id == scene_id, Cost.provider_id == provider_id,
                               Cost.provider_job_id.is_(None)).order_by(Cost.created_at.desc())
        )
        return next((c for c in rows if c.amount_usd + EPSILON >= amount), None)

    def history(self, limit: int = 100) -> list[Cost]:
        return list(self.session.scalars(
            select(Cost).where(Cost.kind == "actual").order_by(Cost.created_at.desc()).limit(limit)))

    def summary(self) -> dict[str, float]:
        limits = self.limits()
        today, month = self.spent(since=self.day_start()), self.spent(since=self.month_start())
        return {**limits, "spent_today": round(today, 4), "spent_month": round(month, 4),
                "remaining_today": round(max(0.0, limits["budget_max_per_day"] - today), 4),
                "remaining_month": round(max(0.0, limits["budget_max_per_month"] - month), 4)}
