from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.models import Cost, Project, Scene
from shortforge.services.app_settings import SettingsError, set_budget_limits, set_value
from shortforge.services.budget import BudgetService, confirmation_message, format_usd

NOW = datetime(2026, 11, 15, 12, 0)


def project(session: Session) -> Project:
    p = Project(title="Budget")
    session.add(p)
    session.flush()
    return p


def spend(session: Session, amount: float, when: datetime, project_id: str | None = None) -> None:
    session.add(Cost(amount_usd=amount, kind="actual", project_id=project_id, created_at=when))
    session.flush()


def test_confirmation_message_matches_the_spec() -> None:
    assert confirmation_message("Gemini Omni 1.2 Flash", 5, 0.35) == (
        "Cette scène utilisera Gemini Omni 1.2 Flash.\nDurée : 5 secondes.\n"
        "Coût estimé : 0,35 dollar.\nConfirmer la génération ?")
    assert format_usd(2.5) == "2,50 dollars"


def test_free_and_unknown_costs(session: Session, settings: Settings) -> None:
    budget = BudgetService(session, settings, now=NOW)
    p = project(session)
    assert budget.check(0, project_id=p.id).allowed
    decision = budget.check(None, project_id=p.id, provider_name="Kling")
    assert not decision.allowed and "non configuré" in decision.reasons[0]


def test_per_scene_limit(session: Session, settings: Settings) -> None:
    p = project(session)
    decision = BudgetService(session, settings, now=NOW).check(0.6, project_id=p.id)
    assert not decision.allowed and "par scène" in decision.reasons[0]


def test_per_short_limit_includes_pending(session: Session, settings: Settings) -> None:
    p = project(session)
    spend(session, 1.8, NOW, p.id)
    budget = BudgetService(session, settings, now=NOW)
    assert budget.check(0.2, project_id=p.id).allowed
    assert not budget.check(0.2, project_id=p.id, pending_usd=0.1).allowed


def test_day_and_month_limits(session: Session, settings: Settings) -> None:
    p = project(session)
    spend(session, 4.9, NOW - timedelta(hours=1))
    budget = BudgetService(session, settings, now=NOW)
    reasons = budget.check(0.2, project_id=p.id).reasons
    assert any("du jour" in r for r in reasons)
    spend(session, 25, NOW - timedelta(days=3))
    assert any("du mois" in r for r in budget.check(0.2, project_id=p.id).reasons)
    spend(session, 100, datetime(2026, 10, 30))  # mois precedent : ne compte pas
    summary = budget.summary()
    assert summary["spent_month"] == 29.9 and summary["remaining_today"] == 0.1


def test_limits_can_be_changed_in_the_app(session: Session, settings: Settings) -> None:
    set_budget_limits(session, {"budget_max_per_scene": 1.0})
    assert BudgetService(session, settings).limits()["budget_max_per_scene"] == 1.0
    with pytest.raises(SettingsError):
        set_budget_limits(session, {"budget_max_per_scene": -1})
    with pytest.raises(SettingsError):
        set_value(session, "gemini_api_key", "secret")


def test_confirmations_are_single_use(session: Session, settings: Settings) -> None:
    p = project(session)
    scene = Scene(project_id=p.id, position=0)
    session.add(scene)
    session.flush()
    budget = BudgetService(session, settings)
    assert budget.open_confirmation(scene.id, "gemini_omni_12_flash", 0.35) is None
    conf = budget.confirm(project_id=p.id, scene_id=scene.id, provider_id="gemini_omni_12_flash", amount=0.35)
    assert budget.open_confirmation(scene.id, "gemini_omni_12_flash", 0.35) is conf
    assert budget.open_confirmation(scene.id, "gemini_omni_12_flash", 0.50) is None
    assert budget.open_confirmation(scene.id, "kling", 0.35) is None
    assert budget.spent() == 0  # une confirmation n'est pas une depense


def test_history_lists_actual_costs(session: Session, settings: Settings) -> None:
    budget = BudgetService(session, settings)
    budget.record(0.35, project_id=None, description="Gemini")
    assert [c.description for c in budget.history()] == ["Gemini"]
