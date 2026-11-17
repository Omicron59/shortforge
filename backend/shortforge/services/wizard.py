"""Nouveau parcours de creation : brief, idees, script et storyboard editables, versions, duplication.

Regles : rien n'est genere sans demande de l'utilisateur, une regeneration ciblee ne touche qu'un champ,
et toute modification date le contenu pour signaler les medias devenus obsoletes (sans rien relancer).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shortforge.integrations.ollama import LLMClient, LLMError
from shortforge.models import Asset, Brief, Idea, PipelineStep, Project, Scene, Script, utcnow
from shortforge.services import scripts as script_service
from shortforge.services.ideas import DUPLICATE_THRESHOLD, previous_subjects
from shortforge.services.safety import best_match, content_issues

GOALS = {"vues": "Faire des vues", "ventes": "Vendre", "notoriete": "Me faire connaître", "education": "Enseigner",
         "divertissement": "Divertir", "autorite": "Montrer mon expertise"}
TONES = {"educatif": "Éducatif", "storytelling": "Récit", "humour": "Humour", "choc": "Choc",
         "autorite": "Expert", "inspirant": "Inspirant"}
PLATFORMS = {"youtube_shorts": "YouTube Shorts", "tiktok": "TikTok", "instagram_reels": "Instagram Reels"}
DURATIONS = (20, 30, 45, 60)
LANGUAGES = {"fr": "Français", "en": "Anglais", "es": "Espagnol", "de": "Allemand", "it": "Italien",
             "pt": "Portugais"}
DIFFICULTIES = ("facile", "moyenne", "difficile")
FIELDS = {"text": "le texte de la voix off", "on_screen_text": "le texte affiché à l'écran",
          "visual_prompt": "le prompt visuel"}

IDEAS_SYSTEM = """Tu proposes des idées de vidéos courtes verticales, ORIGINALES, adaptées au brief fourni.
Ne recopie aucune vidéo, voix ou montage existant. Interdits : violence, sexe, haine, contenu illégal ou
trompeur, personnes réelles, conseils médicaux, juridiques ou financiers personnalisés.
Réponds uniquement en JSON."""

IDEAS_PROMPT = """Brief :
{brief}

Sujets déjà traités ou déjà proposés (à ne pas refaire) :
{history}
{variant}
Propose {count} idées. Format JSON exact :
{{"ideas": [{{"title": "...", "hook": "phrase des 2 premières secondes", "angle": "ce qui rend l'idée originale",
"summary": "ce que la vidéo raconte, en 2 phrases", "duration_s": {duration},
"difficulty": "facile|moyenne|difficile", "resources": ["ce qu'il faut pour la produire"],
"fit_reason": "pourquoi cette idée répond au brief"}}]}}"""

FIELD_SYSTEM = """Tu réécris UN seul élément d'une scène de vidéo courte verticale, sans toucher au reste.
Interdits : violence, sexe, haine, contenu illégal ou trompeur, personnes réelles. Réponds uniquement en JSON."""


class BriefData(BaseModel):
    subject: str = Field(default="", max_length=2000)
    niche: str = Field(default="", max_length=200)
    audience: str = Field(default="", max_length=300)
    goal: str = "vues"
    language: str = "fr"
    tone: str = "educatif"
    duration_s: int = 30
    platform: str = "youtube_shorts"
    visual_style: str = Field(default="", max_length=300)
    constraints: str = Field(default="", max_length=2000)
    avoid: str = Field(default="", max_length=2000)

    @field_validator("goal")
    @classmethod
    def _goal(cls, value: str) -> str:
        return value if value in GOALS else "vues"

    @field_validator("tone")
    @classmethod
    def _tone(cls, value: str) -> str:
        return value if value in TONES else "educatif"

    @field_validator("platform")
    @classmethod
    def _platform(cls, value: str) -> str:
        return value if value in PLATFORMS else "youtube_shorts"

    @field_validator("language")
    @classmethod
    def _language(cls, value: str) -> str:
        return value if value in LANGUAGES else "fr"

    @field_validator("duration_s")
    @classmethod
    def _duration(cls, value: int) -> int:
        return min(DURATIONS, key=lambda d: abs(d - value))


class WizardIdea(BaseModel):
    """Idee renvoyee par le modele, validee. Aucun score de viralite : il ne serait pas fiable."""

    title: str = Field(min_length=3, max_length=200)
    hook: str = Field(default="", max_length=500)
    angle: str = Field(default="", max_length=1000)
    summary: str = Field(default="", max_length=1000)
    duration_s: float = 30
    difficulty: str = ""
    resources: list[str] = Field(default_factory=list)
    fit_reason: str = Field(default="", max_length=1000)

    @field_validator("difficulty", mode="before")
    @classmethod
    def _difficulty(cls, value: Any) -> str:
        value = str(value or "").strip().lower()
        return value if value in DIFFICULTIES else ""

    @field_validator("duration_s", mode="before")
    @classmethod
    def _clamp(cls, value: Any) -> float:
        try:
            return max(5.0, min(180.0, float(value)))
        except (TypeError, ValueError):
            return 30.0

    @field_validator("resources", mode="before")
    @classmethod
    def _resources(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            value = value.split(",")
        return [str(v).strip()[:200] for v in (value or []) if str(v).strip()][:8]


@dataclass(slots=True)
class IdeasResult:
    ideas: list[Idea]
    rejected: list[str] = field(default_factory=list)


# --- brief ---
def brief_of(session: Session, project: Project) -> Brief:
    """Brief du projet ; pour un projet de l'ancien parcours, il est deduit de sa niche, sa langue et son idee."""
    brief = session.get(Brief, project.id)
    if brief is None:
        brief = Brief(project_id=project.id, niche=project.niche,
                      language=project.language if project.language in LANGUAGES else "fr",
                      duration_s=legacy_duration(session, project) or 30)
        session.add(brief)
        session.flush()
    elif _untouched_legacy(brief, project):  # brief cree par la 0.7.0 avec 30 s par defaut : corrige une fois
        duration = legacy_duration(session, project)
        if duration and duration != brief.duration_s:
            brief.duration_s = duration
            session.flush()
    return brief


def legacy_duration(session: Session, project: Project) -> int | None:
    """Duree visee d'un projet de l'ancien parcours : celle de son idee, sinon celle de son script."""
    idea = session.scalars(select(Idea).where(Idea.project_id == project.id)
                           .order_by(Idea.selected.desc(), Idea.created_at.desc())).first()
    seconds = idea.estimated_duration_s if idea and idea.estimated_duration_s > 0 else 0.0
    if not seconds:
        script = script_service.current_script(session, project.id)
        seconds = script.estimated_duration_s if script else 0.0
    return min(DURATIONS, key=lambda d: abs(d - seconds)) if seconds > 0 else None


def _untouched_legacy(brief: Brief, project: Project) -> bool:
    """Brief jamais rempli dans le nouveau parcours, pour un projet qui n'y a pas ete cree.

    Un projet du nouveau parcours porte le titre tire de son brief ; un ancien projet a son propre titre.
    """
    defaults = BriefData()
    untouched = (not brief.subject and not brief.audience and not brief.constraints and not brief.avoid
                 and not brief.visual_style and brief.goal == defaults.goal and brief.tone == defaults.tone
                 and brief.platform == defaults.platform and brief.duration_s == defaults.duration_s)
    return untouched and project.title != project_title(BriefData(niche=brief.niche))


def save_brief(session: Session, project: Project, data: BriefData) -> Brief:
    brief = brief_of(session, project)
    for name, value in data.model_dump().items():
        setattr(brief, name, value.strip() if isinstance(value, str) else value)
    project.niche, project.language = brief.niche, brief.language
    project.title = project_title(data)
    session.flush()
    return brief


def project_title(data: BriefData) -> str:
    text = (data.subject.strip() or data.niche.strip() or "Nouveau Short").splitlines()[0]
    return text[:77] + "…" if len(text) > 78 else text


def brief_text(brief: Brief) -> str:
    lines = [("Sujet ou idée de départ", brief.subject), ("Niche", brief.niche), ("Public visé", brief.audience),
             ("Objectif", GOALS.get(brief.goal, "")), ("Langue", LANGUAGES.get(brief.language, brief.language)),
             ("Ton", TONES.get(brief.tone, "")), ("Durée visée", f"{brief.duration_s} secondes"),
             ("Plateforme principale", PLATFORMS.get(brief.platform, "")), ("Style visuel", brief.visual_style),
             ("Contraintes", brief.constraints), ("Sujets à éviter absolument", brief.avoid)]
    return "\n".join(f"- {label} : {value}" for label, value in lines if value)


# --- idees ---
def generate_ideas(session: Session, llm: LLMClient, project: Project, brief: Brief, *, count: int = 5,
                   base: Idea | None = None) -> IdeasResult:
    """Ajoute des idees au projet (les precedentes sont conservees). `base` : variantes de cette idee."""
    existing = list(session.scalars(select(Idea).where(Idea.project_id == project.id)))
    history = previous_subjects(session, exclude_project=project.id)[-40:] + [i.title for i in existing]
    variant = ""
    if base is not None:
        variant = (f"\nPars de cette idée et propose des VARIANTES nettement différentes (autre angle, autre hook) :\n"
                   f"Titre : {base.title}\nHook : {base.hook}\nAngle : {base.original_angle}\n")
    prompt = IDEAS_PROMPT.format(brief=brief_text(brief) or "- (brief vide : propose des sujets grand public)",
                                 history=_bullets(history), variant=variant, count=count, duration=brief.duration_s)
    raw = llm.generate_json(IDEAS_SYSTEM, prompt)
    items = raw.get("ideas")
    if not isinstance(items, list) or not items:
        raise LLMError("Le modèle n'a proposé aucune idée exploitable. Réessaie ou change de modèle.")
    batch = max((i.batch for i in existing), default=0) + 1
    result = IdeasResult(ideas=[])
    known = list(history)
    for item in items[:count + 3]:
        try:
            draft = WizardIdea.model_validate(item)
        except ValidationError:
            result.rejected.append("une idée incomplète a été écartée")
            continue
        if issues := content_issues(" ".join([draft.title, draft.hook, draft.angle, draft.summary])):
            result.rejected.append(f"« {draft.title} » : {', '.join(issues)}")
            continue
        score, duplicate = best_match(draft.title, known)
        if score >= DUPLICATE_THRESHOLD:
            result.rejected.append(f"« {draft.title} » : trop proche de « {duplicate} »")
            continue
        idea = Idea(project_id=project.id, title=draft.title, hook=draft.hook, original_angle=draft.angle,
                    summary=draft.summary, estimated_duration_s=draft.duration_s, difficulty=draft.difficulty,
                    resources=draft.resources, fit_reason=draft.fit_reason, visual_style=brief.visual_style,
                    batch=batch, parent_id=base.id if base else None)
        session.add(idea)
        known.append(draft.title)
        result.ideas.append(idea)
        if len(result.ideas) == count:
            break
    session.flush()
    if not result.ideas:
        raise LLMError("Toutes les idées proposées ont été écartées : " + " ; ".join(result.rejected))
    return result


def manual_idea(session: Session, project: Project, brief: Brief) -> Idea:
    """Idee creee a la main a partir du brief (ecriture sans modele)."""
    idea = Idea(project_id=project.id, title=project.title, hook="", original_angle="", summary=brief.subject[:1000],
                estimated_duration_s=brief.duration_s, visual_style=brief.visual_style,
                batch=(session.scalar(select(func.max(Idea.batch)).where(Idea.project_id == project.id)) or 0) + 1)
    session.add(idea)
    session.flush()
    return idea


# --- script et storyboard ---
def script_instructions(brief: Brief) -> str:
    return ("Respecte ce brief :\n" + brief_text(brief) + "\nLe texte dit doit tenir dans la durée visée. "
            "« on_screen_text » : 2 à 6 mots forts, ou vide. Termine par un appel à l'action seulement s'il est utile.")


def generate_script(session: Session, llm: LLMClient, project: Project, brief: Brief, idea: Idea) -> Script:
    result = script_service.write_script(session, llm, project, idea, target_duration_s=brief.duration_s,
                                         instructions=script_instructions(brief))
    touch(project)
    return result.script


def manual_script(session: Session, project: Project, idea: Idea) -> Script:
    """Script vide a remplir a la main : une premiere scene, aucun appel a un modele."""
    script = Script(project_id=project.id, idea_id=idea.id, version=_next_version(session, project.id),
                    hook=idea.hook)
    session.add(script)
    session.flush()
    session.add(Scene(project_id=project.id, script_id=script.id, position=0, text=idea.hook,
                      negative_prompt=script_service.DEFAULT_NEGATIVE))
    session.flush()
    touch(project)
    return script


def transform_script(session: Session, llm: LLMClient, project: Project, brief: Brief, script: Script, kind: str,
                     *, tone: str = "", target_duration_s: float | None = None) -> Script:
    """Nouvelle version du script (l'ancienne reste dans l'historique) : plus court, ou autre ton."""
    if kind == "shorten":
        target = target_duration_s or max(10.0, round(current_duration(session, script) * 0.75))
        instruction = (f"Raccourcis le script à environ {round(target)} secondes de voix off. Garde les scènes "
                       "essentielles et les modifications déjà faites, supprime ou resserre le reste.")
    elif kind == "tone":
        if tone not in TONES:
            raise ValueError("Ton inconnu.")
        brief.tone = tone
        instruction = (f"Réécris les textes dits et les textes à l'écran avec un ton « {TONES[tone]} ». "
                       "Garde le même nombre de scènes, le même ordre et les mêmes prompts visuels.")
    else:
        raise ValueError("Transformation inconnue.")
    result = script_service.revise_script(session, llm, project, script, instruction)
    touch(project)
    return result.script


def hook_variants(session: Session, llm: LLMClient, brief: Brief, script: Script, count: int = 3) -> list[str]:
    """Propose d'autres accroches. Rien n'est applique : l'utilisateur choisit."""
    scenes = script_service.scenes_of(session, script.id)
    current = scenes[0].text if scenes else script.hook
    raw = llm.generate_json(FIELD_SYSTEM, (
        f"Brief :\n{brief_text(brief)}\n\nScript :\n{_outline(scenes)}\n\nAccroche actuelle : {current}\n"
        f"Propose {count} autres accroches (2 à 5 secondes à l'oral), dans la langue du script, chacune avec une "
        'approche différente. Format JSON exact : {"hooks": ["...", "..."]}'))
    hooks = [str(h).strip() for h in (raw.get("hooks") or []) if isinstance(h, str) and h.strip()]
    hooks = [h[:500] for h in hooks if not content_issues(h) and h != current][:count]
    if not hooks:
        raise LLMError("Le modèle n'a pas proposé d'accroche exploitable. Réessaie.")
    return hooks


def regenerate_field(session: Session, llm: LLMClient, project: Project, brief: Brief, scene: Scene,
                     field_name: str) -> Scene:
    """Regenere UN champ d'UNE scene. Les autres champs et les autres scenes ne sont pas modifies."""
    if field_name not in FIELDS:
        raise ValueError("Champ inconnu.")
    scenes = script_service.scenes_of(session, scene.script_id or "")
    rule = {"text": "Même langue que le reste du script, durée à l'oral proche de l'actuelle.",
            "on_screen_text": "2 à 6 mots forts, même langue que le script.",
            "visual_prompt": "En anglais, précis, pour un générateur d'images, format vertical 9:16."}[field_name]
    raw = llm.generate_json(FIELD_SYSTEM, (
        f"Brief :\n{brief_text(brief)}\n\nScript complet :\n{_outline(scenes)}\n\n"
        f"Scène {scene.position + 1} :\n- voix off : {scene.text}\n- texte à l'écran : {scene.on_screen_text}\n"
        f"- intention visuelle : {scene.visual_intent}\n- prompt visuel : {scene.visual_prompt}\n\n"
        f"Réécris uniquement {FIELDS[field_name]} de cette scène. {rule}\n"
        'Format JSON exact : {"value": "..."}'))
    value = raw.get("value")
    if not isinstance(value, str) or not value.strip():
        raise LLMError("Le modèle a renvoyé une réponse vide. Rien n'a été modifié.")
    return patch_scene(session, project, scene, {field_name: value.strip()[:2000]})


def patch_scene(session: Session, project: Project, scene: Scene, changes: dict[str, Any]) -> Scene:
    """Modifie une scene et date ce qui devient obsolete (voix et rendu pour le texte, image pour le visuel)."""
    text_like = [str(v) for k, v in changes.items() if k in ("text", "on_screen_text", "visual_prompt",
                                                              "visual_intent") and v is not None]
    if issues := content_issues(" ".join(text_like)):
        raise ValueError("Modification refusée : " + ", ".join(issues) + ".")
    for name in ("text", "on_screen_text", "visual_intent", "visual_prompt", "negative_prompt", "transition",
                 "duration_s"):
        if name not in changes or changes[name] is None:
            continue
        value = changes[name]
        if name == "transition" and value not in script_service.TRANSITIONS:
            raise ValueError("Transition inconnue.")
        if name == "duration_s":
            value = max(1.0, min(15.0, float(value)))
        if getattr(scene, name) == value:
            continue
        setattr(scene, name, value)
        if name in ("visual_prompt", "negative_prompt"):
            scene.visual_changed_at = utcnow()
        if name in ("text", "on_screen_text", "duration_s", "transition"):
            touch(project)
    session.flush()
    return scene


def add_scene(session: Session, project: Project, script: Script, after: int | None) -> Scene:
    scenes = script_service.scenes_of(session, script.id)
    if len(scenes) >= 30:
        raise ValueError("Un Short ne peut pas dépasser 30 scènes.")
    position = len(scenes) if after is None else max(0, min(len(scenes), after + 1))
    for scene in scenes[position:]:
        scene.position += 1
    new = Scene(project_id=project.id, script_id=script.id, position=position,
                negative_prompt=script_service.DEFAULT_NEGATIVE)
    session.add(new)
    touch(project)
    session.flush()
    return new


def delete_scene(session: Session, project: Project, scene: Scene) -> None:
    scenes = script_service.scenes_of(session, scene.script_id or "")
    if len(scenes) <= 1:
        raise ValueError("Le script doit garder au moins une scène.")
    session.delete(scene)
    for index, other in enumerate(s for s in scenes if s.id != scene.id):
        other.position = index
    touch(project)
    session.flush()


def reorder_scenes(session: Session, project: Project, script: Script, ids: list[str]) -> list[Scene]:
    scenes = {s.id: s for s in script_service.scenes_of(session, script.id)}
    if sorted(ids) != sorted(scenes):
        raise ValueError("L'ordre envoyé ne correspond pas aux scènes du script.")
    if [scenes[i].position for i in ids] != list(range(len(ids))):
        for index, scene_id in enumerate(ids):
            scenes[scene_id].position = index
        touch(project)
    session.flush()
    return [scenes[i] for i in ids]


def touch(project: Project) -> None:
    project.content_changed_at = utcnow()


def current_duration(session: Session, script: Script) -> float:
    """Duree ESTIMEE de la voix off (2,5 mots par seconde) : provisoire tant que l'audio n'existe pas."""
    return round(sum(script_service.spoken_duration(s.text) for s in script_service.scenes_of(session, script.id)), 1)


def missing_for_approval(session: Session, script: Script) -> list[str]:
    problems = []
    for scene in script_service.scenes_of(session, script.id):
        if not scene.text.strip() and not scene.on_screen_text.strip():
            problems.append(f"Scène {scene.position + 1} : aucun texte (voix off ou texte à l'écran).")
        if len(scene.visual_prompt.strip()) < 3:
            problems.append(f"Scène {scene.position + 1} : prompt visuel manquant.")
    return problems


# --- versions ---
def _next_version(session: Session, project_id: str) -> int:
    return (session.scalar(select(func.max(Script.version)).where(Script.project_id == project_id)) or 0) + 1


def _copy_scenes(session: Session, source: Script, target: Script) -> None:
    for s in script_service.scenes_of(session, source.id):
        session.add(Scene(project_id=target.project_id, script_id=target.id, position=s.position, text=s.text,
                          on_screen_text=s.on_screen_text, visual_intent=s.visual_intent,
                          visual_prompt=s.visual_prompt, negative_prompt=s.negative_prompt, transition=s.transition,
                          duration_s=s.duration_s, importance=s.importance))


def _clone(session: Session, source: Script, *, project_id: str, version: int, idea_id: str | None) -> Script:
    copy = Script(project_id=project_id, idea_id=idea_id, version=version, hook=source.hook, body=source.body,
                  conclusion=source.conclusion, call_to_action=source.call_to_action,
                  estimated_duration_s=source.estimated_duration_s)
    session.add(copy)
    session.flush()
    _copy_scenes(session, source, copy)
    session.flush()
    return copy


def snapshot(session: Session, script: Script) -> Script:
    """Garde une copie de l'etat actuel dans l'historique. Le script courant garde ses scenes (et ses medias)."""
    copy = _clone(session, script, project_id=script.project_id, version=script.version, idea_id=script.idea_id)
    script.version = copy.version + 1
    session.flush()
    return copy


def restore(session: Session, project: Project, version: int) -> Script:
    """Remet une ancienne version comme version courante, sans effacer les autres."""
    old = session.scalars(select(Script).where(Script.project_id == project.id, Script.version == version)).first()
    if old is None:
        raise ValueError("Version introuvable.")
    restored = _clone(session, old, project_id=project.id, version=_next_version(session, project.id),
                      idea_id=old.idea_id)
    touch(project)
    return restored


def versions(session: Session, project_id: str) -> list[dict[str, Any]]:
    rows = session.scalars(select(Script).where(Script.project_id == project_id).order_by(Script.version.desc()))
    out = []
    for index, script in enumerate(rows):
        scenes = script_service.scenes_of(session, script.id)
        out.append({"version": script.version, "current": index == 0, "scenes": len(scenes),
                    "updated_at": script.updated_at.isoformat(),
                    "preview": (scenes[0].text if scenes else script.hook)[:120]})
    return out


def duplicate(session: Session, source: Project, copy: Project) -> None:
    """Copie le brief, l'idee choisie et le script courant dans `copy`. Aucun media n'est copie."""
    old_brief = brief_of(session, source)
    new_brief = brief_of(session, copy)
    for column in Brief.__table__.columns:
        if column.name not in ("project_id", "updated_at"):
            setattr(new_brief, column.name, getattr(old_brief, column.name))
    idea = session.scalars(select(Idea).where(Idea.project_id == source.id, Idea.selected.is_(True))).first()
    new_idea = None
    if idea is not None:
        new_idea = Idea(project_id=copy.id, title=idea.title, hook=idea.hook, original_angle=idea.original_angle,
                        summary=idea.summary, estimated_duration_s=idea.estimated_duration_s,
                        difficulty=idea.difficulty, resources=list(idea.resources), fit_reason=idea.fit_reason,
                        keywords=list(idea.keywords), visual_style=idea.visual_style, selected=True, batch=1)
        session.add(new_idea)
        session.flush()
    script = script_service.current_script(session, source.id)
    if script is not None and new_idea is not None:
        _clone(session, script, project_id=copy.id, version=1, idea_id=new_idea.id)
    session.flush()


# --- medias obsoletes ---
def staleness(session: Session, project: Project, steps: list[PipelineStep], scenes: list[Scene]) -> dict[str, Any]:
    """Ce qui a ete produit AVANT la derniere modification. Signalement seulement : rien n'est relance."""
    finished = {s.name: s.finished_at for s in steps if s.status == "done" and not (s.output or {}).get("skipped")}
    changed = project.content_changed_at
    visual = max((s.visual_changed_at for s in scenes if s.visual_changed_at), default=None)
    stale_images = []
    for scene in scenes:
        asset = session.scalars(select(Asset).where(Asset.scene_id == scene.id, Asset.kind == "image")
                                .order_by(Asset.created_at.desc())).first()
        if asset is not None and scene.visual_changed_at and asset.created_at < scene.visual_changed_at:
            stale_images.append(scene.id)

    def after(step: str, *moments: Any) -> bool:
        done = finished.get(step)
        return done is not None and any(m is not None and m > done for m in moments)

    return {"images": stale_images, "voice": after("generate_voice", changed),
            "subtitles": after("create_subtitles", changed), "render": after("render_video", changed, visual)}


def _bullets(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines) if lines else "- (aucun)"


def _outline(scenes: list[Scene]) -> str:
    return "\n".join(f"{s.position + 1}. {s.text}" for s in scenes) or "(vide)"
