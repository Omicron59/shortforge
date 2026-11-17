"""Ecriture, modification et raccourcissement des scripts, avec leur decoupage en scenes."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from shortforge.integrations.ollama import LLMClient, LLMError
from shortforge.models import Idea, Project, Scene, Script
from shortforge.services.safety import content_issues

WORDS_PER_SECOND = 2.5  # debit moyen d'une voix off naturelle
HOOK_MIN_S, HOOK_MAX_S = 2.0, 5.0
TRANSITIONS = ("cut", "fondu", "zoom", "glissement", "flash")
IMPORTANCES = ("simple", "transition", "important", "exceptional")
DEFAULT_NEGATIVE = "flou, basse qualité, texte illisible, filigrane, mains déformées, visage déformé"

SYSTEM_PROMPT = """Tu écris des scripts de YouTube Shorts verticaux, rythmés et originaux.
Structure : hook de 2 à 5 secondes, corps, conclusion, appel à l'action.
Découpe en scènes courtes ; pour chaque scène, un prompt visuel précis en anglais (pour un
générateur d'images ou de vidéos, format vertical 9:16) et un prompt négatif.
Interdits : violence, sexe, haine, contenu illégal ou trompeur, personnes réelles,
conseils médicaux, juridiques ou financiers personnalisés. Réponds uniquement en JSON."""

PROMPT_TEMPLATE = """Idée : {title}
Hook proposé : {hook}
Angle original : {angle}
Style visuel : {style}
Langue du texte dit : {language}
Durée visée : {duration} secondes au total.
{extra}
Format JSON exact :
{{"hook": "...", "body": "...", "conclusion": "...", "call_to_action": "...",
"scenes": [{{"text": "texte dit pendant la scène", "on_screen_text": "quelques mots affichés à l'écran, ou vide",
"visual_intent": "en une phrase, ce que l'image doit montrer", "visual_prompt": "...", "negative_prompt": "...",
"transition": "{transitions}", "duration_s": 3, "importance": "{importances}"}}]}}"""


class SceneDraft(BaseModel):
    text: str = ""
    on_screen_text: str = Field(default="", max_length=200)
    visual_intent: str = Field(default="", max_length=500)
    visual_prompt: str = Field(min_length=3)
    negative_prompt: str = ""
    transition: str = "cut"
    duration_s: float = 3
    importance: str = "simple"

    @field_validator("transition", mode="before")
    @classmethod
    def _transition(cls, value: Any) -> str:
        value = str(value or "").strip().lower()
        return value if value in TRANSITIONS else "cut"

    @field_validator("importance", mode="before")
    @classmethod
    def _importance(cls, value: Any) -> str:
        value = str(value or "").strip().lower()
        return value if value in IMPORTANCES else "simple"

    @field_validator("duration_s", mode="before")
    @classmethod
    def _duration(cls, value: Any) -> float:
        try:
            return max(1.0, min(15.0, float(value)))
        except (TypeError, ValueError):
            return 3.0


class ScriptDraft(BaseModel):
    hook: str = Field(min_length=1)
    body: str = ""
    conclusion: str = ""
    call_to_action: str = ""
    scenes: list[SceneDraft] = Field(min_length=1, max_length=30)


@dataclass(slots=True)
class ScriptResult:
    script: Script
    scenes: list[Scene]
    warnings: list[str] = field(default_factory=list)


def spoken_duration(text: str) -> float:
    """Duree estimee d'un texte lu a voix haute, en secondes."""
    return round(len(text.split()) / WORDS_PER_SECOND, 1)


def script_text(script: Script) -> str:
    return " ".join(p for p in (script.hook, script.body, script.conclusion, script.call_to_action) if p)


def check_script(script: Script) -> list[str]:
    """Avertissements non bloquants sur un script (duree du hook, longueur totale)."""
    warnings = []
    hook_s = spoken_duration(script.hook)
    if hook_s > HOOK_MAX_S:
        warnings.append(f"Le hook dure environ {hook_s:g} s : vise {HOOK_MAX_S:g} s au maximum.")
    elif hook_s < HOOK_MIN_S:
        warnings.append(f"Le hook dure environ {hook_s:g} s : vise au moins {HOOK_MIN_S:g} s.")
    if script.estimated_duration_s > 60:
        warnings.append("Le script dépasse 60 secondes : pense à le raccourcir.")
    return warnings


def current_script(session: Session, project_id: str) -> Script | None:
    return session.scalars(
        select(Script).where(Script.project_id == project_id).order_by(Script.version.desc())
    ).first()


def scenes_of(session: Session, script_id: str) -> list[Scene]:
    return list(session.scalars(select(Scene).where(Scene.script_id == script_id).order_by(Scene.position)))


def write_script(session: Session, llm: LLMClient, project: Project, idea: Idea, *,
                 target_duration_s: float | None = None, instructions: str = "") -> ScriptResult:
    """Ecrit une nouvelle version du script a partir de l'idee choisie."""
    duration = target_duration_s or idea.estimated_duration_s or 30
    prompt = PROMPT_TEMPLATE.format(
        title=idea.title, hook=idea.hook, angle=idea.original_angle, style=idea.visual_style or "au choix",
        language=project.language, duration=round(duration), extra=_with_style(session, instructions),
        transitions="|".join(TRANSITIONS), importances="|".join(IMPORTANCES),
    )
    draft = _ask(llm, prompt)
    return _save(session, project, draft, idea_id=idea.id)


def revise_script(session: Session, llm: LLMClient, project: Project, script: Script, instruction: str) -> ScriptResult:
    """Correction en langage naturel (« rends le hook plus drôle ») : nouvelle version du script."""
    if script.status == "approved":
        raise ValueError("Ce script est validé : refais l'étape de validation pour le modifier.")
    if not instruction.strip():
        raise ValueError("Dis ce qu'il faut changer.")
    scenes = scenes_of(session, script.id)
    current = {"hook": script.hook, "body": script.body, "conclusion": script.conclusion,
               "call_to_action": script.call_to_action,
               "scenes": [{"text": s.text, "on_screen_text": s.on_screen_text, "visual_intent": s.visual_intent,
                           "visual_prompt": s.visual_prompt, "negative_prompt": s.negative_prompt,
                           "transition": s.transition, "duration_s": s.duration_s, "importance": s.importance}
                          for s in scenes]}
    prompt = (f"Voici le script actuel (JSON) :\n{json.dumps(current, ensure_ascii=False)}\n\n"
              f"Demande de correction : {instruction.strip()}\n"
              "Applique seulement cette demande, garde le reste tel quel, et renvoie le script complet "
              f"dans le même format JSON.\n{_with_style(session, '')}")
    return _save(session, project, _ask(llm, prompt), idea_id=script.idea_id)


def _with_style(session: Session, instructions: str) -> str:
    from shortforge.services.growth import style_hint

    return "\n".join(p for p in (instructions, style_hint(session)) if p)


def shorten_script(session: Session, llm: LLMClient, project: Project, script: Script,
                   target_duration_s: float) -> ScriptResult:
    """Nouvelle version plus courte du script, en gardant le meme hook si possible."""
    idea = session.get(Idea, script.idea_id) if script.idea_id else None
    instructions = (f"Raccourcis ce script à {round(target_duration_s)} secondes maximum, garde l'idée et le "
                    f"hook si possible :\n{script_text(script)}")
    prompt = PROMPT_TEMPLATE.format(
        title=idea.title if idea else project.title, hook=script.hook, angle=idea.original_angle if idea else "",
        style=idea.visual_style if idea else "au choix", language=project.language,
        duration=round(target_duration_s), extra=instructions,
        transitions="|".join(TRANSITIONS), importances="|".join(IMPORTANCES),
    )
    return _save(session, project, _ask(llm, prompt), idea_id=script.idea_id)


def update_script(session: Session, script: Script, fields: dict[str, Any],
                  scenes: list[dict[str, Any]] | None = None) -> ScriptResult:
    """Modification manuelle du script (et, si fourni, de ses scenes)."""
    if script.status == "approved":
        raise ValueError("Ce script est validé : refais l'étape de validation pour le modifier.")
    for key in ("hook", "body", "conclusion", "call_to_action"):
        if key in fields and fields[key] is not None:
            setattr(script, key, str(fields[key]))
    new_scenes = None
    if scenes is not None:
        try:
            new_scenes = [SceneDraft.model_validate(s) for s in scenes]
        except ValidationError as exc:
            raise ValueError("Scènes invalides : chaque scène doit avoir un prompt visuel.") from exc
    _check_safety(script_text(script) + " " + " ".join(s.text + " " + s.visual_prompt for s in new_scenes or []))
    if new_scenes is not None:
        session.execute(delete(Scene).where(Scene.script_id == script.id))
        _add_scenes(session, script, new_scenes)
    script.estimated_duration_s = spoken_duration(script_text(script))
    session.flush()
    return ScriptResult(script, scenes_of(session, script.id), check_script(script))


def _ask(llm: LLMClient, prompt: str) -> ScriptDraft:
    raw = llm.generate_json(SYSTEM_PROMPT, prompt)
    try:
        return ScriptDraft.model_validate(raw)
    except ValidationError as exc:
        raise LLMError("Le modèle a renvoyé un script incomplet (hook ou scènes manquants).") from exc


def _check_safety(text: str) -> None:
    if issues := content_issues(text):
        raise LLMError("Script refusé : " + ", ".join(issues) + ".")


def _save(session: Session, project: Project, draft: ScriptDraft, *, idea_id: str | None) -> ScriptResult:
    _check_safety(" ".join([draft.hook, draft.body, draft.conclusion, draft.call_to_action,
                            *(s.text + " " + s.visual_prompt for s in draft.scenes)]))
    version = (session.scalar(select(func.max(Script.version)).where(Script.project_id == project.id)) or 0) + 1
    script = Script(project_id=project.id, idea_id=idea_id, version=version, hook=draft.hook, body=draft.body,
                    conclusion=draft.conclusion, call_to_action=draft.call_to_action)
    script.estimated_duration_s = spoken_duration(script_text(script))
    session.add(script)
    session.flush()
    scenes = _add_scenes(session, script, draft.scenes)
    return ScriptResult(script, scenes, check_script(script))


def _add_scenes(session: Session, script: Script, drafts: list[SceneDraft]) -> list[Scene]:
    scenes = [
        Scene(project_id=script.project_id, script_id=script.id, position=i, text=d.text,
              on_screen_text=d.on_screen_text, visual_intent=d.visual_intent,
              visual_prompt=d.visual_prompt, negative_prompt=d.negative_prompt or DEFAULT_NEGATIVE,
              transition=d.transition, duration_s=d.duration_s, importance=d.importance)
        for i, d in enumerate(drafts)
    ]
    session.add_all(scenes)
    session.flush()
    return scenes
