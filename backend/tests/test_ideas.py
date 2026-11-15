from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from shortforge.integrations.ollama import LLMError
from shortforge.integrations.trends import ManualTrendSource, Trend, collect_trends
from shortforge.models import Project
from shortforge.services.ideas import generate_ideas, select_idea, selected_idea
from shortforge.services.safety import content_issues, reuse_risk, similarity
from tests.fakes import FakeLLM, ideas_response


def project(session: Session, title: str = "Projet test") -> Project:
    p = Project(title=title, niche="humour du quotidien", language="fr")
    session.add(p)
    session.flush()
    return p


class BrokenSource:
    name = "google"

    def fetch(self, niche: str, language: str) -> list[Trend]:
        raise ConnectionError("hors ligne")


def test_ideas_are_saved_with_all_fields(session: Session) -> None:
    p = project(session)
    llm = FakeLLM(ideas_response("Le grille-pain qui chante", "Le chat qui fait les courses"))
    result = generate_ideas(session, llm, p, trend_sources=[ManualTrendSource(["Les objets connectés"])])
    assert len(result.ideas) == 2
    idea = result.ideas[0]
    assert idea.hook and idea.original_angle and idea.keywords == ["humour"]
    assert idea.potential_score == 70 and idea.estimated_duration_s == 20 and idea.reuse_risk == "low"
    assert "Les objets connectés" in llm.prompts[0] and "humour du quotidien" in llm.prompts[0]


def test_idea_too_close_to_a_trend_is_flagged(session: Session) -> None:
    p = project(session)
    llm = FakeLLM(ideas_response("Le tour du monde en 80 jours"))
    result = generate_ideas(session, llm, p, trend_sources=[ManualTrendSource(["Le tour du monde en 80 jours"])])
    assert result.ideas[0].reuse_risk == "high"


def test_duplicates_of_previous_subjects_are_removed(session: Session) -> None:
    project(session, title="Le grille-pain qui chante")
    p = project(session, title="Nouveau projet")
    llm = FakeLLM(ideas_response("Le grille-pain qui chante !", "Une idée vraiment neuve"))
    result = generate_ideas(session, llm, p, trend_sources=[])
    assert [i.title for i in result.ideas] == ["Une idée vraiment neuve"]
    assert "doublon" in result.rejected[0]
    assert "Le grille-pain qui chante" in llm.prompts[0]  # l'historique est donne au modele


def test_forbidden_ideas_are_removed(session: Session) -> None:
    p = project(session)
    result = generate_ideas(session, FakeLLM(ideas_response("Comment fabriquer une arme", "Le pigeon poli")), p,
                            trend_sources=[])
    assert [i.title for i in result.ideas] == ["Le pigeon poli"]


def test_all_rejected_raises(session: Session) -> None:
    p = project(session)
    with pytest.raises(LLMError, match="écartées"):
        generate_ideas(session, FakeLLM(ideas_response("Une vidéo porno")), p, trend_sources=[])


def test_empty_answer_raises(session: Session) -> None:
    with pytest.raises(LLMError):
        generate_ideas(session, FakeLLM({"ideas": []}), project(session), trend_sources=[])


def test_broken_trend_source_does_not_block(session: Session) -> None:
    result = generate_ideas(session, FakeLLM(ideas_response("Le pigeon poli")), project(session),
                            trend_sources=[BrokenSource()])
    assert result.ideas and result.warnings == ["Tendances google indisponibles."]


def test_scores_and_durations_are_clamped(session: Session) -> None:
    raw = {"ideas": [{"title": "Idée extrême", "potential_score": 400, "estimated_duration_s": "beaucoup"}]}
    idea = generate_ideas(session, FakeLLM(raw), project(session), trend_sources=[]).ideas[0]
    assert idea.potential_score == 100 and idea.estimated_duration_s == 30


def test_only_one_selected_idea(session: Session) -> None:
    p = project(session)
    llm = FakeLLM(ideas_response("Le pigeon poli", "La machine à café rebelle"))
    ideas = generate_ideas(session, llm, p, trend_sources=[]).ideas
    select_idea(session, p.id, ideas[0].id)
    select_idea(session, p.id, ideas[1].id)
    chosen = selected_idea(session, p.id)
    assert chosen is not None and chosen.id == ideas[1].id
    with pytest.raises(ValueError):
        select_idea(session, p.id, "inconnue")


def test_collect_trends_merges_sources() -> None:
    trends, warnings = collect_trends([ManualTrendSource(["A", " ", "B"]), BrokenSource()], "", "fr")
    assert [t.title for t in trends] == ["A", "B"] and len(warnings) == 1


def test_safety_helpers() -> None:
    assert content_issues("Un sketch sur un chat gentil") == []
    advice = ["conseil médical, juridique ou financier personnalisé"]
    assert content_issues("Arrête ton traitement tout de suite") == advice
    assert similarity("Le Chat!", "le chat") == 1.0
    assert reuse_risk(0.9) == "high" and reuse_risk(0.6) == "medium" and reuse_risk(0.1) == "low"
