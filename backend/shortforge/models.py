"""Modeles SQLite de ShortForge.

Les 15 tables du cahier des charges, plus `pipeline_steps` qui sauvegarde l'etat de chaque
etape du pipeline pour pouvoir reprendre un projet interrompu.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shortforge.db import Base


def utcnow() -> datetime:
    """Horodatage UTC (stocke sans fuseau dans SQLite)."""
    return datetime.now(UTC).replace(tzinfo=None)


def new_id() -> str:
    return uuid.uuid4().hex


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(200))
    niche: Mapped[str] = mapped_column(String(200), default="")
    language: Mapped[str] = mapped_column(String(10), default="fr")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|in_progress|done|cancelled
    current_step: Mapped[str | None] = mapped_column(String(40), nullable=True)
    video_mode: Mapped[str] = mapped_column(String(20), default="economique")
    default_provider: Mapped[str] = mapped_column(String(40), default="comfyui_local")
    # "short" : un seul moteur pour tout le Short ; "scene" : moteur choisi scene par scene.
    engine_scope: Mapped[str] = mapped_column(String(10), default="scene")

    steps: Mapped[list[PipelineStep]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="PipelineStep.position"
    )


class PipelineStep(TimestampMixin, Base):
    __tablename__ = "pipeline_steps"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    position: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    validated_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    project: Mapped[Project] = relationship(back_populates="steps")


class Idea(Base):
    __tablename__ = "ideas"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    hook: Mapped[str] = mapped_column(Text, default="")
    original_angle: Mapped[str] = mapped_column(Text, default="")
    estimated_duration_s: Mapped[float] = mapped_column(Float, default=0)
    potential_score: Mapped[float] = mapped_column(Float, default=0)  # 0 a 100
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    reuse_risk: Mapped[str] = mapped_column(String(10), default="low")  # low|medium|high
    visual_style: Mapped[str] = mapped_column(Text, default="")
    sources: Mapped[list[str]] = mapped_column(JSON, default=list)  # tendances d'inspiration
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Script(TimestampMixin, Base):
    __tablename__ = "scripts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    idea_id: Mapped[str | None] = mapped_column(ForeignKey("ideas.id", ondelete="SET NULL"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    hook: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    conclusion: Mapped[str] = mapped_column(Text, default="")
    call_to_action: Mapped[str] = mapped_column(Text, default="")
    estimated_duration_s: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|approved|rejected


class Scene(TimestampMixin, Base):
    __tablename__ = "scenes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    script_id: Mapped[str | None] = mapped_column(ForeignKey("scripts.id", ondelete="CASCADE"), nullable=True)
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    visual_prompt: Mapped[str] = mapped_column(Text, default="")
    negative_prompt: Mapped[str] = mapped_column(Text, default="")
    transition: Mapped[str] = mapped_column(String(40), default="cut")
    duration_s: Mapped[float] = mapped_column(Float, default=3)
    importance: Mapped[str] = mapped_column(String(20), default="simple")  # simple|transition|important|exceptional
    provider_id: Mapped[str | None] = mapped_column(ForeignKey("providers.id"), nullable=True)
    provider_locked: Mapped[bool] = mapped_column(Boolean, default=False)  # choisi a la main
    provider_reason: Mapped[str] = mapped_column(Text, default="")
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_status: Mapped[str] = mapped_column(String(20), default="pending")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # statut de la video


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    scene_id: Mapped[str | None] = mapped_column(ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))  # image|video|audio|music|thumbnail|subtitle|import
    path: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(100), default="")
    origin: Mapped[str] = mapped_column(String(20), default="generated")  # generated|imported
    license: Mapped[str] = mapped_column(String(100), default="")
    rights_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class VoiceTake(Base):
    __tablename__ = "voice_takes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    script_id: Mapped[str | None] = mapped_column(ForeignKey("scripts.id", ondelete="SET NULL"), nullable=True)
    engine: Mapped[str] = mapped_column(String(20), default="piper")  # xtts|piper|f5tts
    voice_gender: Mapped[str] = mapped_column(String(10), default="female")
    language: Mapped[str] = mapped_column(String(10), default="fr")
    speed: Mapped[float] = mapped_column(Float, default=1.0)
    pitch: Mapped[float] = mapped_column(Float, default=0.0)
    emotion: Mapped[str] = mapped_column(String(30), default="neutre")
    pauses: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Subtitle(TimestampMixin, Base):
    __tablename__ = "subtitles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    voice_take_id: Mapped[str | None] = mapped_column(
        ForeignKey("voice_takes.id", ondelete="SET NULL"), nullable=True
    )
    segments: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # [{start, end, text}]
    style: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # police, couleurs, animation
    position: Mapped[str] = mapped_column(String(20), default="bottom")


class Render(Base):
    __tablename__ = "renders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10), default="preview")  # preview|final
    width: Mapped[int] = mapped_column(Integer, default=1080)
    height: Mapped[int] = mapped_column(Integer, default=1920)
    codec: Mapped[str] = mapped_column(String(20), default="h264")
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Provider(TimestampMixin, Base):
    __tablename__ = "providers"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(10))  # local|external
    tier: Mapped[str] = mapped_column(String(20))  # economique|standard|premium
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    cost_per_second_usd: Mapped[float | None] = mapped_column(Float, nullable=True)  # None = a configurer
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ProviderJob(TimestampMixin, Base):
    __tablename__ = "provider_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    scene_id: Mapped[str | None] = mapped_column(ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True)
    operation: Mapped[str] = mapped_column(String(40))  # generate_from_text, generate_from_image, ...
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0)
    result_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Cost(Base):
    __tablename__ = "costs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    scene_id: Mapped[str | None] = mapped_column(ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True)
    provider_id: Mapped[str | None] = mapped_column(ForeignKey("providers.id"), nullable=True)
    provider_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("provider_jobs.id", ondelete="SET NULL"), nullable=True
    )
    amount_usd: Mapped[float] = mapped_column(Float)
    kind: Mapped[str] = mapped_column(String(15), default="actual")  # confirmation|actual
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class YoutubeChannel(Base):
    __tablename__ = "youtube_channels"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    channel_id: Mapped[str] = mapped_column(String(100), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # Les jetons OAuth ne sont jamais en base : seulement le chemin du fichier local.
    token_path: Mapped[str] = mapped_column(Text, default="")
    connected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PublishJob(TimestampMixin, Base):
    __tablename__ = "publish_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    render_id: Mapped[str | None] = mapped_column(ForeignKey("renders.id", ondelete="SET NULL"), nullable=True)
    channel_id: Mapped[str | None] = mapped_column(
        ForeignKey("youtube_channels.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(100), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    privacy: Mapped[str] = mapped_column(String(10), default="private")  # private|unlisted|public
    made_for_kids: Mapped[bool] = mapped_column(Boolean, default=False)
    category_id: Mapped[str] = mapped_column(String(5), default="22")  # 22 = People & Blogs
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ai_disclosure: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    human_approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    human_approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    youtube_video_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Analytics(Base):
    __tablename__ = "analytics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    publish_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("publish_jobs.id", ondelete="CASCADE"), index=True
    )
    youtube_video_id: Mapped[str] = mapped_column(String(50), index=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    average_view_duration_s: Mapped[float] = mapped_column(Float, default=0)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
