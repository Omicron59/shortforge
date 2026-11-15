"""Budget : plafonds, depenses et historique."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.deps import get_session, get_settings_dep
from shortforge.schemas import BudgetLimits, CostOut
from shortforge.services.app_settings import set_budget_limits
from shortforge.services.budget import BudgetService

router = APIRouter(prefix="/api/budget", tags=["budget"])


@router.get("")
def summary(session: Session = Depends(get_session),
            settings: Settings = Depends(get_settings_dep)) -> dict[str, float]:
    return BudgetService(session, settings).summary()


@router.put("/limits")
def update_limits(payload: BudgetLimits, session: Session = Depends(get_session),
                  settings: Settings = Depends(get_settings_dep)) -> dict[str, float]:
    set_budget_limits(session, payload.model_dump(exclude_none=True))
    return BudgetService(session, settings).summary()


@router.get("/history", response_model=list[CostOut])
def history(limit: int = Query(default=100, ge=1, le=1000), session: Session = Depends(get_session),
            settings: Settings = Depends(get_settings_dep)) -> list[CostOut]:
    return [CostOut.model_validate(c) for c in BudgetService(session, settings).history(limit)]
