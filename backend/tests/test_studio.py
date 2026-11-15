"""Voix off, sous-titres animes, musique, logo, controle qualite, croissance, planning, videos longues
et publications multi-plateformes."""

from __future__ import annotations

import contextlib
import json
import stat
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from shortforge.config import Settings
from shortforge.integrations import tts
from shortforge.integrations.postiz import PostizClient
from shortforge.main import create_app
from shortforge.models import Analytics, Competitor, CompetitorVideo, MusicTrack, Project, SocialPost, utcnow
from shortforge.pipeline import PipelineError, PipelineService, StepName
from shortforge.pipeline.default_handlers import build_handlers
from shortforge.services import clips, growth, music, planning, quality, social, voice, youtube
from shortforge.services import subtitles as subs
from shortforge.services.app_settings import set_value
from shortforge.services.publish_guard import check_publish
from tests.fakes import FakeLLM, FakeTranscriber, ideas_response, make_runtime, script_response
from tests.test_release import (
    FFMPEG,
    FakeYouTube,
    approve_until_draft,
    build,
    connect_channel,
    run_to_render,
)

needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="FFmpeg absent")


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def settings_for(tmp_path: Path, **kw: Any) -> Settings:
    return Settings(_env_file=None, shortforge_data_dir=tmp_path, **kw)  # type: ignore[call-arg]


# ── Voix off ──


def test_system_voice_commands_per_os(tmp_path: Path) -> None:
    s = settings_for(tmp_path)
    win = tts.SystemEngine(s, "win32")
    win._program = lambda: "powershell"  # type: ignore[method-assign]
    cmd = win.command(tmp_path / "t.txt", tmp_path / "v.wav", language="fr", speed=1.2)
    assert cmd[0] == "powershell" and "System.Speech" in cmd[-1] and "$s.Rate=2" in cmd[-1] and "fr*" in cmd[-1]
    mac = tts.SystemEngine(settings_for(tmp_path, system_voice="Thomas"), "darwin")
    mac._program = lambda: "/usr/bin/say"  # type: ignore[method-assign]
    assert mac.command(tmp_path / "t.txt", tmp_path / "v.aiff", language="fr", speed=1.0)[:3] == [
        "/usr/bin/say", "-v", "Thomas"]
    assert win.name == "Voix Windows" and mac.name == "Voix macOS"


def test_auto_engine_prefers_piper_when_ready(tmp_path: Path) -> None:
    assert tts.pick_engine(settings_for(tmp_path)).id == "system"
    model = tmp_path / "fr.onnx"
    model.write_bytes(b"x")
    ready = settings_for(tmp_path, piper_voice=str(model), piper_path=sys.executable)
    assert tts.pick_engine(ready).id == "piper"
    assert tts.pick_engine(ready, "elevenlabs").id == "elevenlabs"


@needs_ffmpeg
@pytest.mark.skipif(sys.platform == "win32", reason="faux programme en script shell")
def test_piper_engine_runs_the_program(tmp_path: Path) -> None:
    fake = tmp_path / "piper"
    fake.write_text('#!/bin/sh\nwhile [ "$1" != "--output_file" ]; do shift; done\n'
                    'cat > /dev/null\nffmpeg -v error -y -f lavfi -i sine=duration=1 "$2"\n')
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    model = tmp_path / "fr.onnx"
    model.write_bytes(b"x")
    engine = tts.PiperEngine(settings_for(tmp_path, piper_path=str(fake), piper_voice=str(model)))
    out = engine.synthesize("Bonjour tout le monde", tmp_path / "v.wav")
    assert out.is_file() and engine.estimate_cost("x") == 0.0


@needs_ffmpeg
def test_elevenlabs_needs_price_and_converts_audio(tmp_path: Path) -> None:
    mp3 = tmp_path / "s.mp3"
    ffmpeg("-f", "lavfi", "-i", "sine=duration=1", str(mp3))
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers["xi-api-key"]
        return httpx.Response(200, content=mp3.read_bytes())

    no_price = tts.ElevenLabsEngine(settings_for(tmp_path, elevenlabs_api_key="k", elevenlabs_voice_id="v"))
    assert no_price.estimate_cost("abc") is None and "tarif inconnu" in no_price.status().detail
    engine = tts.ElevenLabsEngine(settings_for(tmp_path, elevenlabs_api_key="k", elevenlabs_voice_id="v",
                                               elevenlabs_cost_per_1000_chars=0.3),
                                  transport=httpx.MockTransport(handler))
    assert engine.estimate_cost("a" * 2000) == 0.6
    assert engine.synthesize("Bonjour", tmp_path / "o.wav").is_file() and seen["key"] == "k"


# ── Sous-titres animes ──


def test_twenty_presets_and_every_effect_render_ass() -> None:
    assert len(subs.PRESETS) == 20 and len(subs.EFFECTS) == 7
    tokens = ["Le", "chat", "dort.", "Puis", "il", "part"]
    words = [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.35} for i, w in enumerate(tokens)]
    lines = subs.group_lines(words, 3)
    assert [line["text"] for line in lines] == ["Le chat dort.", "Puis il part"]
    for preset in subs.PRESETS:
        ass = subs.to_ass(lines, subs.preset_style(preset))
        assert ass.count("Dialogue:") >= 2, preset
    karaoke = subs.to_ass(lines, subs.preset_style("karaoke"))
    assert "\\kf" in karaoke
    highlight = subs.to_ass(lines, subs.preset_style("rebond"))
    assert "\\t(0,90,\\fscx118" in highlight and highlight.count("Dialogue:") == 6


@needs_ffmpeg
def test_libass_accepts_every_effect(tmp_path: Path) -> None:
    tokens = ["un", "deux", "trois", "quatre"]
    words = [{"word": w, "start": i * 0.3, "end": i * 0.3 + 0.25} for i, w in enumerate(tokens)]
    for effect in subs.EFFECTS:
        ass = tmp_path / f"{effect}.ass"
        ass.write_text(subs.to_ass(subs.group_lines(words, 2), subs.preset_style("classique", {"effect": effect})),
                       encoding="utf-8")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=1080x1920:d=1.5",
                        "-vf", f"ass={ass.name}", "-frames:v", "10", "out.mp4"], cwd=tmp_path, check=True)


# ── Controle qualite ──


def test_quality_score_from_report() -> None:
    stderr = ("black_start:0 black_end:1.2 black_duration:1.2\nfreeze_duration: 3.1\n"
              "silence_duration: 2.0\n  Integrated loudness:\n    I:         -30.5 LUFS\n"
              "  True peak:\n    Peak:  -1.0 dBFS")
    result = quality.score(quality.parse_report(stderr), expect_speech=True, has_subtitles=False)
    assert result["score"] == 4.0 and len(result["issues"]) == 5  # 10 - 3 (noir) - 0,5 - 0,5 - 1 - 1
    assert "dès le début" in result["issues"][0]
    clean = quality.score(quality.parse_report("I: -14.0 LUFS\nPeak: -2.0 dBFS"), expect_speech=True,
                          has_subtitles=True)
    assert clean == {"score": 10.0, "issues": [], "report": clean["report"]}


@needs_ffmpeg
def test_quality_detects_a_black_silent_video(tmp_path: Path) -> None:
    video = tmp_path / "noir.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=black:s=1080x1920:d=6", "-f", "lavfi", "-i", "anullsrc", "-t", "6",
           "-c:v", "libx264", "-c:a", "aac", str(video))
    result = quality.analyse(settings_for(tmp_path), video, expect_speech=True, has_subtitles=True)
    assert result["score"] <= 6 and any("noir" in i for i in result["issues"])


# ── Parcours complet : voix, musique, logo ──


@needs_ffmpeg
def test_render_with_voice_music_and_logo(session: Session, tmp_path: Path, media: dict[str, bytes]) -> None:
    service, _, settings, project_id = build(session, tmp_path, media)
    song = tmp_path / "chanson.mp3"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=3", str(song))
    with pytest.raises(music.MusicError, match="droit"):
        music.add_track(session, settings, filename="c.mp3", content=song.read_bytes(), title="x", license="CC0",
                        rights_confirmed=False)
    track = music.add_track(session, settings, filename="chanson.mp3", content=song.read_bytes(), title="Douce",
                            license="CC0", rights_confirmed=True, volume=0.2)
    music.set_default(session, track.id)
    logo = tmp_path / "logo.png"
    ffmpeg("-f", "lavfi", "-i", "color=red:s=200x200", "-frames:v", "1", str(logo))
    set_value(session, "brand", {"logo_path": str(logo), "subtitle_preset": "karaoke"})
    run_to_render(service, session, project_id)

    music_step = service.get_step(project_id, StepName.SELECT_MUSIC).output or {}
    assert music_step["music"] == "Douce" and music_step["license"] == "CC0"
    out = service.get_step(project_id, StepName.RENDER_VIDEO).output or {}
    assert (out["width"], out["height"], out["audio_codec"]) == (1080, 1920, "aac")
    assert out["quality"]["score"] >= 7, out["quality"]
    ass = (tmp_path / "projects" / project_id / "render" / "sous-titres.ass").read_text(encoding="utf-8")
    assert "\\kf" in ass  # style de la marque applique
    # Les scenes ont ete allongees pour laisser la voix finir (8 mots x 0,3 s + respiration)
    scenes = (service.get_step(project_id, StepName.GENERATE_VOICE).output or {})
    assert scenes["word_timing"] == "calculé"


@needs_ffmpeg
def test_paid_voice_requires_confirmation(session: Session, tmp_path: Path, media: dict[str, bytes]) -> None:
    service, runtime, _, project_id = build(session, tmp_path, media)

    class PaidVoice:
        id, name, local = "elevenlabs", "ElevenLabs (payant)", False

        def status(self) -> Any:
            return tts.EngineStatus(self.id, self.name, False, True)

        def estimate_cost(self, text: str) -> float:
            return 0.12

        def synthesize(self, text: str, dest: Path, **_: Any) -> Path:
            ffmpeg("-f", "lavfi", "-i", "sine=duration=1", "-ar", "48000", "-ac", "2", str(dest))
            return dest

    runtime.tts_override = PaidVoice()
    with contextlib.suppress(AssertionError):  # le parcours s'arrete sur la confirmation de la voix
        run_to_render(service, session, project_id)
    step = service.get_step(project_id, StepName.GENERATE_VOICE)
    assert step.status == "needs_validation" and "Coût estimé : 0,12 dollar" in (step.output or {})["message"]
    service.approve(project_id, StepName.GENERATE_VOICE, actor="utilisateur", confirmed=True)
    assert service.advance(project_id).status == "done"
    costs = growth_costs(session)
    assert costs == [0.12]


def growth_costs(session: Session) -> list[float]:
    from shortforge.models import Cost

    return [c.amount_usd for c in session.scalars(select(Cost).where(Cost.kind == "actual",
                                                                     Cost.description.like("Voix off%")))]


# ── Concurrents, formats gagnants, style, resultats ──


class FakeYouTubeData:
    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/channels"):
            return httpx.Response(200, json={"items": [{"id": "UCabc", "snippet": {"title": "Chaîne rivale"},
                                                        "contentDetails": {"relatedPlaylists": {"uploads": "UUabc"}}}]})
        if path.endswith("/playlistItems"):
            return httpx.Response(200, json={"items": [{"contentDetails": {"videoId": v}} for v in "abcde"]})
        if path.endswith("/videos"):
            views = {"a": 1000, "b": 1200, "c": 900, "d": 5000, "e": 1100}
            return httpx.Response(200, json={"items": [
                {"id": v, "snippet": {"title": f"Short {v}", "description": "", "publishedAt": "2026-11-01T10:00:00Z"},
                 "statistics": {"viewCount": str(n)}, "contentDetails": {"duration": "PT45S" if v != "c" else "PT12M"}}
                for v, n in views.items()]})
        return httpx.Response(404)


def test_competitor_outliers_and_original_idea(session: Session, tmp_path: Path) -> None:
    from shortforge.integrations.youtube_data import YouTubeData

    data = YouTubeData("cle", transport=httpx.MockTransport(FakeYouTubeData().handler))
    competitor = growth.add_competitor(session, data, "youtube", "@rival")
    stats = growth.refresh_competitor(session, data, competitor)
    assert competitor.title == "Chaîne rivale" and stats["videos"] == 4  # la video de 12 min est ignoree
    outlier = session.scalars(select(CompetitorVideo).where(CompetitorVideo.outlier.is_(True))).one()
    assert outlier.external_id == "d" and outlier.ratio >= 2

    tiktok = growth.add_competitor(session, None, "tiktok", "@danse")
    with pytest.raises(growth.GrowthError, match="TikTok"):
        growth.refresh_competitor(session, data, tiktok)
    growth.add_manual_video(session, tiktok, title="Petit", views=100)
    growth.add_manual_video(session, tiktok, title="Gros", views=900)
    assert tiktok.median_views == 500

    recipe = {"hook_type": "question choc", "structure": ["question", "trois indices", "révélation"],
              "pacing": "rapide", "ending": "retournement", "why_it_works": "suspense", "duration_s": 30}
    llm = FakeLLM(recipe, {"title": "Short d", "hook": ""},
                  {"title": "Le mystère du frigo bavard", "hook": "Ton frigo parle-t-il la nuit ?",
                   "original_angle": "enquête domestique", "estimated_duration_s": 30, "potential_score": 70})
    project = PipelineService(session, settings_for(tmp_path), build_handlers(
        make_runtime(settings_for(tmp_path), llm))).create_project("x", niche="humour")
    assert growth.extract_recipe(session, llm, outlier)["structure"][1] == "trois indices"
    assert "ne recopie aucune phrase" in llm.prompts[0].lower() or "Format JSON" in llm.prompts[0]
    with pytest.raises(growth.GrowthError, match="ressemble trop"):
        growth.idea_from_format(session, llm, project, outlier)
    idea = growth.idea_from_format(session, llm, project, outlier)
    assert idea.title == "Le mystère du frigo bavard" and idea.reuse_risk == "low"
    for _ in range(3):
        growth.add_competitor(session, None, "tiktok", "@autre")
    with pytest.raises(growth.GrowthError, match="5 comptes"):
        growth.add_competitor(session, None, "tiktok", "@trop")


def test_style_is_learned_and_used_in_scripts(session: Session, tmp_path: Path) -> None:
    llm = FakeLLM({"tone": "complice", "summary": "Phrases courtes, tutoiement, chute ironique.",
                   "expressions": ["franchement"], "avoid": "le jargon"}, script_response())
    with pytest.raises(growth.GrowthError, match="2 textes"):
        growth.learn_style(session, llm, ["trop court"], "test")
    profile = growth.learn_style(session, llm, ["Franchement, ce chat est un génie du mal.",
                                                "Tu ne vas pas croire ce que fait ma voisine le matin."], "test")
    assert profile["enabled"] and "tutoiement" in growth.style_hint(session)
    from shortforge.models import Idea
    from shortforge.services.scripts import write_script

    project = Project(title="Chat", niche="animaux")
    session.add(project)
    session.flush()
    idea = Idea(project_id=project.id, title="Le chat génie", hook="h")
    session.add(idea)
    session.flush()
    write_script(session, llm, project, idea)
    assert "Phrases courtes, tutoiement" in llm.prompts[-1]


def test_insights_need_three_results(session: Session) -> None:
    projects = []
    for title in ("A", "B", "C"):
        p = Project(title=title)
        session.add(p)
        session.flush()
        projects.append(p)
    growth.add_manual_stats(session, projects[0].id, "tiktok", views=5000, likes=300)
    growth.add_manual_stats(session, projects[1].id, "tiktok", views=200)
    with pytest.raises(growth.GrowthError, match="au moins 3"):
        growth.compute_insights(session, FakeLLM())
    growth.add_manual_stats(session, projects[2].id, "youtube", views=900)
    llm = FakeLLM({"summary": "Les questions marchent.", "what_works": ["question"], "avoid": ["intro longue"],
                   "next_week": ["série de questions"]})
    insights = growth.compute_insights(session, llm)
    assert insights["based_on"] == 3 and "« A » (tiktok) : 5000 vues" in llm.prompts[0]
    from shortforge.services.ideas import _growth_hints

    assert "Les questions marchent." in _growth_hints(session)
    assert session.scalars(select(Analytics)).all()[0].source == "manuel"


# ── Planning de la semaine, validations, pilote automatique ──


def test_week_planning_creates_projects_ready_for_script(session: Session, tmp_path: Path) -> None:
    llm = FakeLLM(ideas_response("Idée lundi", "Recette mardi", "Astuce mercredi"), script_response(),
                  script_response())
    settings = settings_for(tmp_path)
    runtime = make_runtime(settings, llm)
    service = PipelineService(session, settings, build_handlers(runtime))
    pool = planning.create_pool(service, niche="cuisine", language="fr", video_mode="economique")
    from shortforge.services.ideas import generate_ideas

    ideas = generate_ideas(session, llm, pool, trend_sources=[]).ideas
    set_value(session, "schedule_slots", {"days": [0, 2, 4], "youtube": "18:00"})
    dates = planning.next_dates(session, 3, start=datetime(2026, 11, 16, 9))  # lundi
    assert [planning.to_local(d).strftime("%a %H:%M") for d in dates] == ["Wed 18:00", "Fri 18:00", "Mon 18:00"]
    projects = planning.create_week(session, service, pool, [ideas[0].id, ideas[1].id], actor="utilisateur")
    assert len(projects) == 2 and all(p.planned_for for p in projects)
    for project in projects:
        assert service.next_step(project.id).name == "write_script"  # type: ignore[union-attr]
        assert service.get_step(project.id, StepName.SELECT_IDEA).validated_by == "utilisateur"
    with pytest.raises(PipelineError, match="personne"):
        planning.create_week(session, service, pool, [ideas[2].id], actor="agent")
    assert pool.id not in [p.id for p in service.list_projects()]
    service.advance(projects[0].id)
    service.advance(projects[0].id)
    inbox = planning.pending_validations(session)
    assert [(i["project_title"], i["kind"]) for i in inbox] == [("Idée lundi", "script")]


def test_autopilot_stops_at_human_validation(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    llm = FakeLLM(ideas_response("Le chat", "Le chien"), script_response())
    with TestClient(create_app(settings, runtime=make_runtime(settings, llm))) as api:
        pool = api.post("/api/planning/pool", json={"niche": "animaux", "count": 1}).json()
        assert len(pool["ideas"]) == 2 and len(pool["dates"]) == 1
        week = api.post("/api/planning/week", json={"pool_id": pool["pool_id"], "idea_ids": [pool["ideas"][0]["id"]]})
        project_id = week.json()["projects"][0]["id"]
        for _ in range(100):
            steps = {s["name"]: s["status"] for s in api.get(f"/api/projects/{project_id}").json()["steps"]}
            if steps["approve_script"] == "needs_validation":
                break
            time.sleep(0.05)
        assert steps["write_script"] == "done" and steps["approve_script"] == "needs_validation"
        assert api.get("/api/validations").json()[0]["kind"] == "script"
        assert [p["id"] for p in api.get("/api/projects").json()] == [project_id]


# ── Video longue → Shorts ──


@needs_ffmpeg
def test_long_video_to_shorts(session: Session, tmp_path: Path) -> None:
    video = tmp_path / "longue.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=25", "-f", "lavfi", "-i", "sine=duration=40",
           "-t", "40", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", str(video))
    settings = settings_for(tmp_path)
    with pytest.raises(clips.ClipError, match="droit"):
        clips.register_source(session, settings, tmp_path / "x.mp4", title="x", rights_confirmed=False)
    source = clips.register_source(session, settings, video, title="Ma conférence", rights_confirmed=True)
    assert source.duration_s == pytest.approx(40, abs=0.2)

    words = [{"word": w, "start": 5 + i * 0.5, "end": 5.4 + i * 0.5} for i, w in enumerate(
        ["Voici", "le", "secret", "que", "personne", "ne", "connaît", "sur", "les", "fours"])]
    transcript = [{"start": 0.0, "end": 5.0, "text": "Bonjour.", "words": []},
                  {"start": 5.0, "end": 25.0, "text": "Voici le secret que personne ne connaît sur les fours.",
                   "words": words},
                  {"start": 25.0, "end": 40.0, "text": "Merci.", "words": []}]
    clips.transcribe_source(session, FakeTranscriber(transcript, available=True), source)
    llm = FakeLLM({"clips": [{"start": 4.6, "end": 25.3, "title": "Le secret des fours", "hook": "Voici le secret"},
                             {"start": 0, "end": 3, "title": "Trop court"}]})
    proposals = clips.propose_clips(session, llm, source)
    assert proposals == [{"start": 5.0, "end": 25.0, "title": "Le secret des fours", "hook": "Voici le secret",
                          "why": ""}]

    runtime = make_runtime(settings, FakeLLM())
    service = PipelineService(session, settings, build_handlers(runtime))
    project = clips.create_clip_projects(session, service, source, [0], actor="utilisateur")[0]
    assert project.source == "clip" and service.next_step(project.id).name == "create_subtitles"  # type: ignore
    for _ in range(2):  # sous-titres puis montage (voix et musique : son d'origine)
        step = service.advance(project.id)
        assert step.status == "done", (step.name, step.error)
    assert (service.get_step(project.id, StepName.CREATE_SUBTITLES).output or {})["segments"] >= 3
    out = service.get_step(project.id, StepName.RENDER_VIDEO).output or {}
    assert (out["width"], out["height"]) == (1080, 1920) and out["duration_s"] == pytest.approx(20, abs=0.2)
    assert service.advance(project.id).name == "review_preview"


# ── Publications multi-plateformes ──


class FakePostiz:
    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "cle-postiz"
        if request.url.path.endswith("/integrations"):
            return httpx.Response(200, json=[{"id": "tt1", "name": "Mon TikTok", "providerIdentifier": "tiktok"},
                                             {"id": "ig1", "name": "Mon Insta", "providerIdentifier": "instagram"}])
        if request.url.path.endswith("/upload"):
            return httpx.Response(200, json={"id": "m1", "path": "https://postiz.test/m1.mp4"})
        if request.url.path.endswith("/posts"):
            self.posts.append(json.loads(request.content))
            return httpx.Response(200, json=[{"postId": f"p{len(self.posts)}"}])
        return httpx.Response(404)


def test_publish_guard_accepts_either_channel(tmp_path: Path) -> None:
    social_only = settings_for(tmp_path, social_publish_enabled=True)
    assert check_publish(social_only, final_render_validated_by="utilisateur", confirmed=True,
                         actor="utilisateur").allowed
    blocked = check_publish(settings_for(tmp_path), final_render_validated_by="utilisateur", confirmed=True,
                            actor="utilisateur")
    assert "SOCIAL_PUBLISH_ENABLED=false" in blocked.reasons[0]


@needs_ffmpeg
def test_multi_platform_scheduled_publication(session: Session, tmp_path: Path, media: dict[str, bytes]) -> None:
    yt, postiz = FakeYouTube(), FakePostiz()
    service, runtime, settings, project_id = build(session, tmp_path, media, publish=True, yt=yt)
    settings.social_publish_enabled = True
    settings.postiz_api_key = SecretStr("cle-postiz")
    runtime.http_transport = httpx.MockTransport(postiz.handler)
    project = session.get(Project, project_id)
    assert project is not None
    project.planned_for = datetime.now() + timedelta(days=2)
    run_to_render(service, session, project_id)
    approve_until_draft(service, project_id)
    connect_channel(session, settings)
    posts = {p.platform: p for p in social.ensure_posts(session, settings, project)}
    assert {k: p.method for k, p in posts.items()} == {"youtube": "youtube_api", "tiktok": "postiz",
                                                       "instagram": "postiz"}
    assert all(p.scheduled_at and p.scheduled_at > utcnow() for p in posts.values())
    assert settings.ai_disclosure_text in posts["tiktok"].caption and "#fyp" in posts["tiktok"].caption
    social.update_post(session, posts["instagram"], {"enabled": False})

    service.advance(project_id)
    service.approve(project_id, StepName.PUBLISH, actor="utilisateur", confirmed=True)
    assert yt.metadata is not None and yt.metadata["status"]["privacyStatus"] == "private"
    assert yt.metadata["status"]["publishAt"].endswith("Z")
    assert len(postiz.posts) == 1 and postiz.posts[0]["type"] == "schedule"
    sent = postiz.posts[0]["posts"][0]
    assert sent["integration"] == {"id": "tt1"} and sent["settings"]["isAIGenerated"] is True
    statuses = {p.platform: p.status for p in session.scalars(select(SocialPost))}
    assert statuses == {"youtube": "scheduled", "tiktok": "scheduled", "instagram": "draft"}


@needs_ffmpeg
def test_manual_export_without_automatic_publication(session: Session, tmp_path: Path,
                                                     media: dict[str, bytes]) -> None:
    service, _, settings, project_id = build(session, tmp_path, media)
    run_to_render(service, session, project_id)
    project = session.get(Project, project_id)
    assert project is not None
    with pytest.raises(PipelineError, match="rendu final"):
        from shortforge.services.render import latest_render

        if latest_render(session, project_id).approved_at is None:  # type: ignore[union-attr]
            raise PipelineError("Valide d'abord le rendu final.")
    approve_until_draft(service, project_id)
    posts = social.ensure_posts(session, settings, project)
    assert {p.method for p in posts} == {"manual"}
    assert youtube.final_checks(session, settings, project)[1].id == "targets"
    social.mark_exported(session, posts[1])
    social.mark_published(session, posts[1], "https://www.tiktok.com/@moi/video/1")
    service.finish_without_publishing(project, actor="utilisateur")
    assert project.status == "done" and service.get_step(project_id, StepName.PUBLISH).output["manual"]  # type: ignore


def test_postiz_client_errors(tmp_path: Path) -> None:
    from shortforge.integrations.postiz import PostizError

    with pytest.raises(PostizError, match="POSTIZ_API_KEY"):
        PostizClient("https://postiz.test", None).integrations()
    bad = PostizClient("https://postiz.test", "k", transport=httpx.MockTransport(lambda _: httpx.Response(401)))
    with pytest.raises(PostizError, match="refuse"):
        bad.integrations()


# ── API ──


def test_studio_endpoints(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings, runtime=make_runtime(settings, FakeLLM()))) as api:
        state = api.get("/api/voice").json()
        assert {e["id"] for e in state["engines"]} == {"piper", "system", "elevenlabs"}
        assert api.put("/api/voice", json={"engine": "system", "speed": 1.1}).json()["settings"]["speed"] == 1.1
        presets = api.get("/api/subtitle-presets").json()
        assert len(presets["presets"]) == 20
        brand = api.put("/api/brand", json={"subtitle_preset": "neon", "logo_position": "bas_gauche"}).json()
        assert brand["subtitle_preset"] == "neon" and brand["has_logo"] is False
        assert api.put("/api/brand", json={"subtitle_preset": "inconnu"}).status_code == 502
        refused = api.put("/api/music/upload?filename=a.mp3&license=CC0", content=b"xx")
        assert refused.status_code == 502 and "droit" in refused.json()["detail"]
        slots = api.put("/api/planning/slots", json={"instagram": "08:30", "per_day": 3}).json()
        assert slots["instagram"] == "08:30" and slots["per_day"] == 3
        assert api.put("/api/planning/slots", json={"tiktok": "midi"}).status_code == 422
        tiktok = api.post("/api/competitors", json={"platform": "tiktok", "handle": "@danse"}).json()
        manual = api.post(f"/api/competitors/{tiktok['id']}/videos", json={"title": "Danse", "views": 10}).json()
        assert manual["videos"][0]["source"] == "manuel"
        onboarding = api.get("/api/onboarding").json()
        assert {s["id"] for s in onboarding["steps"]} == {"ffmpeg", "ollama", "comfyui", "voice", "whisper"}
        assert api.post("/api/onboarding/done").json() == {"done": True}
        source = api.put("/api/sources/upload?filename=v.mp4&rights_confirmed=false", content=b"x")
        assert source.status_code == 502 and "droit" in source.json()["detail"]
        assert api.get("/api/validations").json() == []
        assert api.get("/api/performance").json()["rows"] == []


def test_script_revision_in_plain_language(session: Session) -> None:
    from shortforge.services.scripts import revise_script, write_script

    llm = FakeLLM(script_response(), script_response())
    project = Project(title="Chat")
    session.add(project)
    session.flush()
    from shortforge.models import Idea

    idea = Idea(project_id=project.id, title="Le chat", hook="h")
    session.add(idea)
    session.flush()
    first = write_script(session, llm, project, idea).script
    second = revise_script(session, llm, project, first, "rends le hook plus drôle").script
    assert second.version == 2 and "rends le hook plus drôle" in llm.prompts[-1]
    assert '"hook": "Tu ne devineras jamais' in llm.prompts[-1]


def test_voice_step_skips_when_disabled(session: Session, tmp_path: Path) -> None:
    set_value(session, "voice", {"enabled": False})
    assert voice.voice_settings(session)["enabled"] is False
    assert session.scalars(select(MusicTrack)).all() == []
    assert session.scalars(select(Competitor)).all() == []
