"""Montage FFmpeg reel, apercu, validation humaine, brouillon YouTube, verification finale et publication."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.models import Project, PublishJob, Scene, YoutubeChannel
from shortforge.pipeline import PipelineError, PipelineService, StepName
from shortforge.pipeline.default_handlers import build_handlers
from shortforge.runtime import Runtime
from shortforge.services import render, youtube
from shortforge.services.ideas import select_idea
from shortforge.services.publish_guard import PublishBlockedError
from tests.fakes import FakeComfyServer, FakeGoogleApi, FakeLLM, add_video_workflow, ideas_response, make_runtime
from tests.fakes import script_response as base_script

FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="FFmpeg absent")


# ── Medias reels pour FFmpeg ──


class MediaComfy(FakeComfyServer):
    def __init__(self, png: bytes) -> None:
        super().__init__()
        self.png = png

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/view":
            return httpx.Response(200, content=self.png)
        return super().handler(request)


class MediaGoogle(FakeGoogleApi):
    def __init__(self, mp4: bytes) -> None:
        super().__init__()
        self.mp4 = mp4

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "files.test":
            return httpx.Response(200, content=self.mp4)
        self.polls = max(self.polls, 1)
        return super().handler(request)


class FakeYouTube:
    """Simule Google OAuth et l'API YouTube (chaine + envoi en deux temps)."""

    def __init__(self) -> None:
        self.metadata: dict[str, Any] | None = None
        self.uploaded = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(youtube.TOKEN_URL):
            return httpx.Response(200, json={"access_token": "acces", "refresh_token": "durable", "expires_in": 3600})
        if "/youtube/v3/channels" in url:
            return httpx.Response(200, json={"items": [{"id": "UC123", "snippet": {"title": "Ma chaîne"}}]})
        if url.startswith(youtube.UPLOAD_URL) and request.method == "POST":
            assert request.headers["authorization"] == "Bearer acces"
            self.metadata = json.loads(request.content)
            return httpx.Response(200, headers={"location": "https://upload.test/session/1"})
        if url.startswith("https://upload.test/session/1"):
            self.uploaded = len(request.content)
            return httpx.Response(200, json={"id": "vid42"})
        return httpx.Response(404)


def script_with_text() -> dict[str, Any]:
    response = base_script(("simple", "important"))
    for scene in response["scenes"]:
        scene["text"] = "Ce grille-pain chante chaque matin sans raison"
        scene["transition"] = "fondu"
        scene["duration_s"] = 3
    return response


def build(session: Session, tmp_path: Path, media: dict[str, bytes], *, publish: bool = False,
          yt: FakeYouTube | None = None) -> tuple[PipelineService, Runtime, Settings, str]:
    secrets_file = tmp_path / "client_secret.json"
    secrets_file.write_text(json.dumps({"installed": {"client_id": "id", "client_secret": "secret"}}))
    settings = Settings(_env_file=None, shortforge_data_dir=tmp_path, gemini_api_key="cle-test",  # type: ignore[call-arg]
                        youtube_publish_enabled=publish, youtube_client_secrets_file=str(secrets_file))
    runtime = make_runtime(settings, FakeLLM(ideas_response("Le grille-pain qui chante"), script_with_text()),
                           comfy=MediaComfy(media["png"]), provider_handler=MediaGoogle(media["mp4"]).handler)
    runtime.youtube_transport = httpx.MockTransport((yt or FakeYouTube()).handler)
    add_video_workflow(runtime.library, "comfyui_local")
    service = PipelineService(session, settings, build_handlers(runtime))
    project = service.create_project("Grille-pain", niche="humour", video_mode="standard")
    return service, runtime, settings, project.id


def run_to_render(service: PipelineService, session: Session, project_id: str) -> None:
    service.advance(project_id)
    service.advance(project_id)
    idea_id = service.get_step(project_id, StepName.GENERATE_IDEAS).output["idea_ids"][0]  # type: ignore[index]
    select_idea(session, project_id, idea_id)
    service.approve(project_id, StepName.SELECT_IDEA, actor="utilisateur")
    service.advance(project_id)
    service.advance(project_id)
    service.approve(project_id, StepName.APPROVE_SCRIPT, actor="utilisateur")
    service.advance(project_id)  # decoupage
    service.advance(project_id)  # images
    service.advance(project_id)  # videos : confirmation de la depense
    service.approve(project_id, StepName.GENERATE_VIDEOS, actor="utilisateur", confirmed=True)
    assert service.advance(project_id).status == "done"
    for _ in range(4):  # voix, sous-titres, musique, montage
        step = service.advance(project_id)
        assert step.status == "done", (step.name, step.error)


def approve_until_draft(service: PipelineService, project_id: str) -> None:
    assert service.advance(project_id).name == "review_preview"
    service.approve(project_id, StepName.REVIEW_PREVIEW, actor="utilisateur")
    assert service.advance(project_id).name == "approve_final_render"
    service.approve(project_id, StepName.APPROVE_FINAL_RENDER, actor="utilisateur", confirmed=True)
    assert service.advance(project_id).status == "done"  # brouillon YouTube


def connect_channel(session: Session, settings: Settings) -> None:
    token = settings.shortforge_data_dir / "youtube" / "token.json"
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text(json.dumps({"refresh_token": "durable"}))
    session.add(YoutubeChannel(channel_id="UC123", title="Ma chaîne", token_path=str(token), is_default=True))
    session.flush()


# ── Sous-titres et commande FFmpeg (sans FFmpeg) ──


def test_subtitles_follow_scene_timing() -> None:
    from shortforge.services import subtitles as subs

    scenes = [Scene(text="un deux trois quatre cinq", duration_s=4), Scene(text="", duration_s=2),
              Scene(text="six sept", duration_s=3)]
    words = subs.words_from_scenes(scenes)
    assert words[4] == {"word": "cinq", "start": 3.2, "end": 4.0} and words[5]["start"] == 6.0
    segments = subs.group_lines(words, 3)
    assert [s["text"] for s in segments] == ["un deux trois", "quatre cinq", "six sept"]
    srt = subs.to_srt(segments)
    assert srt.startswith("1\n00:00:00,000 --> 00:00:02,400\nun deux trois\n")
    ass = subs.to_ass(segments, subs.preset_style("classique", {"position": "top", "color": "#FF0000"}))
    assert "PlayResY: 1920" in ass and ",&H000000FF," in ass and ",8,80,80,260," in ass
    assert "Dialogue: 0,0:00:06.00,0:00:09.00,Default,,0,0,0,,six sept" in ass


def test_ffmpeg_command_targets_vertical_h264(tmp_path: Path) -> None:
    plan = render.RenderPlan(clips=[render.ClipInput(tmp_path / "a.mp4", 3, False, "fondu"),
                                    render.ClipInput(tmp_path / "b.png", 2.5, True)],
                             output=tmp_path / "out.mp4", subtitles=tmp_path / "s.ass")
    cmd = render.build_command("ffmpeg", plan)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920" in graph
    assert "fade=t=in:st=0:d=0.4" in graph and "concat=n=2" in graph and "ass=s.ass" in graph
    assert "anullsrc=r=48000:cl=stereo" in cmd  # piste muette sans voix
    assert cmd[cmd.index("-c:v") + 1] == "libx264" and cmd[cmd.index("-t", cmd.index("-map")) + 1] == "5.5"
    assert cmd[cmd.index("-loop"):cmd.index("-loop") + 2] == ["-loop", "1"]


def test_spec_problems_detects_wrong_format() -> None:
    ok = {"width": 1080, "height": 1920, "video_codec": "h264", "audio_codec": "aac", "duration_s": 20}
    assert render.spec_problems(ok) == []
    bad = render.spec_problems({**ok, "width": 1920, "height": 1080, "duration_s": 200})
    assert len(bad) == 2


# ── Parcours complet avec FFmpeg ──


@needs_ffmpeg
def test_export_preview_validation_and_draft(session: Session, tmp_path: Path, media: dict[str, bytes]) -> None:
    service, _, settings, project_id = build(session, tmp_path, media)
    run_to_render(service, session, project_id)

    final = render.latest_render(session, project_id)
    assert final is not None and final.approved_at is None
    out = service.get_step(project_id, StepName.RENDER_VIDEO).output or {}
    assert (out["width"], out["height"], out["video_codec"], out["audio_codec"]) == (1080, 1920, "h264", "aac")
    assert out["duration_s"] == pytest.approx(6, abs=0.1)
    assert out["quality"]["score"] >= 7, out["quality"]
    voice_step = service.get_step(project_id, StepName.GENERATE_VOICE).output or {}
    assert voice_step["engine"] == "Voix de test" and voice_step["scenes"] == 2

    assert service.advance(project_id).status == "needs_validation"  # apercu
    service.approve(project_id, StepName.REVIEW_PREVIEW, actor="utilisateur")
    service.advance(project_id)
    with pytest.raises(PipelineError, match="regardé la vidéo"):
        service.approve(project_id, StepName.APPROVE_FINAL_RENDER, actor="utilisateur")
    with pytest.raises(PipelineError, match="personne"):
        service.approve(project_id, StepName.APPROVE_FINAL_RENDER, actor="agent", confirmed=True)
    service.approve(project_id, StepName.APPROVE_FINAL_RENDER, actor="utilisateur", confirmed=True)
    assert render.latest_render(session, project_id).approved_by == "utilisateur"  # type: ignore[union-attr]

    draft_step = service.advance(project_id)
    assert draft_step.status == "done" and "rien n'a été envoyé" in draft_step.output["message"]  # type: ignore[index]
    draft = youtube.current_draft(session, project_id)
    assert draft is not None and draft.privacy == "private" and draft.status == "draft"
    assert settings.ai_disclosure_text in draft.description and "#Shorts" in draft.description

    gate = service.advance(project_id)
    assert gate.name == "publish" and gate.status == "needs_validation"
    with pytest.raises(PublishBlockedError, match="désactivée"):
        service.approve(project_id, StepName.PUBLISH, actor="utilisateur", confirmed=True)


@needs_ffmpeg
def test_preview_rejection_redoes_the_render(session: Session, tmp_path: Path, media: dict[str, bytes]) -> None:
    service, _, _, project_id = build(session, tmp_path, media)
    run_to_render(service, session, project_id)
    service.advance(project_id)
    service.reject(project_id, StepName.REVIEW_PREVIEW, reason="sous-titres trop bas")
    assert service.next_step(project_id).name == "render_video"  # type: ignore[union-attr]


@needs_ffmpeg
def test_publication_needs_every_final_check(session: Session, tmp_path: Path, media: dict[str, bytes]) -> None:
    yt = FakeYouTube()
    service, _, settings, project_id = build(session, tmp_path, media, publish=True, yt=yt)
    run_to_render(service, session, project_id)
    approve_until_draft(service, project_id)
    service.advance(project_id)  # publish -> needs_validation
    project = session.get(Project, project_id)
    assert project is not None

    # Pas de chaine connectee : la verification finale bloque, rien n'est envoye
    with pytest.raises(PublishBlockedError, match="Chaîne YouTube connectée"):
        service.approve(project_id, StepName.PUBLISH, actor="utilisateur", confirmed=True)
    assert yt.metadata is None

    connect_channel(session, settings)
    # Mention IA retiree : bloque aussi
    youtube.update_draft(session, settings, project_id, {"description": "Sans mention"})
    with pytest.raises(PublishBlockedError, match="Mention"):
        service.approve(project_id, StepName.PUBLISH, actor="utilisateur", confirmed=True)
    youtube.update_draft(session, settings, project_id, {"description": f"Ok. {settings.ai_disclosure_text}"})

    # Sans confirmation explicite : bloque par le garde-fou
    with pytest.raises(PublishBlockedError, match="confirmée"):
        service.approve(project_id, StepName.PUBLISH, actor="utilisateur")

    checks = youtube.checks_as_dict(youtube.final_checks(session, settings, project))
    assert checks["ready"] is True, [c for c in checks["checks"] if not c["ok"]]
    step = service.approve(project_id, StepName.PUBLISH, actor="utilisateur", confirmed=True)
    assert step.status == "done"
    job = youtube.current_draft(session, project_id)
    assert isinstance(job, PublishJob) and job.status == "published" and job.youtube_video_id == "vid42"
    assert job.human_approved_by == "utilisateur" and yt.uploaded > 1000
    assert yt.metadata is not None and yt.metadata["status"] == {
        "privacyStatus": "private", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}
    with pytest.raises(youtube.YouTubeError, match="déjà été envoyée"):
        youtube.update_draft(session, settings, project_id, {"title": "Autre"})


@needs_ffmpeg
def test_modified_render_file_fails_the_final_check(session: Session, tmp_path: Path,
                                                    media: dict[str, bytes]) -> None:
    service, _, settings, project_id = build(session, tmp_path, media, publish=True)
    run_to_render(service, session, project_id)
    approve_until_draft(service, project_id)
    final = render.latest_render(session, project_id)
    assert final is not None
    from shortforge.models import Asset

    asset = session.get(Asset, final.asset_id)
    assert asset is not None
    with Path(asset.path).open("ab") as handle:
        handle.write(b"modifie")
    project = session.get(Project, project_id)
    assert project is not None
    failed = {c.id for c in youtube.final_checks(session, settings, project) if not c.ok}
    assert "render_unchanged" in failed


# ── Connexion OAuth ──


def test_oauth_connection_saves_token_file_only(session: Session, tmp_path: Path) -> None:
    secrets_file = tmp_path / "client_secret.json"
    secrets_file.write_text(json.dumps({"installed": {"client_id": "id", "client_secret": "secret"}}))
    settings = Settings(_env_file=None, shortforge_data_dir=tmp_path,  # type: ignore[call-arg]
                        youtube_client_secrets_file=str(secrets_file))
    client = youtube.YouTubeClient(settings, transport=httpx.MockTransport(FakeYouTube().handler))
    url = client.authorization_url()
    assert "youtube.upload" in url and "127.0.0.1%3A8787%2Fapi%2Fyoutube%2Foauth%2Fcallback" in url
    with pytest.raises(youtube.YouTubeError, match="sécurité"):
        client.finish_authorization(session, "code", "mauvais")
    state = url.split("state=")[1].split("&")[0]
    client.authorization_url()  # un nouvel essai invalide l'ancien jeton
    with pytest.raises(youtube.YouTubeError):
        client.finish_authorization(session, "code", state)
    url = client.authorization_url()
    channel = client.finish_authorization(session, "code", url.split("state=")[1].split("&")[0])
    assert channel.title == "Ma chaîne" and Path(channel.token_path).is_file()
    saved = json.loads(Path(channel.token_path).read_text())
    assert saved["refresh_token"] == "durable" and "secret" not in json.dumps(saved)
    assert client.access_token(channel) == "acces"


def test_missing_client_secrets_has_clear_message(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, shortforge_data_dir=tmp_path)  # type: ignore[call-arg]
    with pytest.raises(youtube.YouTubeError, match="YOUTUBE_CLIENT_SECRETS_FILE"):
        youtube.YouTubeClient(settings).authorization_url()
