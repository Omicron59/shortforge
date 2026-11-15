from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.integrations.comfyui import WorkflowLibrary
from shortforge.models import Project, Provider, Scene
from shortforge.providers.registry import build_registry
from shortforge.services.app_settings import set_value
from shortforge.services.budget import BudgetService
from shortforge.services.engine_selection import PRESET_RULES, plan_scenes
from tests.fakes import ASSETS_WORKFLOWS, FakeComfyServer

IMPORTANCES = ("simple", "transition", "important", "exceptional")


def setup(session: Session, mode: str = "standard", **project_fields: str) -> tuple[Project, list[Scene]]:
    project = Project(title="Moteurs", video_mode=mode, **project_fields)
    session.add(project)
    session.flush()
    scenes = [Scene(project_id=project.id, position=i, importance=imp, duration_s=5, visual_prompt="x")
              for i, imp in enumerate(IMPORTANCES)]
    session.add_all(scenes)
    session.flush()
    return project, scenes


def plan(session: Session, settings: Settings, tmp_path: Path, project: Project, scenes: list[Scene]) -> list[str]:
    registry = build_registry(session, settings, FakeComfyServer().client(),
                              WorkflowLibrary([ASSETS_WORKFLOWS], tmp_path / "wf"))
    plan_scenes(session, project, scenes, registry, BudgetService(session, settings))
    return [s.provider_id or "" for s in scenes]


def test_standard_mode_follows_the_example_rules(session: Session, settings: Settings, tmp_path: Path) -> None:
    project, scenes = setup(session)
    assert plan(session, settings, tmp_path, project, scenes) == [
        "comfyui_local", "ltx_video_local", "gemini_omni_12_flash", "gemini_omni_12_flash"]
    assert scenes[2].estimated_cost_usd == 0.35 and "scène importante" in scenes[2].provider_reason


def test_economic_mode_is_free(session: Session, settings: Settings, tmp_path: Path) -> None:
    project, scenes = setup(session, "economique")
    providers = plan(session, settings, tmp_path, project, scenes)
    assert "veo3" not in providers and all(s.estimated_cost_usd == 0 for s in scenes)


def test_veo_is_never_chosen_outside_premium() -> None:
    for mode in ("economique", "standard"):
        assert "veo3" not in PRESET_RULES[mode].values()
    assert PRESET_RULES["premium"]["exceptional"] == "veo3"


def test_premium_without_veo_price_falls_back(session: Session, settings: Settings, tmp_path: Path) -> None:
    project, scenes = setup(session, "premium")
    providers = plan(session, settings, tmp_path, project, scenes)
    assert providers[3] == "comfyui_local" and "non configuré" in scenes[3].provider_reason


def test_budget_blocks_the_fifth_paid_scene(session: Session, settings: Settings, tmp_path: Path) -> None:
    project, _ = setup(session)
    extra = [Scene(project_id=project.id, position=10 + i, importance="important", duration_s=7, visual_prompt="x")
             for i in range(5)]
    session.add_all(extra)
    session.flush()
    providers = plan(session, settings, tmp_path, project, extra)  # 0,49 $ par scene, plafond du Short : 2 $
    assert providers == ["gemini_omni_12_flash"] * 4 + ["comfyui_local"]
    assert extra[4].provider_reason.startswith("Budget dépassé : ComfyUI local")


def test_manual_choice_wins(session: Session, settings: Settings, tmp_path: Path) -> None:
    session.get(Provider, "kling").cost_per_second_usd = 0.08  # type: ignore[union-attr]
    project, scenes = setup(session)
    scenes[0].provider_id, scenes[0].provider_locked = "kling", True
    assert plan(session, settings, tmp_path, project, scenes)[0] == "kling"
    assert scenes[0].provider_reason == "choisi à la main pour cette scène"


def test_manual_choice_with_unknown_price_falls_back(session: Session, settings: Settings, tmp_path: Path) -> None:
    project, scenes = setup(session)
    scenes[0].provider_id, scenes[0].provider_locked = "kling", True
    assert plan(session, settings, tmp_path, project, scenes)[0] == "comfyui_local"
    assert scenes[0].provider_reason.startswith("Tarif inconnu : ComfyUI local")


def test_single_engine_for_the_whole_short(session: Session, settings: Settings, tmp_path: Path) -> None:
    project, scenes = setup(session, engine_scope="short", default_provider="wan22_local")
    assert set(plan(session, settings, tmp_path, project, scenes)) == {"wan22_local"}


def test_disabled_provider_falls_back(session: Session, settings: Settings, tmp_path: Path) -> None:
    session.get(Provider, "gemini_omni_12_flash").enabled = False  # type: ignore[union-attr]
    project, scenes = setup(session)
    assert plan(session, settings, tmp_path, project, scenes)[2] == "comfyui_local"
    assert "désactivé" in scenes[2].provider_reason


def test_custom_rules(session: Session, settings: Settings, tmp_path: Path) -> None:
    set_value(session, "engine_rules", {"simple": "cogvideox_local"})
    project, scenes = setup(session, "personnalise")
    assert plan(session, settings, tmp_path, project, scenes)[0] == "cogvideox_local"
