from __future__ import annotations

from pathlib import Path

import pytest

from shortforge.config import Settings
from shortforge.services.publish_guard import PublishBlockedError, check_publish, ensure_can_publish


def settings_with(tmp_path: Path, enabled: bool) -> Settings:
    return Settings(_env_file=None, shortforge_data_dir=tmp_path,  # type: ignore[call-arg]
                    youtube_publish_enabled=enabled)


def test_publication_is_disabled_by_default(tmp_path: Path) -> None:
    assert Settings(_env_file=None).youtube_publish_enabled is False  # type: ignore[call-arg]


def test_env_example_keeps_publication_disabled() -> None:
    env = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
    assert "YOUTUBE_PUBLISH_ENABLED=false" in env


def test_all_conditions_met(tmp_path: Path) -> None:
    result = check_publish(settings_with(tmp_path, True), final_render_validated_by="utilisateur",
                           confirmed=True, actor="utilisateur")
    assert result.allowed and result.reasons == []


@pytest.mark.parametrize(
    ("enabled", "validated_by", "confirmed", "actor"),
    [
        (False, "utilisateur", True, "utilisateur"),
        (True, None, True, "utilisateur"),
        (True, "system", True, "utilisateur"),
        (True, "utilisateur", False, "utilisateur"),
        (True, "utilisateur", True, "agent"),
    ],
)
def test_any_missing_condition_blocks(tmp_path: Path, enabled: bool, validated_by: str | None,
                                      confirmed: bool, actor: str) -> None:
    with pytest.raises(PublishBlockedError) as err:
        ensure_can_publish(settings_with(tmp_path, enabled), final_render_validated_by=validated_by,
                           confirmed=confirmed, actor=actor)
    assert err.value.reasons


def test_reasons_are_in_french(tmp_path: Path) -> None:
    result = check_publish(settings_with(tmp_path, False), final_render_validated_by=None,
                           confirmed=False, actor="")
    assert len(result.reasons) == 4
    assert "désactivée" in result.reasons[0]


def test_env_example_loads_with_empty_values(tmp_path: Path) -> None:
    env = Path(__file__).resolve().parents[2] / ".env.example"
    settings = Settings(_env_file=env)  # type: ignore[call-arg]
    assert settings.gemini_api_key is None and settings.elevenlabs_cost_per_1000_chars is None
    assert settings.youtube_publish_enabled is False and settings.social_publish_enabled is False
