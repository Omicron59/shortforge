"""Sous-titres animes : 20 styles et 7 effets, rendus en ASS (libass) a l'echelle 1080x1920.

Les mots sont minutes sur la voix off (Whisper ou calcul), puis regroupes en lignes courtes.
Effets : aucun, surlignage du mot dit, rebond du mot dit, karaoke (remplissage), mot a mot,
apparition « pop » et fondu. Polices presentes sur Windows et macOS.
"""

from __future__ import annotations

from typing import Any

EFFECTS = {
    "aucun": "Texte fixe",
    "surlignage": "Le mot dit change de couleur",
    "rebond": "Le mot dit grossit puis revient",
    "karaoke": "Remplissage progressif des mots",
    "mot_a_mot": "Les mots apparaissent un par un",
    "pop": "Chaque ligne apparaît en grossissant",
    "fondu": "Chaque ligne apparaît en fondu",
}

_BASE: dict[str, Any] = {"font": "Arial", "size": 78, "color": "#FFFFFF", "outline_color": "#000000", "outline": 5,
                         "highlight_color": "#FFD400", "position": "bottom", "uppercase": True, "effect": "surlignage",
                         "words_per_line": 3, "box": False, "bold": True}

PRESETS: dict[str, dict[str, Any]] = {
    "classique": {"label": "Classique", "effect": "aucun", "uppercase": False, "words_per_line": 5, "size": 66},
    "classique_jaune": {"label": "Classique jaune", "effect": "surlignage"},
    "impact": {"label": "Impact", "font": "Impact", "size": 92, "effect": "surlignage", "outline": 6},
    "neon": {"label": "Néon", "color": "#E6FFFF", "outline_color": "#00B7FF", "highlight_color": "#FF3CF0",
             "effect": "surlignage", "outline": 4},
    "karaoke": {"label": "Karaoké", "effect": "karaoke", "color": "#FFFFFF", "highlight_color": "#22D3EE"},
    "karaoke_rose": {"label": "Karaoké rose", "effect": "karaoke", "highlight_color": "#FF4FA3"},
    "pop": {"label": "Pop", "effect": "pop", "highlight_color": "#FFFFFF", "size": 86},
    "rebond": {"label": "Rebond", "effect": "rebond", "highlight_color": "#7CFF4F"},
    "mot_a_mot": {"label": "Mot à mot", "effect": "mot_a_mot", "words_per_line": 4},
    "boite_noire": {"label": "Boîte noire", "box": True, "outline_color": "#000000", "outline": 14,
                    "effect": "surlignage", "highlight_color": "#FFD400", "uppercase": False, "size": 64},
    "boite_jaune": {"label": "Boîte jaune", "box": True, "color": "#111111", "outline_color": "#FFD400", "outline": 14,
                    "effect": "aucun", "uppercase": False, "size": 64},
    "minimal": {"label": "Minimal", "effect": "fondu", "uppercase": False, "bold": False, "outline": 3, "size": 60,
                "words_per_line": 6},
    "minimal_bas": {"label": "Minimal bas", "effect": "aucun", "uppercase": False, "bold": False, "outline": 2,
                    "size": 54, "words_per_line": 7, "position": "bottom"},
    "cinema": {"label": "Cinéma", "font": "Georgia", "effect": "fondu", "uppercase": False, "bold": False,
               "size": 62, "words_per_line": 6, "outline": 2},
    "fondu_doux": {"label": "Fondu doux", "effect": "fondu", "color": "#FFF7E6", "uppercase": False, "size": 70},
    "gros_titres": {"label": "Gros titres", "font": "Impact", "size": 120, "words_per_line": 2, "effect": "pop",
                    "position": "middle", "outline": 8},
    "bulle": {"label": "Bulle", "box": True, "color": "#FFFFFF", "outline_color": "#7C3AED", "outline": 16,
              "effect": "pop", "uppercase": False, "size": 62},
    "retro": {"label": "Rétro", "font": "Trebuchet MS", "color": "#FFE8B0", "outline_color": "#7A2E00",
              "highlight_color": "#FF8A00", "effect": "rebond"},
    "menthe": {"label": "Menthe", "color": "#FFFFFF", "outline_color": "#064E3B", "highlight_color": "#34D399",
               "effect": "karaoke"},
    "feu": {"label": "Feu", "font": "Impact", "color": "#FFF1C1", "outline_color": "#7F1D1D",
            "highlight_color": "#FF4500", "effect": "rebond", "size": 90},
}

ALIGNMENTS = {"bottom": 2, "middle": 5, "top": 8}
MARGINS_V = {"bottom": 380, "middle": 0, "top": 260}
# Texte a l'ecran (titre de scene) : en haut, ou au milieu si les sous-titres sont deja en haut.
SCREEN_TEXT_STYLE: dict[str, Any] = {"font": "Arial", "size": 92, "color": "#FFFFFF",
                                     "outline_color": "#000000", "outline": 7}
SCREEN_TEXT_MARGIN_V = 330
EDITABLE = frozenset({"font", "size", "color", "outline_color", "outline", "highlight_color", "position",
                      "uppercase", "effect", "words_per_line", "box", "bold"})


def preset_style(name: str | None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    preset = PRESETS.get(name or "", PRESETS["classique_jaune"])
    style = {**_BASE, **{k: v for k, v in preset.items() if k != "label"}}
    style.update({k: v for k, v in (overrides or {}).items() if k in EDITABLE})
    if style["effect"] not in EFFECTS:
        style["effect"] = "aucun"
    style["words_per_line"] = max(1, min(8, int(style["words_per_line"])))
    return style


def presets_list() -> list[dict[str, Any]]:
    return [{"id": key, "label": value["label"], "style": preset_style(key)} for key, value in PRESETS.items()]


# ── Minutage ──


def words_from_scenes(scenes: list[Any]) -> list[dict[str, Any]]:
    """Mots repartis regulierement sur chaque scene (sans voix off)."""
    words, start = [], 0.0
    for scene in scenes:
        tokens = scene.text.split()
        step = scene.duration_s / len(tokens) if tokens else 0
        words += [{"word": t, "start": round(start + i * step, 3), "end": round(start + (i + 1) * step, 3)}
                  for i, t in enumerate(tokens)]
        start += scene.duration_s
    return words


def group_lines(words: list[dict[str, Any]], words_per_line: int = 3) -> list[dict[str, Any]]:
    """Lignes de sous-titres : quelques mots, coupees aussi aux fins de phrase et aux longues pauses."""
    lines: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for word in words:
        if current and (len(current) >= words_per_line or word["start"] - current[-1]["end"] > 0.6):
            lines.append(current)
            current = []
        current.append(word)
        if word["word"].rstrip().endswith((".", "!", "?", "…")):
            lines.append(current)
            current = []
    if current:
        lines.append(current)
    segments = []
    for i, line in enumerate(lines):
        end = line[-1]["end"]
        if i + 1 < len(lines) and lines[i + 1][0]["start"] - end < 0.35:  # pas de clignotement entre lignes
            end = lines[i + 1][0]["start"]
        segments.append({"start": line[0]["start"], "end": round(end, 3),
                         "text": " ".join(w["word"] for w in line), "words": line})
    return segments


# ── Fichiers ──


def _timestamp(seconds: float, sep: str) -> str:
    ms = round(max(0.0, seconds) * 1000)
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    if sep == ",":
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    return f"{h:d}:{m:02d}:{s:02d}.{ms // 10:02d}"


def to_srt(segments: list[dict[str, Any]]) -> str:
    return "\n".join(f"{i}\n{_timestamp(seg['start'], ',')} --> {_timestamp(seg['end'], ',')}\n{seg['text']}\n"
                     for i, seg in enumerate(segments, 1))


def ass_color(hex_color: str, alpha: str = "00") -> str:
    value = str(hex_color).lstrip("#")
    if len(value) != 6:
        value = "FFFFFF"
    return f"&H{alpha}{value[4:6]}{value[2:4]}{value[0:2]}".upper()


def _clean(text: str, upper: bool) -> str:
    text = text.replace("\n", " ").replace("{", "(").replace("}", ")").replace("\\", "/")
    return text.upper() if upper else text


def screen_texts(scenes: list[Any]) -> list[dict[str, Any]]:
    """Texte a l'ecran de chaque scene, affiche pendant toute la scene (minutage = duree des scenes du montage)."""
    events, start = [], 0.0
    for scene in scenes:
        text = str(getattr(scene, "on_screen_text", "") or "").strip()
        end = start + float(scene.duration_s)
        if text:
            events.append({"start": round(start, 3), "end": round(end, 3), "text": text})
        start = end
    return events


def to_ass(segments: list[dict[str, Any]], style: dict[str, Any],
           screen: list[dict[str, Any]] | None = None) -> str:
    """Sous-titres (style Default) et, s'il y en a, textes a l'ecran (style Ecran, calque au-dessus)."""
    st = {**_BASE, **style}
    position = st["position"] if st["position"] in ALIGNMENTS else "bottom"
    effect = st["effect"]
    primary, secondary = ass_color(st["color"]), ass_color(st["color"])
    if effect == "karaoke":  # avant remplissage : couleur du texte ; apres : couleur de surlignage
        primary = ass_color(st["highlight_color"])
    border_style = 3 if st.get("box") else 1
    back = ass_color(st["outline_color"], "00" if st.get("box") else "80")
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{st['font']},{int(st['size'])},{primary},{secondary},{ass_color(st['outline_color'])},"
        f"{back},{-1 if st.get('bold') else 0},0,0,0,100,100,0,0,{border_style},{int(st['outline'])},"
        f"{0 if st.get('box') else 2},{ALIGNMENTS[position]},80,80,{MARGINS_V[position]},1\n"
        f"{_screen_style(position)}\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    upper = bool(st.get("uppercase"))
    hl = ass_color(st["highlight_color"])
    lines: list[str] = []

    def dialogue(start: float, end: float, text: str) -> None:
        if end - start > 0.01:
            lines.append(f"Dialogue: 0,{_timestamp(start, '.')},{_timestamp(end, '.')},Default,,0,0,0,,{text}")

    for seg in segments:
        words = seg.get("words") or [{"word": w, "start": seg["start"], "end": seg["end"]} for w in seg["text"].split()]
        texts = [_clean(w["word"], upper) for w in words]
        if effect in ("surlignage", "rebond"):
            for i, word in enumerate(words):
                end = words[i + 1]["start"] if i + 1 < len(words) else seg["end"]
                tag = "{\\c" + hl + "&" + ("\\t(0,90,\\fscx118\\fscy118)\\t(90,180,\\fscx100\\fscy100)"
                                            if effect == "rebond" else "") + "}"
                parts = [f"{tag}{t}{{\\r}}" if j == i else t for j, t in enumerate(texts)]
                if i == 0 and word["start"] > seg["start"]:
                    dialogue(seg["start"], word["start"], " ".join(texts))
                dialogue(word["start"], end, " ".join(parts))
        elif effect == "karaoke":
            chunks, cursor = [], seg["start"]
            for word, text in zip(words, texts, strict=True):
                gap = max(0, round((word["start"] - cursor) * 100))
                if gap:
                    chunks.append(f"{{\\k{gap}}}")
                chunks.append(f"{{\\kf{max(1, round((word['end'] - word['start']) * 100))}}}{text} ")
                cursor = word["end"]
            dialogue(seg["start"], seg["end"], "".join(chunks).rstrip())
        elif effect == "mot_a_mot":
            for i, word in enumerate(words):
                end = words[i + 1]["start"] if i + 1 < len(words) else seg["end"]
                dialogue(word["start"], end, " ".join(texts[: i + 1]))
        elif effect == "pop":
            dialogue(seg["start"], seg["end"], "{\\fscx70\\fscy70\\t(0,120,\\fscx100\\fscy100)}" + " ".join(texts))
        elif effect == "fondu":
            dialogue(seg["start"], seg["end"], "{\\fad(140,100)}" + " ".join(texts))
        else:
            dialogue(seg["start"], seg["end"], " ".join(texts))
    for event in screen or []:
        if event["end"] - event["start"] > 0.01:
            lines.append(f"Dialogue: 1,{_timestamp(event['start'], '.')},{_timestamp(event['end'], '.')},Ecran,,0,0,0,,"
                         "{\\fad(150,150)}" + _clean(event["text"], True))
    return header + "\n".join(lines) + "\n"


def _screen_style(subtitle_position: str) -> str:
    sc = SCREEN_TEXT_STYLE
    alignment, margin = (5, 0) if subtitle_position == "top" else (8, SCREEN_TEXT_MARGIN_V)
    return (f"Style: Ecran,{sc['font']},{sc['size']},{ass_color(sc['color'])},{ass_color(sc['color'])},"
            f"{ass_color(sc['outline_color'])},{ass_color(sc['outline_color'], '80')},-1,0,0,0,100,100,0,0,1,"
            f"{sc['outline']},3,{alignment},90,90,{margin},1")
