"""Branche les services sur les etapes du pipeline, des idees jusqu'a la publication.

Voix off et musique ne sont pas encore generees : leurs etapes se terminent en le disant, et le
montage utilise une piste muette. Les sous-titres sont calcules a partir du texte des scenes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shortforge.models import Asset, Project, utcnow
from shortforge.pipeline.engine import PipelineError
from shortforge.pipeline.handlers import HandlerRegistry, StepContext
from shortforge.pipeline.steps import StepName
from shortforge.runtime import Runtime
from shortforge.services import production, render, youtube
from shortforge.services.ideas import generate_ideas, selected_idea
from shortforge.services.scripts import current_script, write_script


def _project(ctx: StepContext) -> Project:
    project = ctx.session.get(Project, ctx.project_id)
    if project is None:
        raise PipelineError("Projet introuvable.")
    return project


def build_handlers(runtime: Runtime) -> HandlerRegistry:
    registry = HandlerRegistry()

    def ideas_step(ctx: StepContext) -> dict[str, Any]:
        sources = runtime.trend_sources(ctx.session)
        result = generate_ideas(ctx.session, runtime.llm, _project(ctx), trend_sources=sources)
        return {"idea_ids": [i.id for i in result.ideas], "rejected": result.rejected, "warnings": result.warnings}

    def select_idea_check(ctx: StepContext) -> None:
        if selected_idea(ctx.session, ctx.project_id) is None:
            raise PipelineError("Choisis d'abord une idée.")

    def script_step(ctx: StepContext) -> dict[str, Any]:
        idea = selected_idea(ctx.session, ctx.project_id)
        if idea is None:
            raise PipelineError("Aucune idée choisie.")
        result = write_script(ctx.session, runtime.llm, _project(ctx), idea)
        return {"script_id": result.script.id, "version": result.script.version, "scenes": len(result.scenes),
                "estimated_duration_s": result.script.estimated_duration_s, "warnings": result.warnings}

    def approve_script(ctx: StepContext) -> None:
        script = current_script(ctx.session, ctx.project_id)
        if script is None:
            raise PipelineError("Aucun script à valider.")
        script.status = "approved"

    def storyboard_step(ctx: StepContext) -> dict[str, Any]:
        return production.create_storyboard(ctx.session, runtime, _project(ctx))

    def images_step(ctx: StepContext) -> dict[str, Any]:
        return production.generate_images(ctx.session, runtime, _project(ctx))

    def videos_step(ctx: StepContext) -> dict[str, Any]:
        return production.generate_videos(ctx.session, runtime, _project(ctx))

    def confirm_videos(ctx: StepContext) -> None:
        try:
            production.confirm_costs(ctx.session, runtime, _project(ctx))
        except production.ProductionError as exc:
            raise PipelineError(str(exc)) from exc

    def voice_step(ctx: StepContext) -> dict[str, Any]:
        return {"skipped": True, "message": "Voix off pas encore disponible : la vidéo sera exportée sans voix."}

    def subtitles_step(ctx: StepContext) -> dict[str, Any]:
        return render.create_subtitles(ctx.session, runtime.data_dir, _project(ctx))

    def music_step(ctx: StepContext) -> dict[str, Any]:
        return {"skipped": True, "message": "Pas de musique : la bibliothèque de musiques libres arrivera plus tard."}

    def render_step(ctx: StepContext) -> dict[str, Any]:
        return render.render_video(ctx.session, runtime.settings, _project(ctx))

    def check_preview(ctx: StepContext) -> None:
        if render.latest_render(ctx.session, ctx.project_id) is None:
            raise PipelineError("Aucun aperçu à valider : lance d'abord le montage.")

    def approve_final(ctx: StepContext) -> None:
        final = render.latest_render(ctx.session, ctx.project_id)
        if final is None or final.asset_id is None:
            raise PipelineError("Aucun rendu final à valider.")
        if not ctx.confirmed:
            raise PipelineError("Confirme que tu as regardé la vidéo en entier (confirm: true) pour la valider.")
        asset = ctx.session.get(Asset, final.asset_id)
        if asset is None or not Path(asset.path).is_file() or render.file_sha256(Path(asset.path)) != asset.sha256:
            raise PipelineError("Le fichier du rendu a changé ou a disparu : refais le montage.")
        final.approved_at, final.approved_by = utcnow(), ctx.actor

    def draft_step(ctx: StepContext) -> dict[str, Any]:
        return youtube.create_draft(ctx.session, runtime.settings, _project(ctx))

    def publish_hook(ctx: StepContext) -> None:
        youtube.publish(ctx.session, runtime.settings, _project(ctx), runtime.youtube, ctx.actor)

    registry.register(StepName.GENERATE_IDEAS, ideas_step)
    registry.on_approve(StepName.SELECT_IDEA, select_idea_check)
    registry.register(StepName.WRITE_SCRIPT, script_step)
    registry.on_approve(StepName.APPROVE_SCRIPT, approve_script)
    registry.register(StepName.CREATE_STORYBOARD, storyboard_step)
    registry.register(StepName.GENERATE_IMAGES, images_step)
    registry.register(StepName.GENERATE_VIDEOS, videos_step)
    registry.on_approve(StepName.GENERATE_VIDEOS, confirm_videos)
    registry.register(StepName.GENERATE_VOICE, voice_step)
    registry.register(StepName.CREATE_SUBTITLES, subtitles_step)
    registry.register(StepName.SELECT_MUSIC, music_step)
    registry.register(StepName.RENDER_VIDEO, render_step)
    registry.on_approve(StepName.REVIEW_PREVIEW, check_preview)
    registry.on_approve(StepName.APPROVE_FINAL_RENDER, approve_final)
    registry.register(StepName.CREATE_YOUTUBE_DRAFT, draft_step)
    registry.on_approve(StepName.PUBLISH, publish_hook)
    return registry
