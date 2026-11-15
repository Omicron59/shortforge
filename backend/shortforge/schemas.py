"""Schemas Pydantic v2 des entrees et sorties de l'API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

VideoMode = Literal["economique", "standard", "premium", "personnalise"]


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    niche: str = Field(default="", max_length=200)
    language: str = Field(default="fr", max_length=10)
    video_mode: VideoMode = "economique"


class StepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    label: str = ""
    position: int
    status: str
    human_gate: bool = False
    attempts: int
    output: dict[str, Any] | None
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    validated_at: datetime | None
    validated_by: str | None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    niche: str
    language: str
    status: str
    current_step: str | None
    video_mode: str
    default_provider: str
    engine_scope: str
    created_at: datetime
    updated_at: datetime


class ProjectDetail(ProjectOut):
    steps: list[StepOut]


class ApprovePayload(BaseModel):
    validated_by: str = Field(default="utilisateur", max_length=100)
    confirm: bool = False


class RejectPayload(BaseModel):
    reason: str = Field(default="", max_length=2000)


class ProviderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    kind: str
    tier: str
    enabled: bool
    is_default: bool
    cost_per_second_usd: float | None
    config: dict[str, Any] = {}
    configured: bool = False
    configuration_hint: str = ""
    operations: list[str] = []


class HealthOut(BaseModel):
    status: Literal["ok"]
    version: str
    database: str
    youtube_publish_enabled: bool


class IdeaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    hook: str
    original_angle: str
    estimated_duration_s: float
    potential_score: float
    keywords: list[str]
    reuse_risk: str
    visual_style: str
    sources: list[str]
    selected: bool


class SceneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    position: int
    text: str
    visual_prompt: str
    negative_prompt: str
    transition: str
    duration_s: float
    importance: str
    provider_id: str | None
    provider_locked: bool
    provider_reason: str
    estimated_cost_usd: float
    seed: int | None
    image_status: str
    status: str


class ScriptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version: int
    hook: str
    body: str
    conclusion: str
    call_to_action: str
    estimated_duration_s: float
    status: str


class ScriptDetail(BaseModel):
    script: ScriptOut
    scenes: list[SceneOut]
    warnings: list[str] = []


class SceneEdit(BaseModel):
    text: str = ""
    visual_prompt: str = Field(min_length=3)
    negative_prompt: str = ""
    transition: str = "cut"
    duration_s: float = 3
    importance: str = "simple"


class ScriptEdit(BaseModel):
    hook: str | None = None
    body: str | None = None
    conclusion: str | None = None
    call_to_action: str | None = None
    scenes: list[SceneEdit] | None = None


class ShortenPayload(BaseModel):
    target_duration_s: float = Field(ge=5, le=180)


class RegeneratePayload(BaseModel):
    instructions: str = Field(default="", max_length=2000)


class ScenePatch(BaseModel):
    provider_id: str | None = None  # "" = revenir au choix automatique
    importance: Literal["simple", "transition", "important", "exceptional"] | None = None
    visual_prompt: str | None = Field(default=None, min_length=3)
    negative_prompt: str | None = None
    duration_s: float | None = Field(default=None, gt=0, le=30)
    transition: str | None = None


class SceneRegenerate(BaseModel):
    target: Literal["image", "video"] = "video"


class EngineSettings(BaseModel):
    video_mode: VideoMode | None = None
    engine_scope: Literal["short", "scene"] | None = None
    default_provider: str | None = None


class ProviderPatch(BaseModel):
    enabled: bool | None = None
    cost_per_second_usd: float | None = Field(default=None, ge=0)
    config: dict[str, str] | None = None


class BudgetLimits(BaseModel):
    budget_max_per_scene: float | None = Field(default=None, ge=0)
    budget_max_per_short: float | None = Field(default=None, ge=0)
    budget_max_per_day: float | None = Field(default=None, ge=0)
    budget_max_per_month: float | None = Field(default=None, ge=0)


class CostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: str | None
    scene_id: str | None
    provider_id: str | None
    amount_usd: float
    kind: str
    description: str
    created_at: datetime


class WorkflowIn(BaseModel):
    id: str = Field(min_length=1, max_length=60)
    name: str = ""
    kind: Literal["image", "video"] = "image"
    workflow: dict[str, Any]
    inputs: dict[str, dict[str, str]] | None = None


class WorkflowOut(BaseModel):
    id: str
    name: str
    kind: str
    inputs: list[str]
    user: bool
